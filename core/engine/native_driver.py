import json
import logging
import asyncio
import uuid
from typing import AsyncGenerator, Dict, Any, List, Optional
from core.common.models import ChatCompletionRequest
from core.common.errors import LLMBadRequestError
from core.tools.native_tools import NATIVE_TOOL_FUNCTIONS, GATEKEEPER_TOOLS
from core.tools.native.google_search import GOOGLE_SEARCH_DEF
from core.common.clock import get_current_datetime_str
from core.config.waiting_messages import SMART_SEARCH_WAITING_MESSAGES

logger = logging.getLogger("UniversalAIGateway")

MAX_AGENT_ITERATIONS = 10

class NativeDriver:
    def __init__(self, manager):
        """
        Args:
            manager: The StreamingManager instance.
                     We use it to access _execute_llm_step, mcp_manager, initial_payload, etc.
        """
        self.manager = manager
        self.session_id = manager.session_id
        self.initial_payload = manager.initial_payload

    def _get_enrichment_settings(self) -> Dict[str, Any]:
        return self.manager.main_config.get("enrichment_settings", {
            "enable_mcp_detection": True,
            "enable_native_detection": True,
            "placeholders": {}
        })

    def _get_enabled_native_tools(self) -> List[Dict[str, Any]]:
        settings = self._get_enrichment_settings()
        if not settings.get("enable_native_detection", True):
            return []

        toggles = self.manager.main_config.get("native_tool_toggles", {})
        enable_smart = self.manager.main_config.get("enable_smart_search", False)

        enabled_tools = []
        for tool_def in GATEKEEPER_TOOLS:
            fn_name = tool_def.get("function", {}).get("name")
            if not fn_name:
                continue

            # Special Logic for Smart Search Override
            if enable_smart:
                # If smart search is on, we skip basic search tools to prevent confusion
                if fn_name in ["google_search", "web_search"]:
                    continue
            else:
                # If smart search is off, we skip it
                if fn_name == "smart_search":
                    continue

            # Default to True if not specified (unless strictly disabled in config logic, but here we use dict get default True)
            if toggles.get(fn_name, True):
                 enabled_tools.append(tool_def)

        return enabled_tools

    async def _enrich_system_prompt(self, system_prompt: str, available_tools_list: List[Dict[str, Any]]) -> str:
        if system_prompt is None:
            return ""

        settings = self._get_enrichment_settings()
        placeholders_config = settings.get("placeholders", {})

        placeholders = {}

        # 1. Tools List
        if placeholders_config.get("tools_list_text", False):
             if available_tools_list:
                tools_json = json.dumps(available_tools_list, indent=2, ensure_ascii=False)
                placeholders["tools_list_text"] = f"**AVAILABLE TOOLS DEFINITION (Use these tools):**\n{tools_json}"
             else:
                placeholders["tools_list_text"] = ""
        else:
            placeholders["tools_list_text"] = ""

        # 2. Server Status
        if placeholders_config.get("server_status_text", False):
             placeholders["server_status_text"] = await self.manager.tool_orchestrator.get_server_status_text()
        else:
             placeholders["server_status_text"] = ""

        # 3. Current Date
        if placeholders_config.get("current_date", False):
             placeholders["current_date"] = get_current_datetime_str()
        else:
             placeholders["current_date"] = ""

        # 4. Draft Context
        if placeholders_config.get("draft_context", False):
             placeholders["draft_context"] = self.initial_payload.get("draft_context", "")
        else:
             placeholders["draft_context"] = ""

        # 5. Tool Instructions
        if placeholders_config.get("tool_instructions", False) and available_tools_list:
            base_instr = """**TOOL USAGE:**
To use a tool, you must use the native function calling capability of the model."""

            if self.manager.main_config.get("enable_smart_search", False):
                 base_instr += "\n\n**IMPORTANT:** For ANY information retrieval from the web, you MUST use the 'smart_search' tool. It will handle searching, reading, and summarizing automatically. Do NOT try to search multiple times. One call is sufficient."

            placeholders["tool_instructions"] = base_instr
        else:
            placeholders["tool_instructions"] = ""

        # 6. System Instruction
        if placeholders_config.get("system_instruction", False):
             placeholders["system_instruction"] = self.initial_payload.get("final_system_instruction") or ""
        else:
             placeholders["system_instruction"] = ""

        try:
            return system_prompt.format(**placeholders)
        except KeyError as e:
            logger.warning(f"Missing placeholder in system prompt: {e}")
            return system_prompt
        except Exception as e:
            logger.error(f"Error enriching system prompt: {e}")
            return system_prompt

    async def _run_waiting_notifications(self, queue: asyncio.Queue):
        """
        Background task to send periodic waiting messages for long-running tools.
        """
        try:
            for item in SMART_SEARCH_WAITING_MESSAGES:
                delay = item.get("delay", 0)
                message = item.get("message", "")

                if delay > 0:
                    await asyncio.sleep(delay)

                if message:
                     # Generate event string and side effects (Kafka)
                     event_str = await self.manager._yield_event("FinalAnswerChunk", {"content": message})
                     await queue.put(event_str)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in waiting notification task: {e}")

    async def run(self) -> AsyncGenerator[str, None]:
        """
        Executes the native tool calling loop.
        """
        enrichment_settings = self._get_enrichment_settings()

        # 1. Initialize Tools
        agent_settings = self.initial_payload.get("agent_settings", {})
        allowed_tool_servers = agent_settings.get("allowed_tool_servers", [])

        # Initialize MCP Tools if servers are configured AND enabled
        if enrichment_settings.get("enable_mcp_detection", True):
            if allowed_tool_servers:
                 async for event in self.manager.tool_orchestrator.initialize_tools(allowed_tool_servers):
                    yield await self.manager._yield_event(event["type"], event["payload"])
        else:
            logger.info("MCP detection disabled by config.")

        # Ensure tools_initialized is True (via tool_orchestrator)
        if not self.manager.tool_orchestrator.tools_initialized:
             self.manager.tool_orchestrator.tools_initialized = True

        # 2. Build Available Tools List
        available_tools = []

        # Add MCP Tools
        if enrichment_settings.get("enable_mcp_detection", True) and self.manager.tool_orchestrator.mcp_manager:
            available_tools.extend(await self.manager.tool_orchestrator.mcp_manager.list_all_tools(allowed_tool_servers))

        # Add Native Tools
        native_tools = self._get_enabled_native_tools()
        if native_tools:
            available_tools.extend(native_tools)

        # 3. Prepare Conversation History
        raw_system_prompt = self.initial_payload.get("final_system_instruction") or ""
        enriched_system_prompt = await self._enrich_system_prompt(raw_system_prompt, available_tools)

        messages = [
            {
                "role": "system",
                "content": enriched_system_prompt,
            },
            {"role": "user", "content": self.initial_payload.get("user_query", "")},
        ]

        # 4. Main Loop
        for iteration in range(MAX_AGENT_ITERATIONS):
            logger.info(f"NativeDriver iteration {iteration} for session {self.session_id}")

            if await self.manager.session_store.is_cancelled():
                yield await self.manager._yield_event(
                    "info", {"message": "Session cancelled by user."}
                )
                break

            pydantic_request = ChatCompletionRequest(
                model="placeholder_native",
                messages=messages,
                stream=True,
                tools=available_tools,
            )

            logger.debug(f"NativeDriver Request Messages (Iter {iteration}): {json.dumps(messages, default=str)}")

            full_response_buffer = ""

            # --- Tool Call Accumulator ---
            # Key: index (int), Value: dict (partial tool call)
            accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}

            # Flags
            is_thinking = False

            # We explicitly set apply_agent_settings=False to prevent _execute_llm_step
            # from attempting to inject a ReAct pattern or system prompt, as _native_driver
            # manages the full conversation state (including system prompt) manually.
            try:
                async for chunk in self.manager._execute_llm_step(
                    pydantic_request,
                    self.initial_payload.get("user_query", ""),
                    "",
                    apply_agent_settings=False
                ):
                    if not isinstance(chunk, str) or not chunk.startswith("data: "):
                        continue

                    data_str = chunk[6:]
                    if data_str.strip() == "[DONE]":
                        continue

                    try:
                        chunk_json = json.loads(data_str)
                        delta = chunk_json.get("choices", [{}])[0].get("delta", {})

                        # A. Handle Reasoning/Thinking (DeepSeek/Groq)
                        reasoning = delta.get("reasoning_content", "")
                        if reasoning:
                            if not is_thinking:
                                yield await self.manager._yield_event("FinalAnswerChunk", {"content": "<think>"})
                                full_response_buffer += "<think>"
                                is_thinking = True

                            full_response_buffer += reasoning
                            yield await self.manager._yield_event("FinalAnswerChunk", {"content": reasoning})

                        # B. Handle Content
                        content = delta.get("content", "")
                        if content:
                            if is_thinking:
                                yield await self.manager._yield_event("FinalAnswerChunk", {"content": "</think>"})
                                full_response_buffer += "</think>"
                                is_thinking = False

                            full_response_buffer += content
                            yield await self.manager._yield_event("FinalAnswerChunk", {"content": content})

                        # C. Handle Tool Calls (Accumulation)
                        if "tool_calls" in delta and delta["tool_calls"]:
                            for tc_delta in delta["tool_calls"]:
                                index = tc_delta.get("index", 0)

                                if index not in accumulated_tool_calls:
                                    accumulated_tool_calls[index] = {
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""}
                                    }

                                # Merge fields
                                if tc_delta.get("id"):
                                    accumulated_tool_calls[index]["id"] = tc_delta.get("id")

                                if tc_delta.get("function"):
                                    fn = tc_delta["function"]
                                    if fn.get("name"):
                                        accumulated_tool_calls[index]["function"]["name"] += fn["name"]
                                    if fn.get("arguments"):
                                        accumulated_tool_calls[index]["function"]["arguments"] += fn["arguments"]

                    except json.JSONDecodeError:
                        continue
            except LLMBadRequestError as e:
                logger.warning(f"NativeDriver caught LLMBadRequestError: {e}")
                if self._handle_provider_error(e, messages):
                    yield await self.manager._yield_event("info", {"message": "Recovering from tool error..."})
                    continue
                else:
                    raise e

            # End of Stream for this turn
            if is_thinking:
                yield await self.manager._yield_event("FinalAnswerChunk", {"content": "</think>"})
                full_response_buffer += "</think>"

            # Check if we have tool calls
            if not accumulated_tool_calls:
                # No tools called -> This is the final answer
                # Yield any remaining buffer if not already yielded (it was yielded in loop)
                # Just break the loop
                break

            # Process Tool Calls
            # Convert accumulator to list sorted by index
            sorted_tool_calls = []
            for i in sorted(accumulated_tool_calls.keys()):
                tc = accumulated_tool_calls[i]
                if not tc["id"]:
                     tc["id"] = f"call_{uuid.uuid4().hex[:8]}"
                     logger.warning(f"Generated missing tool_call_id for index {i}: {tc['id']}")
                sorted_tool_calls.append(tc)

            # Append assistant message with tool calls to history
            messages.append({
                "role": "assistant",
                "content": full_response_buffer if full_response_buffer else None,
                "tool_calls": sorted_tool_calls
            })

            # D. Execute Tools in Parallel
            call_tasks = []
            has_smart_search = False

            for tool_call in sorted_tool_calls:
                fn_name = tool_call.get("function", {}).get("name")
                call_id = tool_call.get("id")

                if not fn_name:
                    continue

                if fn_name == "smart_search":
                    has_smart_search = True

                try:
                    args_str = tool_call.get("function", {}).get("arguments", "{}")
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse arguments for tool {fn_name}: {args_str}")
                    # Mock error result
                    call_tasks.append(self._mock_tool_error(fn_name, call_id, f"JSONDecodeError: Invalid arguments '{args_str}'"))
                    continue

                # Routing: Check if Native Tool or MCP Tool
                if fn_name in NATIVE_TOOL_FUNCTIONS:
                     call_tasks.append(self._exec_native_tool(fn_name, args, call_id))
                else:
                     # MCP Tool Call
                     call_tasks.append(self.manager._call_tool_with_retry(fn_name, args, call_id))

            # Create tools task
            tool_future = asyncio.gather(*call_tasks)

            # Handle Waiting Notifications (Smart Search)
            if has_smart_search:
                notification_queue = asyncio.Queue()
                notification_task = asyncio.create_task(self._run_waiting_notifications(notification_queue))

                while not tool_future.done():
                    # Wait for either tools to finish OR a notification to arrive
                    queue_get_task = asyncio.create_task(notification_queue.get())
                    done, pending = await asyncio.wait(
                        [tool_future, queue_get_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    if queue_get_task in done:
                        # Yield the notification to the stream
                        yield queue_get_task.result()
                    else:
                        # Tools finished (or both), cancel the queue wait
                        queue_get_task.cancel()

                # Cleanup notification task
                notification_task.cancel()
                try:
                    await notification_task
                except asyncio.CancelledError:
                    pass

                # Separator to ensure subsequent LLM response starts on a new line
                yield await self.manager._yield_event("FinalAnswerChunk", {"content": "\n\n"})
            else:
                # Standard wait
                await tool_future

            tool_results = tool_future.result()

            # E. Append Tool Outputs to History
            for result in tool_results:
                content_str = json.dumps(result["result"], ensure_ascii=False) \
                    if isinstance(result["result"], (dict, list)) else str(result["result"])

                messages.append({
                    "role": "tool",
                    "tool_call_id": result["tool_call_id"],
                    "name": result["full_tool_name"],
                    "content": content_str,
                })

        yield await self.manager._yield_event("StreamEnd", {})

    def _handle_provider_error(self, e: Exception, messages: List[Dict[str, Any]]) -> bool:
        """
        Attempts to recover from a provider error (e.g. Groq tool validation).
        Returns True if recovery is possible (messages updated), False otherwise.
        """
        error_str = str(e)
        if "tool_use_failed" in error_str or "failed_generation" in error_str:
            # Try to extract details json
            import re
            match = re.search(r'Details: ({.*})', error_str)
            if match:
                try:
                    details_json = json.loads(match.group(1))
                    failed_gen = details_json.get("failed_generation")
                    msg = details_json.get("message", "Tool validation failed.")

                    if failed_gen:
                        # Append a system message informing the model of its mistake
                        messages.append({
                            "role": "user",
                            "content": f"SYSTEM ERROR: Your previous tool call caused a validation error: {msg}. \nFailed generation: {failed_gen}\nPlease correct your arguments or use a different tool."
                        })
                    else:
                         messages.append({
                            "role": "user",
                            "content": f"SYSTEM ERROR: Your previous request was rejected: {msg}. Please try again."
                        })

                    logger.info("Successfully added recovery message to history.")
                    return True
                except Exception as parse_err:
                    logger.error(f"Failed to parse error details for recovery: {parse_err}")

            # Fallback if regex fails but keyword exists
            messages.append({
                 "role": "user",
                 "content": f"SYSTEM ERROR: Your previous request was rejected by the provider. Error: {error_str}. Please try again with valid tool usage."
            })
            return True

        return False

    async def _exec_native_tool(self, name: str, args: Dict, call_id: str) -> Dict:
        """Executes a native Python function tool."""
        # Double check config just in case?
        # Since this method is internal and only called for tools the model chose (which we filtered),
        # it's redundant but safe.
        toggles = self.manager.main_config.get("native_tool_toggles", {})
        if not toggles.get(name, True):
             return {
                "tool_call_id": call_id,
                "full_tool_name": name,
                "result": f"Error: Tool {name} is disabled by configuration."
            }

        func = NATIVE_TOOL_FUNCTIONS.get(name)
        if not func:
            return {
                "tool_call_id": call_id,
                "full_tool_name": name,
                "result": f"Error: Function {name} not found."
            }

        try:
            logger.info(f"Executing Native Tool: {name} with args {args}")
            res = await func(**args)
            return {
                "tool_call_id": call_id,
                "full_tool_name": name,
                "result": res
            }
        except Exception as e:
            logger.error(f"Native Tool {name} failed: {e}", exc_info=True)
            return {
                "tool_call_id": call_id,
                "full_tool_name": name,
                "result": f"Error: {str(e)}"
            }

    async def _mock_tool_error(self, name: str, call_id: str, error_msg: str) -> Dict:
        return {
            "tool_call_id": call_id,
            "full_tool_name": name,
            "result": f"Error: {error_msg}"
        }
