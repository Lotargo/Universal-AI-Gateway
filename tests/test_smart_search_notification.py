import asyncio
import json
import logging
from unittest.mock import MagicMock, AsyncMock, patch
from core.engine.native_driver import NativeDriver
from core.tools.native_tools import NATIVE_TOOL_FUNCTIONS

# Configure logging to see output
logging.basicConfig(level=logging.DEBUG)

# Mock Messages for fast testing
TEST_MESSAGES = [
    {"delay": 0, "message": "\n\n> MSG_1"},
    {"delay": 0.2, "message": "\n\n> MSG_2"},
    {"delay": 0.2, "message": "\n\n> MSG_3"}
]

async def mock_smart_search(query):
    print("Mock Smart Search Started")
    await asyncio.sleep(1.0) # Longer than all messages
    print("Mock Smart Search Finished")
    return "Search Result"

async def run_test():
    # Mock Manager
    manager = MagicMock()
    manager.session_id = "test_session"
    manager.initial_payload = {
        "user_query": "test query",
        "agent_settings": {}
    }
    manager.main_config = {
        "enrichment_settings": {"enable_native_detection": True},
        "native_tool_toggles": {"smart_search": True},
        "enable_smart_search": True
    }

    # Mock session store
    manager.session_store.is_cancelled = AsyncMock(return_value=False)

    # Mock tool orchestrator
    manager.tool_orchestrator.tools_initialized = True
    manager.tool_orchestrator.mcp_manager = None

    async def llm_step_gen(*args, **kwargs):
        tool_call_chunk = {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"name": "smart_search", "arguments": '{"query": "foo"}'}
                    }]
                }
            }]
        }
        yield f"data: {json.dumps(tool_call_chunk)}"
        yield "data: [DONE]"

    async def llm_step_final(*args, **kwargs):
        chunk = {
            "choices": [{
                "delta": {
                    "content": "Final Answer"
                }
            }]
        }
        yield f"data: {json.dumps(chunk)}"
        yield "data: [DONE]"

    call_count = 0
    async def execute_llm_step_mock(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            async for x in llm_step_gen(): yield x
        else:
             async for x in llm_step_final(): yield x

    manager._execute_llm_step = execute_llm_step_mock

    # Mock _yield_event
    async def yield_event_mock(type, data):
        return f"EVENT: {type} - {data}"
    manager._yield_event = yield_event_mock

    # Mock _call_tool_with_retry
    manager._call_tool_with_retry = AsyncMock()

    # Instantiate Driver
    driver = NativeDriver(manager)

    # Inject Mock Tool
    original_tool = NATIVE_TOOL_FUNCTIONS.get("smart_search")
    NATIVE_TOOL_FUNCTIONS["smart_search"] = mock_smart_search

    try:
        # Patch Messages
        with patch("core.engine.native_driver.SMART_SEARCH_WAITING_MESSAGES", TEST_MESSAGES):

            print("Starting Driver...")
            collected_events = []
            async for event in driver.run():
                print(f"Received: {event}")
                collected_events.append(event)

            print("Driver Finished.")

            # Verify Messages
            found_msgs = []
            found_separator = False

            for evt in collected_events:
                if "FinalAnswerChunk" in evt:
                    if "MSG_1" in evt: found_msgs.append("MSG_1")
                    if "MSG_2" in evt: found_msgs.append("MSG_2")
                    if "MSG_3" in evt: found_msgs.append("MSG_3")

                    # Check for exact separator chunk: {'content': '\n\n'}
                    # The mock returns repr of dict, so it will look like {'content': '\n\n'}
                    if "{'content': '\\n\\n'}" in evt:
                        found_separator = True

            print(f"Found Messages: {found_msgs}")
            print(f"Found Separator: {found_separator}")

            assert "MSG_1" in found_msgs
            assert "MSG_2" in found_msgs
            assert "MSG_3" in found_msgs
            assert found_separator, "Separator \\n\\n not found!"
            assert "Final Answer" in str(collected_events)
    finally:
        if original_tool:
             NATIVE_TOOL_FUNCTIONS["smart_search"] = original_tool

if __name__ == "__main__":
    asyncio.run(run_test())
