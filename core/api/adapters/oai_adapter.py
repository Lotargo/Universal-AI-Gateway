import json
import time
import uuid
import logging
from typing import AsyncGenerator

from core.common.models import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
)

logger = logging.getLogger("UniversalAIGateway")

# Define event types for clarity
TEXT_CHUNK_EVENTS = {"text_chunk", "FinalAnswerChunk"}
TOOL_CALL_EVENTS = {"tool_code", "AgentToolCallStart"}
STREAM_END_EVENT = "stream_end"
ERROR_EVENT = "error"


async def oai_stream_adapter(
    custom_stream: AsyncGenerator[str, None], model_name: str
) -> AsyncGenerator[str, None]:
    """
    Adapter that converts the custom event stream from StreamingManager
    into a standard SSE stream compatible with the OpenAI API.
    """
    chunk_id = f"chatcmpl-oai-{uuid.uuid4().hex}"
    created_ts = int(time.time())

    logger.info(
        f"[OAI_ADAPTER] Starting stream for model '{model_name}' with chunk_id '{chunk_id}'."
    )

    try:
        # Send the initial chunk with the role
        first_delta = ChatCompletionChunkDelta(role="assistant")
        first_choice = ChatCompletionChunkChoice(index=0, delta=first_delta)
        first_chunk = ChatCompletionChunk(
            id=chunk_id, created=created_ts, model=model_name, choices=[first_choice]
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"
        logger.debug("[OAI_ADAPTER] Yielding first chunk.")

        async for sse_event in custom_stream:
            if not sse_event.strip() or not sse_event.startswith("data:"):
                continue

            try:
                event_data = json.loads(sse_event[6:])
            except json.JSONDecodeError:
                logger.warning(
                    f"[OAI_ADAPTER] Failed to decode SSE event data: {sse_event[6:]}"
                )
                continue

            event_type = event_data.get("event_type")
            payload = event_data.get("payload", {})
            logger.debug(
                f"[OAI_ADAPTER] Received event: {event_type}, payload: {payload}"
            )

            delta = ChatCompletionChunkDelta()
            finish_reason = None

            if event_type in TEXT_CHUNK_EVENTS:
                # Fix: streaming_manager sends "content", but we looked for "text"
                content = payload.get("text") or payload.get("content", "")
                if content:
                    delta.content = content

            elif event_type in TOOL_CALL_EVENTS:
                tool_calls = payload.get("tool_calls")
                if tool_calls:
                    oai_tool_calls = []
                    for i, call in enumerate(tool_calls):
                        arguments = call.get("arguments", {})
                        if not isinstance(arguments, str):
                            arguments = json.dumps(arguments)

                        oai_tool_calls.append(
                            {
                                "index": i,
                                "id": call.get("id", f"call_{uuid.uuid4().hex}"),
                                "type": "function",
                                "function": {
                                    "name": call.get("name"),
                                    "arguments": arguments,
                                },
                            }
                        )

                    delta.tool_calls = oai_tool_calls
                    finish_reason = (
                        "tool_calls"  # Critical fix: Set finish_reason for tool calls
                    )

            elif event_type == STREAM_END_EVENT:
                finish_reason = payload.get("finish_reason", "stop")

            elif event_type == ERROR_EVENT:
                delta.content = f"Error: {payload.get('error', 'Unknown error')}"

            if delta.content or delta.tool_calls or finish_reason:
                choice = ChatCompletionChunkChoice(
                    index=0, delta=delta, finish_reason=finish_reason
                )
            else:
                logger.debug(f"[OAI_ADAPTER] Ignoring empty event type: {event_type}")
                continue
            chunk = ChatCompletionChunk(
                id=chunk_id, created=created_ts, model=model_name, choices=[choice]
            )
            yield f"data: {chunk.model_dump_json()}\n\n"

    except Exception as e:
        logger.error(
            f"[OAI_ADAPTER] An unhandled error occurred in the adapter: {e}",
            exc_info=True,
        )
        error_payload = {"error": f"An unhandled error occurred in the adapter: {e}"}
        yield f"data: {json.dumps(error_payload)}\n\n"

    finally:
        logger.info(f"[OAI_ADAPTER] Sending [DONE] for chunk_id '{chunk_id}'.")
        yield "data: [DONE]\n\n"
