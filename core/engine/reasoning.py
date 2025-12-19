import json
import logging
import re
import asyncio
from typing import AsyncGenerator, Dict, Any, List, Optional, Union

from core.common.models import ChatCompletionRequest
from core.common.errors import LLMBadRequestError
from core.providers.key_manager import ProviderUnavailableError
from core.engine.native_driver import NativeDriver
from core.common.utils import get_model_config_by_name
from core.tools.native_tools import GATEKEEPER_TOOLS, NATIVE_TOOL_FUNCTIONS
from core.common.fuzzy_xml import FuzzyXmlParser

logger = logging.getLogger("UniversalAIGateway")
MAX_AGENT_ITERATIONS = 10

class ReasoningEngine:
    def __init__(self, manager):
        self.manager = manager

    async def run_simple_chat(self) -> AsyncGenerator[str, None]:
        messages = [
            {
                "role": "system",
                "content": self.manager.initial_payload.get("final_system_instruction", ""),
            },
            {"role": "user", "content": self.manager.initial_payload.get("user_query", "")},
        ]
        pydantic_request = ChatCompletionRequest(
            model="placeholder_simple_chat", messages=messages, stream=True
        )

        is_thinking = False

        async for chunk in self.manager._execute_llm_step(
            pydantic_request, self.manager.initial_payload.get("user_query", ""), ""
        ):
            if not isinstance(chunk, str) or not chunk.startswith("data: "):
                continue
            data_str = chunk[6:]
            if data_str.strip() == "[DONE]":
                continue
            try:
                chunk_json = json.loads(data_str)
                delta = chunk_json.get("choices", [{}])[0].get("delta", {})

                reasoning = delta.get("reasoning_content", "")
                content = delta.get("content", "")

                if reasoning:
                    if not is_thinking:
                        yield await self.manager._yield_event("FinalAnswerChunk", {"content": "<think>"})
                        is_thinking = True
                    yield await self.manager._yield_event("FinalAnswerChunk", {"content": reasoning})

                if content:
                    if is_thinking:
                        yield await self.manager._yield_event("FinalAnswerChunk", {"content": "</think>"})
                        is_thinking = False
                    yield await self.manager._yield_event("FinalAnswerChunk", {"content": content})
            except json.JSONDecodeError:
                continue

        if is_thinking:
            yield await self.manager._yield_event("FinalAnswerChunk", {"content": "</think>"})

        yield await self.manager._yield_event("StreamEnd", {})

    async def run_react(self) -> AsyncGenerator[str, None]:
        model_config = get_model_config_by_name(
            self.manager.main_config, self.manager.priority_chain[0]
        )
        agent_settings = model_config.get("model_params", {}).get("agent_settings", {})
        allowed_tool_servers = agent_settings.get("allowed_tool_servers")

        # --- DRAFT & PHASE INITIALIZATION ---
        current_draft = await self.manager.session_store.get_draft()
        current_phase = await self.manager.session_store.get_phase()

        phase_text = f"\n**LAST COMPLETED PHASE:** {current_phase}\n" if current_phase > 0 else "\n**LAST COMPLETED PHASE:** None (Start at Phase 1)\n"
        draft_text = f"\n**CURRENT WORKBOOK (DRAFT):**\n{current_draft}\n" if current_draft else "\n**CURRENT WORKBOOK (DRAFT):**\n(Empty)\n"

        self.manager.initial_payload["draft_context"] = f"{phase_text}{draft_text}"

        # Use Orchestrator
        async for event in self.manager.tool_orchestrator.initialize_tools(allowed_tool_servers, self.manager.initial_payload.get("tools_list_text", "")):
            yield await self.manager._yield_event(event["type"], event["payload"])

        if not self.manager.tool_orchestrator.tools_initialized:
            logger.error("Tools not initialized, cannot proceed with ReAct driver")
            yield await self.manager._yield_event("error", {"error": "Tools initialization failed."})
            return

        # Update initial_payload with discovering tools list json
        self.manager.initial_payload["tools_list_text"] = self.manager.tool_orchestrator.tools_list_json

        user_query = self.manager.initial_payload.get("user_query", "")
        scratchpad = ""
        iteration = 0
        consecutive_empty_responses = 0

        while iteration < MAX_AGENT_ITERATIONS:
            iteration += 1
            logger.info(f"ReAct iteration {iteration} for session {self.manager.session_id}")
            if await self.manager.session_store.is_cancelled():
                yield await self.manager._yield_event("info", {"message": "Session cancelled by user."})
                break

            full_response_buffer = ""
            is_thinking = False
            recovered = False

            try:
                llm_params = {"model": "placeholder", "messages": [], "stream": True}
                for key in ["temperature", "top_p", "max_tokens"]:
                    if key in self.manager.initial_payload and self.manager.initial_payload[key] is not None:
                        llm_params[key] = self.manager.initial_payload[key]
                pydantic_request = ChatCompletionRequest(**llm_params)

                async for chunk in self.manager._execute_llm_step(
                    pydantic_request, user_query, scratchpad
                ):
                    if not isinstance(chunk, str) or not chunk.startswith("data: "):
                        continue
                    data_str = chunk[6:]
                    if data_str.strip() == "[DONE]":
                        continue
                    try:
                        chunk_json = json.loads(data_str)
                        delta = chunk_json.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        reasoning = delta.get("reasoning_content", "")

                        if reasoning:
                            if not is_thinking:
                                full_response_buffer += "<think>"
                                is_thinking = True
                            full_response_buffer += reasoning
                            yield await self.manager._yield_event("FinalAnswerChunk", {"content": reasoning})

                        if content:
                            if is_thinking:
                                full_response_buffer += "</think>"
                                is_thinking = False
                            full_response_buffer += content
                            yield await self.manager._yield_event("FinalAnswerChunk", {"content": content})

                    except json.JSONDecodeError:
                        continue

                if is_thinking:
                    full_response_buffer += "</think>"
                    is_thinking = False

            except LLMBadRequestError as e:
                error_str = str(e)
                logger.warning(f"LLM 400 Bad Request: {error_str}")

                # --- SELF-HEALING with Fuzzy Parser ---
                recovered_content = FuzzyXmlParser.extract_from_failed_generation(error_str)

                if recovered_content["thought"] or recovered_content["action"] or recovered_content["final_answer"] or recovered_content["draft"]:
                    logger.info("Recovered valid content from rejected tool call/error.")

                    if recovered_content["thought"]:
                        formatted_thought = f"<THOUGHT>{recovered_content['thought']}</THOUGHT>"
                        yield await self.manager._yield_event("FinalAnswerChunk", {"content": formatted_thought})
                        full_response_buffer += formatted_thought

                    if recovered_content["draft"]:
                        formatted_draft = f"<DRAFT>{recovered_content['draft']}</DRAFT>"
                        yield await self.manager._yield_event("FinalAnswerChunk", {"content": formatted_draft})
                        full_response_buffer += formatted_draft

                    if recovered_content["action"]:
                        formatted_action = f"<ACTION>{recovered_content['action']}</ACTION>"
                        yield await self.manager._yield_event("FinalAnswerChunk", {"content": formatted_action})
                        full_response_buffer += formatted_action

                    if recovered_content["final_answer"]:
                        formatted_final = f"<FINAL_ANSWER>{recovered_content['final_answer']}</FINAL_ANSWER>"
                        yield await self.manager._yield_event("FinalAnswerChunk", {"content": formatted_final})
                        full_response_buffer += formatted_final

                    recovered = True
                    pass

                else:
                    if not recovered:
                         if "<OBSERVATION>System: The previous response" in scratchpad[-200:]:
                             yield await self.manager._yield_event("error", {"error": "Repeated format errors (400). Aborting."})
                             return

                         warn_msg = "\n<OBSERVATION>System: The previous response was rejected due to invalid format (400). Please output a valid thought or action.</OBSERVATION>\n"
                         scratchpad += warn_msg
                         yield await self.manager._yield_event("warning", {"message": "Provider rejected tool output (400). Requesting retry..."})
                         continue

            except ProviderUnavailableError:
                yield await self.manager._yield_event("error", {"error": "LLM providers unavailable."})
                return
            except Exception as e:
                yield await self.manager._yield_event("error", {"error": f"LLM step failed: {e}"})
                return

            # --- Fuzzy Parsing of the Response ---
            parsed = self._parse_react_response(full_response_buffer)

            # Lenient Fallback
            if not parsed["action"]:
                 module_match_raw = re.search(r">>> MODULE:\s*(.+)", full_response_buffer, re.IGNORECASE)
                 if module_match_raw:
                     parsed["action"] = full_response_buffer

            # SELF-HEALING: Garbage Collection
            if not parsed["thought"] and not parsed["action"] and not parsed["final_answer"] and not parsed["draft"]:
                clean_buffer = full_response_buffer.strip()
                if clean_buffer and len(clean_buffer) > 10:
                    parsed["thought"] = clean_buffer
                    logger.info("Fuzzy Parser: Treated raw text as thought.")
                else:
                     logger.warning("Agent output was empty or unparseable. Skipping history update.")
                     scratchpad += "\n<OBSERVATION>System: The previous response was empty or invalid. Please provide a thought or action.</OBSERVATION>\n"
                     continue

            # --- DRAFT UPDATING & PHASE TRACKING ---
            updated_state = False

            # Update Draft
            if parsed["draft"]:
                current_draft = parsed["draft"]
                await self.manager.session_store.save_draft(current_draft)
                updated_state = True
                scratchpad += "\n<OBSERVATION>System: Draft/Notebook updated successfully.</OBSERVATION>\n"

            # Update Phase
            if parsed.get("thought_attrs") and "title" in parsed["thought_attrs"]:
                 title = parsed["thought_attrs"]["title"]
                 nums = [int(n) for n in re.findall(r"\d+", title)]
                 if nums:
                     max_phase = max(nums)
                     if max_phase > current_phase:
                         current_phase = max_phase
                         await self.manager.session_store.save_phase(current_phase)
                         updated_state = True
                         logger.info(f"Updated Session Phase to {current_phase}")

            # Refresh Context for Next Turn
            if updated_state:
                phase_text = f"\n**LAST COMPLETED PHASE:** {current_phase}\n" if current_phase > 0 else "\n**LAST COMPLETED PHASE:** None (Start at Phase 1)\n"
                draft_text = f"\n**CURRENT WORKBOOK (DRAFT):**\n{current_draft}\n"
                self.manager.initial_payload["draft_context"] = f"{phase_text}{draft_text}"

            # Normal History Update
            scratchpad += full_response_buffer

            # --- System Note Injection (if recovered) ---
            if recovered:
                 scratchpad += "\n<OBSERVATION>System Note: Previous output was recovered from malformed format. Please ensure strict XML tag closing.</OBSERVATION>\n"

            if parsed["final_answer"]:
                logger.info("Agent reached final answer.")
                break

            if parsed["action"]:
                try:
                    action_json = self._parse_action_json(parsed["action"], full_response_buffer)
                    tool_name = action_json.get("tool_name") or action_json.get("name")
                    kwargs = action_json.get("arguments") or {}

                    if tool_name == "internet_query": tool_name = "smart_search"

                    logger.info(f"--- TOOL DETECTED: {tool_name} ---")

                    # Call Orchestrator
                    observation_dict = await self.manager.tool_orchestrator.call_tool(tool_name, **kwargs)

                    observation_text = json.dumps(observation_dict, ensure_ascii=False)
                    observation_block = f"\n<OBSERVATION>{observation_text}</OBSERVATION>\n"
                    scratchpad += observation_block
                    for char in observation_block:
                        yield await self.manager._yield_event("FinalAnswerChunk", {"content": char})

                except Exception as e:
                    error_msg = f"Invalid action: {e}"
                    observation_block = f"\n<OBSERVATION>{error_msg}</OBSERVATION>\n"
                    scratchpad += observation_block
                    for char in observation_block:
                        yield await self.manager._yield_event("FinalAnswerChunk", {"content": char})
            else:
                if parsed["thought"] or parsed["draft"]:
                    consecutive_empty_responses = 0
                else:
                    logger.warning("Empty response from agent.")
                    if consecutive_empty_responses < 3:
                        consecutive_empty_responses += 1
                        await asyncio.sleep(1.0)
                        continue
                    yield await self.manager._yield_event("error", {"error": "Agent stopped: No valid output."})
                    break

            consecutive_empty_responses = 0

        if iteration >= MAX_AGENT_ITERATIONS:
            yield await self.manager._yield_event("warning", {"message": "Maximum iterations reached."})
        yield await self.manager._yield_event("StreamEnd", {})

    def _parse_react_response(self, text: str) -> Dict[str, Any]:
        """
        Uses the FuzzyXmlParser to robustly extract content.
        """
        return FuzzyXmlParser.parse(text)

    def _parse_action_json(self, action_str: str, full_buffer: str) -> Dict[str, Any]:
        clean = action_str.strip()
        if clean.startswith("```json"): clean = clean[7:]
        if clean.endswith("```"): clean = clean[:-3]
        clean = clean.strip()
        try:
            return json.loads(clean)
        except:
            pass

        module_match = re.search(r">>> MODULE:\s*(.+)", action_str, re.IGNORECASE)
        if module_match:
            name = module_match.group(1).strip()
            return {"tool_name": name, "arguments": {}}
        raise ValueError(f"Could not parse JSON action: {clean[:50]}...")
