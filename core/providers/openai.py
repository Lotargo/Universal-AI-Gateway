import httpx
import logging
import json as json_lib
import uuid
import time
import os
import asyncio
from contextlib import asynccontextmanager

from core.common.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChunk,
)
from core.providers.rotation_manager import rotation_manager
from core.providers.media_manager import MediaManager
from core.config.base.reasoning_models import REASONING_MODEL_CONFIGS
from core.providers.workflow.composer import PolicyResolver, PayloadComposer
from core.providers.utils.normalization import MessageNormalizer

logger = logging.getLogger("UniversalAIGateway")


def _clean_payload_for_provider(payload: dict, provider: str) -> dict:
    """Sanitizes the payload based on provider restrictions.

    Args:
        payload: The request payload.
        provider: The provider name.

    Returns:
        The sanitized payload.
    """
    # Common cleanup
    if "model" in payload:
        pass  # Handled by caller usually, but fine if here

    # Provider-specific cleanup
    if provider == "groq":
        # Groq does not support 'n', 'logprobs', 'logit_bias', 'top_logprobs'
        # It strictly validates parameters.
        params_to_remove = [
            "n",
            "logprobs",
            "top_logprobs",
            "logit_bias",
            "presence_penalty",
            "frequency_penalty",
        ]

        # Models that do NOT support parallel tool use
        # openai/gpt-oss-20b, openai/gpt-oss-120b, openai/gpt-oss-safeguard-20b
        no_parallel_tools_models = [
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-safeguard-20b"
        ]

        # Check if current model is in the blacklist
        current_model = payload.get("model", "")
        if any(m in current_model for m in no_parallel_tools_models):
             params_to_remove.append("parallel_tool_calls")

        for param in params_to_remove:
            if param in payload:
                del payload[param]

    elif provider == "cerebras":
        # Cerebras does not support 'stream' parameter in non-streaming endpoint or unexpected places.
        # But here we are cleaning general payload.
        # Ensure max_tokens is set as Cerebras often requires it or defaults low?
        # Cerebras also has strict model naming.
        pass

    elif provider == "sambanova":
        pass

    return payload


@asynccontextmanager
async def _get_http_client(kwargs):
    """Context manager to yield a shared or new http client.
    Does NOT close the client if it's shared.
    """
    shared_client = kwargs.get("http_client")
    if shared_client:
        yield shared_client
    else:
        async with httpx.AsyncClient() as client:
            yield client


async def proxy_openai_compat_chat(
    req: ChatCompletionRequest, model_config: dict, key: str, **kwargs
) -> ChatCompletionResponse:
    """Proxies a chat request to an OpenAI-compatible API.

    Supports providers like Groq, Cerebras, Mistral, etc.

    Args:
        req: The chat completion request.
        model_config: Configuration for the model.
        key: API key.
        **kwargs: Additional arguments.

    Returns:
        The chat completion response.
    """
    provider = model_config["provider"]
    api_base = model_config["model_params"].get("api_base", "https://api.openai.com/v1")

    # Provider-specific default bases
    if provider == "mistral":
        api_base = "https://api.mistral.ai/v1"
    elif provider == "groq":
        api_base = "https://api.groq.com/openai/v1"
    elif provider == "cerebras":
        api_base = "https://api.cerebras.ai/v1"
    elif provider == "sambanova":
        api_base = "https://api.sambanova.ai/v1"

    api_url = f"{api_base.rstrip('/')}/chat/completions"
    headers = (
        {"Authorization": f"Bearer {key}"} if not provider.startswith("local") else {}
    )

    # 1. Dump model
    payload = req.model_dump(exclude={"stream"}, exclude_none=True)

    # 2. Process Media (Base64 -> Cloudinary URL)
    # We only do this for providers that likely need URLs instead of huge base64
    # For now, let's enable it for everyone except local providers if CLOUDINARY_URL is present
    if not provider.startswith("local"):
        if "messages" in payload:
            redis_client = kwargs.get("redis_client")
            payload["messages"] = await MediaManager.process_messages_for_url_provider(
                payload["messages"], redis_client=redis_client
            )

    # 3. Overwrite model name from config
    model_alias = model_config["model_params"]["model"]
    real_model_name = await rotation_manager.get_next_model(provider, model_alias)
    payload["model"] = real_model_name

    # 4. Normalize messages (Clean empty, merge)
    if "messages" in payload:
        payload["messages"] = MessageNormalizer.normalize_for_openai(payload["messages"])

    # 5. Apply provider-specific cleanups
    payload = _clean_payload_for_provider(payload, provider)

    if provider == "mistral" and model_config["model_params"].get("safe_mode"):
        payload["safe_prompt"] = True

    async with _get_http_client(kwargs) as client:
        response = await client.post(
            api_url, json=payload, headers=headers, timeout=300.0
        )

    response.raise_for_status()
    response_data = response.json()
    if "usage" not in response_data:
        response_data["usage"] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    return ChatCompletionResponse(**response_data)


async def proxy_openai_compat_chat_stream(
    req: ChatCompletionRequest, model_config: dict, key: str, config: dict, **kwargs
):
    """Proxies a streaming chat request to an OpenAI-compatible API.

    Args:
        req: The chat completion request.
        model_config: Configuration for the model.
        key: API key.
        config: Global configuration.

    Yields:
        SSE-formatted chunks of the response.
    """
    # --- MOCK MODE FOR LOAD TESTING ---
    if os.getenv("MOCK_MODE", "false").lower() == "true":
        chunk_id = f"mock-{uuid.uuid4().hex}"
        created_ts = int(time.time())
        model_name = model_config.get("model_params", {}).get("model", "mock-model")

        # Simulate network latency (adjustable)
        latency = float(os.getenv("MOCK_LATENCY", "0.01"))

        mock_tokens = ["This", " is", " a", " MOCK", " response", " for", " load", " testing."]

        # First chunk with role
        first_chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created_ts,
            "model": model_name,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]
        }
        yield f"data: {json_lib.dumps(first_chunk)}\n\n"

        for token in mock_tokens:
            await asyncio.sleep(latency)
            chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model_name,
                "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}]
            }
            yield f"data: {json_lib.dumps(chunk)}\n\n"

        # Final chunk
        done_chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created_ts,
            "model": model_name,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
        }
        yield f"data: {json_lib.dumps(done_chunk)}\n\n"
        yield "data: [DONE]\n\n"
        return

    provider = model_config["provider"]
    model_params = model_config["model_params"]

    api_base = model_params.get("api_base", "https://api.openai.com/v1")

    if provider == "mistral":
        api_base = "https://api.mistral.ai/v1"
    elif provider == "groq":
        api_base = "https://api.groq.com/openai/v1"
    elif provider == "cerebras":
        api_base = "https://api.cerebras.ai/v1"
    elif provider == "sambanova":
        api_base = "https://api.sambanova.ai/v1"

    api_url = f"{api_base.rstrip('/')}/chat/completions"
    headers = (
        {"Authorization": f"Bearer {key}"} if not provider.startswith("local") else {}
    )

    payload = req.model_dump(exclude_none=True)

    # Process Media (Base64 -> Cloudinary URL)
    if not provider.startswith("local"):
        if "messages" in payload:
             redis_client = kwargs.get("redis_client")
             payload["messages"] = await MediaManager.process_messages_for_url_provider(
                 payload["messages"], redis_client=redis_client
             )

    # Normalize messages
    if "messages" in payload:
        payload["messages"] = MessageNormalizer.normalize_for_openai(payload["messages"])

    model_alias = model_config["model_params"]["model"]
    real_model_name = await rotation_manager.get_next_model(provider, model_alias)

    # Update model in the original req dict logic (though we compose fresh payload below)
    # The payload variable here was derived earlier via req.model_dump().
    # But compose_payload starts fresh from `req`, so we need to ensure `req` or the args passed to compose_payload are correct.
    # Actually, compose_payload calls req.model_dump().

    # Let's resolve the policy first.
    # We need the intended tools from the request to decide offline status.
    initial_tools = req.tools

    policy = PolicyResolver.resolve(
        model_config=model_config,
        real_model_name=real_model_name,
        payload_tools=initial_tools
    )

    # Compose the final payload using the DSL/Policy engine
    payload, output_handling_mode = PayloadComposer.compose(
        req=req,
        policy=policy,
        real_model_name=real_model_name,
        provider=provider
    )

    # Set critical fields that are computed dynamically
    payload["model"] = real_model_name
    payload["stream"] = True

    # Note: _clean_payload_for_provider is still useful for generic cleanup not covered by policy (like cleaning 'n' or 'logprobs')
    payload = _clean_payload_for_provider(payload, provider)

    # Log payload for debugging provider errors
    logger.debug(f"[{provider}] Payload model: {payload.get('model')}")

    if provider == "mistral":
        if model_params.get("safe_mode"):
            payload["safe_prompt"] = True

        # Handle Mistral's requirement: Last message cannot be 'assistant' unless prefix=True
        # This allows prefilling the assistant's response (e.g., for ReAct scratchpads)
        # messages = payload.get("messages", [])
        # if messages and messages[-1].get("role") == "assistant":
        #     messages[-1]["prefix"] = True

    chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
    created_ts = int(time.time())

    logger.info(f"[{provider}] Starting stream for model: {real_model_name}")

    async with _get_http_client(kwargs) as client:
        async with client.stream(
            "POST", api_url, json=payload, headers=headers, timeout=600.0
        ) as response:
            response.raise_for_status()

            is_first_chunk_sent = False
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue

                if line.strip() == "data: [DONE]":
                    break

                json_str = line[6:]
                try:
                    provider_chunk_data = json_lib.loads(json_str)

                    # --- Enhanced Diagnostics for Empty/Weird Chunks ---
                    choices = provider_chunk_data.get("choices")
                    if not choices:
                        # Log if choices missing/empty, but only if it's not a known non-standard chunk or error
                        if "error" not in provider_chunk_data:
                             logger.debug(f"[{provider}] Chunk has no choices: {json_str[:200]}")
                    else:
                        delta = choices[0].get("delta", {})
                        if not delta:
                             logger.debug(f"[{provider}] Chunk has empty delta: {json_str[:200]}")
                    # ---------------------------------------------------

                    # Handle explicit API errors in the stream (common with Groq/Cerebras)
                    if "error" in provider_chunk_data:
                        error_msg = provider_chunk_data["error"].get("message", "Unknown error")
                        logger.error(f"[{provider}] Stream Error: {error_msg}")
                        # We cannot raise exception here easily to break the generator in a clean way
                        # that the client expects, but we can stop yielding and maybe yield an error block
                        # or just break. For now, let's log and break.
                        # Ideally, we should raise an exception that the caller handles.
                        from core.common.errors import LLMBadRequestError
                        # Serialize full error object to allow advanced recovery (e.g. extracting failed_generation)
                        error_json_str = json_lib.dumps(provider_chunk_data["error"])
                        raise LLMBadRequestError(f"Provider Stream Error: {error_msg} | Details: {error_json_str}")

                    # --- Reasoning Output Normalization ---
                    # 1. Cerebras: 'reasoning' field in delta
                    if output_handling_mode == "delta_reasoning_field":
                        if provider_chunk_data.get("choices"):
                            delta = provider_chunk_data["choices"][0].get("delta", {})
                            if "reasoning" in delta and delta["reasoning"]:
                                # Map 'reasoning' to our standard 'reasoning_content'
                                delta["reasoning_content"] = delta.pop("reasoning")

                    # 2. Mistral Structured Content (Existing logic adapted)
                    if (
                        provider_chunk_data.get("choices")
                        and isinstance(provider_chunk_data["choices"], list)
                    ):
                        delta = provider_chunk_data["choices"][0].get("delta", {})
                        content = delta.get("content")

                        # Mistral Thinking Blocks
                        if isinstance(content, list):
                            extracted_text = ""
                            extracted_reasoning = ""

                            for item in content:
                                if item.get("type") == "text":
                                    extracted_text += item.get("text", "")
                                elif item.get("type") == "thinking":
                                    # Recursively extract thinking
                                    thinking_parts = item.get("thinking", [])
                                    if isinstance(thinking_parts, list):
                                        for t_part in thinking_parts:
                                            if t_part.get("type") == "text":
                                                extracted_reasoning += t_part.get("text", "")
                                    elif isinstance(thinking_parts, str):
                                         extracted_reasoning += thinking_parts

                            # Update delta
                            if extracted_text:
                                provider_chunk_data["choices"][0]["delta"]["content"] = extracted_text
                            else:
                                provider_chunk_data["choices"][0]["delta"]["content"] = None # Avoid empty string if only reasoning

                            if extracted_reasoning:
                                provider_chunk_data["choices"][0]["delta"]["reasoning_content"] = extracted_reasoning

                    # 3. Groq Raw Tags (<think>)
                    # Groq returns <think> tags in the 'content' stream.
                    # Normalizing this requires stateful parsing which is complex in a stateless proxy.
                    # We will pass it through as 'content' for now, or the client/adapter handles it.
                    # The 'OAIAdapter' in adapters/oai_react_adapter.py handles <think> tags parsing
                    # if output_format='native_reasoning'.
                    # So for Groq, we just ensure 'reasoning_format'="raw" was sent (done above).

                    clean_chunk_model = ChatCompletionChunk.model_validate(
                        provider_chunk_data
                    )

                    # Ensure role is sent in the first chunk
                    if not is_first_chunk_sent:
                        # Some providers don't send role in the first delta
                        if clean_chunk_model.choices and not clean_chunk_model.choices[0].delta.role:
                             clean_chunk_model.choices[0].delta.role = "assistant"
                        is_first_chunk_sent = True

                    clean_json_str = clean_chunk_model.model_dump_json(
                        exclude_none=True
                    )
                    yield f"data: {clean_json_str}\n\n"

                except (json_lib.JSONDecodeError, Exception) as e:
                    # Check if the exception is our own raised LLMBadRequestError
                    from core.common.errors import LLMBadRequestError
                    if isinstance(e, LLMBadRequestError):
                        # Re-raise it to be caught by the manager
                        raise e

                    # For other errors (like Pydantic validation of weird chunks), log and continue
                    logger.warning(
                        f"OAI-compat stream: Could not parse or validate chunk: {e}. Chunk: '{json_str}'"
                    )
                    # If the chunk was an error object but Pydantic failed, we might want to check for error here too
                    # Simple heuristic: if 'error' key is in json_str, maybe we should crash
                    if '"error":' in json_str and '"failed_generation":' in json_str:
                         raise LLMBadRequestError(f"Provider Stream Error (Raw): {json_str}")

                    continue

            # Ensure proper termination
            yield "data: [DONE]\n\n"
