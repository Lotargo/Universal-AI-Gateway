import httpx
import uuid
import time
import json as json_lib
import logging
from contextlib import asynccontextmanager

from core.providers.rotation_manager import rotation_manager
from core.providers.media_manager import MediaManager
from core.common.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionMessage,
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
)

logger = logging.getLogger("UniversalAIGateway")

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

async def proxy_cohere_chat(
    req: ChatCompletionRequest, model_config: dict, key: str, **kwargs
) -> ChatCompletionResponse:
    """Proxies a chat request to the Cohere V2 API.

    Uses Cohere V2 Chat API which supports multi-turn messages and vision.
    Handles Cloudinary image processing via MediaManager.

    Args:
        req: The chat completion request.
        model_config: Configuration for the model.
        key: API key.
        **kwargs: Additional arguments.

    Returns:
        The chat completion response.
    """
    model_alias = model_config["model_params"]["model"]
    model_name = await rotation_manager.get_next_model("cohere", model_alias)
    api_url = "https://api.cohere.com/v2/chat"

    # 1. Process Messages (Images -> Cloudinary URLs)
    messages = req.messages
    redis_client = kwargs.get("redis_client")
    messages = await MediaManager.process_messages_for_url_provider(messages, redis_client=redis_client)

    # 2. Construct Payload
    payload = {
        "model": model_name,
        "messages": messages, # Cohere V2 accepts OpenAI-like messages structure
    }

    if req.temperature:
        payload["temperature"] = req.temperature
    if req.max_tokens:
        payload["max_tokens"] = req.max_tokens

    # Map other standard params if needed (top_p, etc.)
    if req.top_p:
        payload["p"] = req.top_p

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    async with _get_http_client(kwargs) as client:
        response = await client.post(
            api_url, json=payload, headers=headers, timeout=60.0
        )

    response.raise_for_status()
    data = response.json()

    # V2 Response Format parsing
    # Content is usually a list of blocks
    content_list = data.get("message", {}).get("content", [])
    text_response = ""
    for block in content_list:
        if block.get("type") == "text":
            text_response += block.get("text", "")

    finish_reason = data.get("finish_reason", "stop")
    # Map Cohere reasons to OAI standard if needed
    if finish_reason == "COMPLETE": finish_reason = "stop"
    elif finish_reason == "MAX_TOKENS": finish_reason = "length"

    final_message = ChatCompletionMessage(role="assistant", content=text_response)
    final_choice = ChatCompletionChoice(
        index=0, message=final_message, finish_reason=finish_reason
    )

    usage_data = data.get("usage", {})

    return ChatCompletionResponse(
        id=data.get("id", f"chatcmpl-{uuid.uuid4()}"),
        created=int(time.time()),
        model=model_name,
        choices=[final_choice],
        usage={
            "prompt_tokens": int(usage_data.get("tokens", {}).get("input_tokens", 0)),
            "completion_tokens": int(usage_data.get("tokens", {}).get("output_tokens", 0)),
            "total_tokens": 0, # Calculate if needed
        },
    )


async def proxy_cohere_chat_stream(
    req: ChatCompletionRequest, model_config: dict, key: str, config: dict, **kwargs
):
    """Proxies a streaming chat request to the Cohere V2 API.

    Args:
        req: The chat completion request.
        model_config: Configuration for the model.
        key: API key.
        config: Global configuration.
        **kwargs: Additional args (including redis_client).

    Yields:
        SSE-formatted chunks of the response.
    """
    model_alias = model_config["model_params"]["model"]
    model_name = await rotation_manager.get_next_model("cohere", model_alias)
    api_url = "https://api.cohere.com/v2/chat"

    # 1. Process Messages (Images -> Cloudinary URLs)
    messages = req.messages
    redis_client = kwargs.get("redis_client")
    messages = await MediaManager.process_messages_for_url_provider(messages, redis_client=redis_client)

    payload = {
        "model": model_name,
        "messages": messages,
        "stream": True,
    }

    if req.temperature:
        payload["temperature"] = req.temperature
    if req.max_tokens:
        payload["max_tokens"] = req.max_tokens
    if req.top_p:
        payload["p"] = req.top_p

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    chunk_id = f"chatcmpl-{uuid.uuid4()}"
    created_ts = int(time.time())

    async with _get_http_client(kwargs) as client:
        async with client.stream(
            "POST", api_url, json=payload, headers=headers, timeout=120.0
        ) as response:
            response.raise_for_status()

            is_first_chunk_sent = False
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json_lib.loads(line)
                except Exception:
                    continue

                event_type = data.get("type")

                if event_type == "content-delta":
                    delta_payload = data.get("delta", {})
                    text_content = delta_payload.get("message", {}).get("content", {}).get("text", "")

                    if text_content:
                        if not is_first_chunk_sent:
                            delta = ChatCompletionChunkDelta(role="assistant", content=text_content)
                            is_first_chunk_sent = True
                        else:
                            delta = ChatCompletionChunkDelta(content=text_content)

                        choice = ChatCompletionChunkChoice(index=0, delta=delta)
                        chunk = ChatCompletionChunk(
                            id=chunk_id,
                            created=created_ts,
                            model=model_name,
                            choices=[choice],
                        )
                        yield f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"

                elif event_type == "message-end":
                    finish_reason = data.get("delta", {}).get("finish_reason", "stop")
                    if finish_reason == "COMPLETE": finish_reason = "stop"
                    elif finish_reason == "MAX_TOKENS": finish_reason = "length"

                    delta = ChatCompletionChunkDelta()
                    choice = ChatCompletionChunkChoice(
                        index=0, delta=delta, finish_reason=finish_reason
                    )
                    chunk = ChatCompletionChunk(
                        id=chunk_id,
                        created=created_ts,
                        model=model_name,
                        choices=[choice],
                    )
                    yield f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
                    yield "data: [DONE]\n\n"
