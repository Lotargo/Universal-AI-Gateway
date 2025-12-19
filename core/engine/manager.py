import asyncio
import json
import uuid
import logging
import re
import time
from typing import AsyncGenerator, Dict, Any, List, Optional, Union

import redis.asyncio as redis
import httpx
from aiokafka import AIOKafkaProducer
from fastapi import Request
from opentelemetry import trace

# --- Local Imports ---
from core.common import kafka_tracing
from core.common.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ChatCompletionMessage,
    ChatCompletionChoice,
)
from core.providers.key_manager import ApiKeyManager, ProviderUnavailableError
from core.mcp.client import MCPManager, MCPError
from .pattern_loader import get_react_pattern
from core.common.models import User
from core.common.utils import get_model_config_by_name
from core.common.clock import get_current_datetime_str
from .model_garage import ModelGarage
from core.tools.native_tools import GATEKEEPER_TOOLS, NATIVE_TOOL_FUNCTIONS
from core.engine.native_driver import NativeDriver
from core.common.errors import LLMBadRequestError

from .session import SessionStateStore
from .tools import ToolOrchestrator
from .reasoning import ReasoningEngine

logger = logging.getLogger("UniversalAIGateway")
tracer = trace.get_tracer(__name__)

# Global rate limiter for Kafka logs to prevent spam
_kafka_log_limiter = {"last_log_time": 0}

def sanitize_json_string(json_str: str) -> str:
    """Removes control characters and garbage from a JSON string.

    Preserves essential whitespace but removes ASCII control characters
    that can break json.loads().

    Args:
        json_str: The input JSON string.

    Returns:
        The sanitized string.
    """
    # Remove all ASCII control characters except \n, \r, \t
    # \x00-\x08, \x0b, \x0c, \x0e-\x1f
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", json_str)

    # Handle BOM at the beginning of the string
    if sanitized.startswith("\ufeff"):
        sanitized = sanitized[1:]

    return sanitized.strip()


# --- SSE Event Formatting ---
def _format_sse_event(event_type: str, data: Dict[str, Any], seq: int) -> str:
    payload = {"event_type": event_type, "payload": data}
    json_payload = json.dumps(payload, ensure_ascii=False)
    return f"data: {json_payload}\n\n"


class StreamingManager:
    def __init__(
        self,
        request: Request,
        session_id: str,
        initial_payload: Dict[str, Any],
        priority_chain: List[str],
        user: Optional[User] = None,
    ):
        self.request = request
        self.user = user
        self.redis_client: redis.Redis = request.app.state.redis_client
        self.kafka_producer: AIOKafkaProducer = request.app.state.kafka_producer
        self.key_manager: ApiKeyManager = request.app.state.key_manager
        self.main_config: Dict[str, Any] = request.app.state.config
        # We assume ModelGarage is initialized in app state (it is usually done in verification endpoint)
        # But for reliability, we can instantiate a temporary helper if needed,
        # though ModelGarage in model_garage.py is designed to load from disk on init.
        # We will check app.state later or create a local instance.
        self.model_garage = ModelGarage(self.key_manager)

        self.session_id = session_id
        self.initial_payload = initial_payload
        self.priority_chain = priority_chain
        logger.warning(f"SESSION {session_id} PRIORITY CHAIN: {priority_chain}")

        self.worker_id = f"worker-{uuid.uuid4().hex}"
        self.sequence_number = 0

        self.session_store = SessionStateStore(self.redis_client, session_id)
        self.tool_orchestrator = ToolOrchestrator(request.app.state, session_id)
        self.reasoning_engine = ReasoningEngine(self)

        self._pending_ui_requests: Dict[str, asyncio.Future] = {}

    async def stream_response(self) -> AsyncGenerator[str, None]:
        if self.redis_client and not await self.session_store.acquire_lease():
            yield await self._yield_event(
                "error", {"error": "Could not acquire lease for this session."}
            )
            return

        # Save user_id to session if available
        if self.user and self.redis_client:
             try:
                 # We use a separate key or update the task hash.
                 # Updating task hash is cleaner.
                 await self.redis_client.hset(
                     f"task:{self.session_id}", "user_id", self.user.id
                 )
             except Exception as e:
                 logger.warning(f"Failed to save user_id to session {self.session_id}: {e}")

        try:
            yield await self._yield_event("info", {"message": "Agent session started."})
            model_config = get_model_config_by_name(
                self.main_config, self.priority_chain[0]
            )
            reasoning_mode = (
                model_config.get("model_params", {})
                .get("agent_settings", {})
                .get("reasoning_mode")
            )

            # --- Dynamic Hybrid Engine ---
            if reasoning_mode == "dynamic_hybrid":
                # driver_generator = self.reasoning_engine.run_dynamic_hybrid()
                yield await self._yield_event("error", {"error": "Dynamic Hybrid mode under maintenance."})
                return
            # --- Legacy Modes ---
            elif reasoning_mode == "native_tool_calling":
                driver = NativeDriver(self)
                driver_generator = driver.run()
            elif reasoning_mode:
                driver_generator = self.reasoning_engine.run_react()
            else:
                driver_generator = self.reasoning_engine.run_simple_chat()

            async for event in driver_generator:
                yield event

        except MCPError as e:
            logger.error(f"MCP Error in session {self.session_id}: {e}", exc_info=True)
            yield await self._yield_event(
                "error", {"error": f"Tool server communication error: {e}"}
            )
        except Exception as e:
            logger.error(
                f"Streaming session {self.session_id} crashed: {e}", exc_info=True
            )
            yield await self._yield_event(
                "error", {"error": f"An unexpected error occurred: {e}"}
            )
        finally:
            await self.session_store.release_lease()
            logger.info(
                f"Streaming session {self.session_id} finished and lease released."
            )

    async def _yield_event(self, event_type: str, data: Dict[str, Any]) -> str:
        self.sequence_number += 1
        event_str = _format_sse_event(event_type, data, self.sequence_number)
        if self.kafka_producer:
            audit_payload = {
                "session_id": self.session_id,
                "event_seq": self.sequence_number,
                "event_type": event_type,
                "payload": data,
            }

            async def _safe_kafka_send():
                try:
                    def json_default(o):
                        if isinstance(o, bytes):
                            return o.decode("utf-8")
                        raise TypeError(f"Type {o.__class__.__name__} not serializable")

                    headers = []
                    kafka_tracing.inject_trace_context(headers)
                    json_value = json.dumps(audit_payload, default=json_default).encode("utf-8")
                    await asyncio.wait_for(
                        self.kafka_producer.send(
                            "agent_audit_events", value=json_value, headers=headers
                        ),
                        timeout=1.0,
                    )
                except Exception as e:
                    # Log error but don't crash. Rate limit logs to avoid terminal spam.
                    current_time = time.time()
                    if current_time - _kafka_log_limiter["last_log_time"] > 60:
                        logger.warning(f"Failed to send audit event to Kafka: {repr(e)}")
                        _kafka_log_limiter["last_log_time"] = current_time

            asyncio.create_task(_safe_kafka_send())
        return event_str

    async def _execute_llm_step(
        self,
        pydantic_request: ChatCompletionRequest,
        user_query: str,
        scratchpad: str,
        apply_agent_settings: bool = True,
    ) -> AsyncGenerator[str, None]:
        last_error_for_chain = None
        from core.providers import (
            proxy_google_chat_stream,
            proxy_openai_compat_chat_stream,
            proxy_cohere_chat_stream,
        )

        provider_map = {
            "google": proxy_google_chat_stream,
            "openai": proxy_openai_compat_chat_stream,
            "mistral": proxy_openai_compat_chat_stream,
            "deepseek": proxy_openai_compat_chat_stream,
            "anthropic": proxy_openai_compat_chat_stream,
            "local": proxy_openai_compat_chat_stream,
            "groq": proxy_openai_compat_chat_stream,
            "cerebras": proxy_openai_compat_chat_stream,
            "sambanova": proxy_openai_compat_chat_stream,
            "cohere": proxy_cohere_chat_stream,
        }

        # Optimization: Reuse shared http_client for connection pooling
        http_client = getattr(self.request.app.state, "http_client", None)

        for model_name in self.priority_chain:
            model_config = get_model_config_by_name(self.main_config, model_name)
            if not model_config:
                continue
            provider = model_config.get("provider")
            proxy_function = provider_map.get(provider)
            if not proxy_function:
                continue

            if apply_agent_settings:
                agent_settings = model_config.get("model_params", {}).get(
                    "agent_settings", {}
                )
                reasoning_mode = agent_settings.get("reasoning_mode")

                # Explicitly skip pattern loading for native tool calling,
                # as it is handled by _native_driver directly and does not use a pattern file.
                if reasoning_mode and reasoning_mode != "native_tool_calling":
                    pattern_data = get_react_pattern(reasoning_mode)
                    if not pattern_data:
                        logger.warning(
                            f"Pattern '{reasoning_mode}' not found for model '{model_name}'. Skipping."
                        )
                        continue

                    server_status_text = await self.tool_orchestrator.get_server_status_text()

                    # GeoIP logic removed as per architecture decision.
                    # IP resolution is handled by external WAF/CDN layers (e.g. Cloudflare).

                    # Conditional Header Injection
                    # Only inject headers if there is actual content for tools or servers
                    tools_list_payload = self.initial_payload.get("tools_list_text", "")
                    if tools_list_payload and tools_list_payload.strip() != "[]":
                        tools_section = f"**AVAILABLE TOOLS DEFINITION (Use these tools):**\n{tools_list_payload}"
                        # --- DYNAMIC INSTRUCTION INJECTION ---
                        # If tools are present, we inject the instructions on HOW to use them.
                        # This prevents models from hallucinating tool usage when no tools are available.
                        tool_instructions_text = """**TOOL USAGE:**
To use a tool, you must output a valid JSON object inside an <ACTION> tag:
<ACTION>
{
  "tool_name": "tool_name_here",
  "arguments": { "arg_name": "value" }
}
</ACTION>
"""
                    else:
                        tools_section = ""
                        # SILENT MODE: No warnings if tools are offline.
                        # Agent will not know about tools at all.
                        tool_instructions_text = ""

                    if server_status_text and server_status_text.strip() != ".":
                         # server_status_text already includes the header from ToolOrchestrator if valid
                         server_section = server_status_text
                    else:
                         server_section = ""

                    placeholders = {
                        "tools_list_text": tools_section,
                        "server_status_text": server_section,
                        "tool_instructions": tool_instructions_text,
                        "current_date": get_current_datetime_str(),
                        "draft_context": self.initial_payload.get("draft_context", ""),
                    }

                    agent_sys_prompt = self.initial_payload.get("final_system_instruction", "")
                    try:
                        # Pre-format to resolve internal placeholders
                        agent_sys_prompt = agent_sys_prompt.format(**placeholders)
                    except Exception:
                        pass

                    placeholders["system_instruction"] = agent_sys_prompt

                    # --- SMART CACHING LOGIC ---
                    if isinstance(pattern_data, dict) and "static_system" in pattern_data:
                        # New structure: Static System + Dynamic Context

                        # Format static system with ALL placeholders to allow Draft injection
                        static_system = pattern_data["static_system"].format(**placeholders)

                        dynamic_context = pattern_data["dynamic_context"].format(**placeholders)

                        # Message 1: Static System (Can be cached by Google or matched by Mistral prefix)
                        messages = [{"role": "system", "content": static_system}]

                        current_turn_messages = self._construct_multiturn_history(
                            user_query, scratchpad
                        )

                        # Inject dynamic context into the FIRST user message of the turn
                        # This keeps the System Prompt static and identical across requests.
                        if current_turn_messages and current_turn_messages[0]["role"] == "user":
                             original_query = current_turn_messages[0]["content"]
                             # Safe injection for structured/list content
                             if isinstance(original_query, str):
                                 current_turn_messages[0]["content"] = f"{dynamic_context}\n\nUser Query: {original_query}"
                             elif isinstance(original_query, list):
                                 # Prepend text block to the list
                                 current_turn_messages[0]["content"] = [
                                     {"type": "text", "text": f"{dynamic_context}\n\nUser Query:"}
                                 ] + original_query

                        pydantic_request.messages = messages + current_turn_messages

                    elif isinstance(pattern_data, list):
                        # Legacy structure (List of dicts)
                        messages = [msg.copy() for msg in pattern_data]
                        for msg in messages:
                            if msg["role"] == "system":
                                msg["content"] = msg["content"].format(**placeholders)
                                break
                        current_turn_messages = self._construct_multiturn_history(
                            user_query, scratchpad
                        )
                        pydantic_request.messages = messages + current_turn_messages
                    else:
                        logger.error(f"Unknown pattern format for {reasoning_mode}")
                        continue

            # Check for user-specific key
            user_key = None
            if self.user and self.user.provider_keys and provider in self.user.provider_keys:
                user_key = self.user.provider_keys[provider]
                logger.info(f"Using USER key for provider '{provider}' (User: {self.user.username})")

            if user_key:
                # User Key Path: Single attempt, no rotation/quarantine (it's their key)
                try:
                    stream_generator = proxy_function(
                        req=pydantic_request,
                        model_config=model_config,
                        key=user_key,
                        config=self.main_config,
                        redis_client=self.redis_client,
                        http_client=http_client
                    )
                    async for chunk in stream_generator:
                        yield chunk
                    return
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 400:
                        logger.error(f"User key 400 Bad Request for '{provider}': {e}")
                        raise LLMBadRequestError(f"Provider returned 400: {e}")
                    logger.error(f"User key failed for '{provider}': {e}")
                    last_error_for_chain = e
                    continue
                except Exception as e:
                    logger.error(f"User key failed for '{provider}': {e}")
                    last_error_for_chain = e
                    continue

            # System Key Path (Standard Rotation)
            max_key_attempts = 3
            for attempt in range(max_key_attempts):
                api_key = await self.key_manager.get_key(provider)
                if not api_key:
                    last_error_for_chain = ProviderUnavailableError(
                        f"No keys for '{provider}'"
                    )
                    break
                try:
                    stream_generator = proxy_function(
                        req=pydantic_request,
                        model_config=model_config,
                        key=api_key,
                        config=self.main_config,
                        redis_client=self.redis_client,
                        http_client=http_client
                    )
                    async for chunk in stream_generator:
                        yield chunk
                    await self.key_manager.release_key(provider, api_key)
                    return
                except httpx.HTTPStatusError as e:
                    # Specific handling for 400 Bad Request
                    if e.response.status_code == 400:
                         logger.error(f"[{provider}] 400 Bad Request encountered. Not quarantining. Error: {e}")
                         # Release key since it's valid, just the request was bad
                         await self.key_manager.release_key(provider, api_key)
                         # Raise special error to be caught by _react_driver for recovery
                         raise LLMBadRequestError(f"Provider returned 400 Bad Request: {e}")

                    # For other status codes (401, 5xx), fall through to general exception handling (quarantine)
                    last_error_for_chain = e
                    await self.key_manager.quarantine_key(provider, api_key, str(e))

                except asyncio.CancelledError:
                    # Handle cancellation (e.g. client disconnect) to prevent key leak
                    logger.warning(f"Stream cancelled for {provider}. Releasing key.")
                    await self.key_manager.release_key(provider, api_key)
                    raise

                except LLMBadRequestError as e:
                    # Explicitly catch and re-raise LLMBadRequestError from proxy logic
                    # to bypass key rotation and trigger Advanced Recovery in _react_driver
                    # Release key as it's a logic error, not a key issue
                    await self.key_manager.release_key(provider, api_key)
                    raise e

                except Exception as e:
                    last_error_for_chain = e
                    await self.key_manager.quarantine_key(provider, api_key, str(e))
        raise ProviderUnavailableError(
            f"All providers failed. Last error: {last_error_for_chain}"
        )

    def _construct_multiturn_history(
        self, user_query: str, scratchpad: str
    ) -> List[Dict[str, str]]:
        """Constructs the conversation history for the current turn."""
        messages = [{"role": "user", "content": user_query}]
        if scratchpad:
            messages.append({"role": "assistant", "content": scratchpad})
            # Add a user continuation prompt to satisfy API requirements (Google)
            # and force model continuation (Mistral).
            # Check if user_query has image?
            # Actually, `user_query` is usually just text here from `self.manager.initial_payload.get("user_query")`
            # Wait, `run_react` in `reasoning.py` gets `user_query` from `initial_payload`.
            # Is that a string or list?
            # It seems `initial_payload` comes from the API request.
            # If `user_query` is multimodal (list), we need to be careful.

            # If scratchpad exists (we are in ReAct loop), we append a user prompt.
            # Gemma/Gemini 400 can happen if we have [User(Image), Model(Thought), User(Text)].
            # Actually that should be fine.
            # But if `user_query` is a list (image), then `messages[0]` is list.
            # `messages[2]` is text.
            # This is generally allowed.

            messages.append({"role": "user", "content": "Proceed with the next step."})
        return messages

    async def _call_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        return await self.tool_orchestrator.call_tool(tool_name, **kwargs)

    @staticmethod
    async def cancel_session(redis_client: redis.Redis, session_id: str) -> bool:
        return await SessionStateStore.cancel_session(redis_client, session_id)
