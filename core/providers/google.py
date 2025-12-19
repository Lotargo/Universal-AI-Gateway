import httpx
import uuid
import time
import json as json_lib
import base64
import logging
import asyncio
import copy
import hashlib
import re
from contextlib import asynccontextmanager

from core.common.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionMessage,
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    SpeechCreationRequest,
)
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from core.providers.rotation_manager import rotation_manager
from core.config.base.reasoning_models import REASONING_MODEL_CONFIGS
from core.providers.utils.normalization import MessageNormalizer

logger = logging.getLogger("UniversalAIGateway")

# Regex for thought signatures
SIGNATURE_REGEX = re.compile(r'\n<!-- google_signature: (.*?) -->')

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

async def _process_text_for_embedded_images(content: str, key: str, redis_client=None) -> list:
    """
    Scans a text string for embedded base64 images (data:image/...).
    Uses inlineData (raw base64) for Gemini.
    Handles thought signatures in text parts.
    """
    parts = []
    # Match data URIs until a delimiter (quote, paren, space, etc.) to capture full base64
    DATA_URI_REGEX = re.compile(r'(data:image/[^;]+;base64,[^"\)\s\>]+)')
    split_parts = DATA_URI_REGEX.split(content)

    if len(split_parts) > 1:
        for sp in split_parts:
            if sp.startswith("data:image"):
                 try:
                    header, data_str = sp.split(",", 1)
                    mime_type = header.split(":")[1].split(";")[0]
                    # Note: For inlineData we send the base64 string directly, not decoded bytes.
                    parts.append({
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": data_str
                        }
                    })
                 except Exception as e:
                    logger.error(f"Failed to process embedded base64 image string: {e}")
                    parts.append({"text": "[Image processing failed]"})
            else:
                if sp.strip():
                    # Extract Signature logic (Inline for sub-parts)
                    signature_match = SIGNATURE_REGEX.search(sp)
                    clean_text = sp
                    signature = None

                    if signature_match:
                        signature = signature_match.group(1)
                        clean_text = SIGNATURE_REGEX.sub('', sp).strip()

                    if clean_text:
                        part = {"text": clean_text}
                        if signature:
                            part["thought_signature"] = signature
                        parts.append(part)
        return parts

    # Fallback for no images found (just signatures)
    signature_match = SIGNATURE_REGEX.search(content)
    clean_text = content
    signature = None

    if signature_match:
        signature = signature_match.group(1)
        # Remove the signature comment from the text sent to Gemini
        clean_text = SIGNATURE_REGEX.sub('', content).strip()

    if clean_text:
        part = {"text": clean_text}
        if signature:
            part["thought_signature"] = signature
        parts.append(part)

    return parts

async def _process_message_content(content, key: str, redis_client=None):
    """Processes message content to handle both text and multimodal parts (OpenAI -> Gemini)."""
    parts = []

    # Text Handling
    if isinstance(content, str):
        return await _process_text_for_embedded_images(content, key, redis_client)

    # Multimodal List Handling
    elif isinstance(content, list):
        for item in content:
            if item.get("type") == "text":
                text = item.get("text", "")
                text_parts = await _process_text_for_embedded_images(text, key, redis_client)
                parts.extend(text_parts)

            elif item.get("type") == "image_url":
                image_url = item.get("image_url", {}).get("url", "")
                if image_url.startswith("data:"):
                    try:
                        header, data_str = image_url.split(",", 1)
                        mime_type = header.split(":")[1].split(";")[0]
                        # Use inlineData for direct base64 transmission
                        parts.append({
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": data_str
                            }
                        })
                    except Exception as e:
                        logger.error(f"Failed to process image: {e}")
                        parts.append({"text": "[Image processing failed]"})
                else:
                    logger.warning("Google Gemini provider: Only base64 data URIs are supported for inline images.")
                    parts.append({"text": f"[Image URL: {image_url}]"})
    return parts

async def _get_or_create_gemini_cache_from_contents(google_contents, real_model_name, key, redis_client):
    """Creates or retrieves a Google Gemini Context Cache using pre-processed Google Contents."""
    if not redis_client or not google_contents:
        return None

    # Exclude the last message (current turn) from cache
    # google_contents is a list of dicts: [{"role": "user", "parts": [...]}, ...]
    contents_to_cache = google_contents[:-1] if len(google_contents) > 1 else []

    if not contents_to_cache:
        return None

    # Calculate Hash
    # We need to hash everything: text parts and inlineData parts
    hasher = hashlib.md5()

    # Also handle System Instruction if it was embedded differently,
    # but here google_contents usually reflects the "history" part.
    # If system instruction is separate, it should be passed here or handled.
    # In `proxy_google_chat`, `processed_messages` includes everything?
    # MessageNormalizer usually preserves roles.
    # But `_construct_gemini_messages` converts them.

    # Note: `contents` in Gemini Cache API does NOT include systemInstruction (it's a separate field).
    # But `_construct_gemini_messages` maps system to... wait, where?
    # MessageNormalizer might leave 'system' roles?
    # `_construct_gemini_messages` ignores 'system' roles in the loop if they aren't mapped?
    # Checking `_construct_gemini_messages`: It doesn't seem to explicitly handle 'system' role mapping
    # other than skipping or treating as 'user'?
    # Actually, `_get_or_create_gemini_cache` (old) extracted system instruction manually.
    # We need to preserve that behavior.

    # Let's rebuild the hash logic to iterate over `contents_to_cache` structure
    for msg in contents_to_cache:
        role = msg.get("role", "")
        hasher.update(role.encode("utf-8"))
        for part in msg.get("parts", []):
            if "text" in part:
                hasher.update(part["text"].encode("utf-8"))
            if "inlineData" in part:
                # Hash the base64 data + mime
                hasher.update(part["inlineData"].get("mimeType", "").encode("utf-8"))
                # Hash the data string (it's base64)
                hasher.update(part["inlineData"].get("data", "").encode("utf-8"))
            if "functionCall" in part:
                hasher.update(json_lib.dumps(part["functionCall"], sort_keys=True).encode("utf-8"))
            if "functionResponse" in part:
                hasher.update(json_lib.dumps(part["functionResponse"], sort_keys=True).encode("utf-8"))

    # We assume System Instruction is relatively static or included in the caller's logic.
    # Ideally, we should pass system_instruction separately if it exists.
    # For now, let's hash the contents.

    # Check total length/size proxy (rough estimate)
    # Gemini requires ~32k tokens.
    # A base64 image is large, so it satisfies the cache requirement easily.
    # We'll use a rough char count of text + data length
    total_chars = 0
    for msg in contents_to_cache:
        for part in msg.get("parts", []):
            if "text" in part: total_chars += len(part["text"])
            if "inlineData" in part: total_chars += len(part["inlineData"]["data"])

    if total_chars < 10000: # Lowered threshold slightly, but usually images are big
        return None

    content_hash = hasher.hexdigest()
    key_suffix = key[-6:]
    cache_redis_key = f"gemini_context_cache:{key_suffix}:{real_model_name}:{content_hash}"

    cached_resource = await redis_client.get(cache_redis_key)
    if cached_resource:
        logger.info(f"[Gemini Context Cache] HIT: {cached_resource}")
        return cached_resource

    logger.info(f"[Gemini Context Cache] MISS: Creating new cache for ~{total_chars} chars (incl. inlineData)...")
    creation_url = "https://generativelanguage.googleapis.com/v1beta/cachedContents"

    payload = {
        "model": f"models/{real_model_name}",
        "ttl": "3600s",
        "contents": contents_to_cache
    }

    # IMPORTANT: System instruction is NOT in `contents` usually.
    # We need to extract it if we want to cache it.
    # Current `_construct_gemini_messages` does not produce a "system" role in `contents`
    # (Gemini API expects "user" or "model" or "function" in `contents`).
    # If the user passed a system message, it should be in `systemInstruction` field of cache, NOT `contents`.

    # To fix this properly without changing `_construct_gemini_messages` return type too much:
    # We can rely on the fact that `proxy_google_chat` creates the system instruction separately if needed,
    # OR we can accept `system_instruction` as an argument here.
    # Let's modify the signature in the next step or assume it's passed in `google_contents` if encoded?
    # No, `_construct_gemini_messages` filters out system roles usually?
    # Let's check `_construct_gemini_messages` implementation again (it was in the read_file output).
    # It converts 'system' to 'user' OR skips?
    # The previous `_get_or_create_gemini_cache` handled system instruction manually from original messages.

    # Correction: `_construct_gemini_messages` iterates and maps role="system" -> role="user" usually?
    # Let's look at `_construct_gemini_messages` in this file.
    # It says: `role = "model" if msg.get("role") == "assistant" else "user"`
    # So system becomes user.
    # Gemini supports system instructions separately.
    # However, for caching, if it's in `contents`, it's cached as a user message.
    # If we want it as systemInstruction in cache, we need to separate it.
    # For now, treating it as User message in cache is "safe" enough for functionality,
    # though technically less "correct" than `systemInstruction`.

    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(creation_url, json=payload, headers=headers, timeout=20.0)
            resp.raise_for_status()
            resource_name = resp.json().get("name")
            if resource_name:
                await redis_client.set(cache_redis_key, resource_name, ex=3500)
                logger.info(f"[Gemini Context Cache] Created: {resource_name}")
                return resource_name
    except Exception as e:
        logger.error(f"[Gemini Context Cache] Creation failed: {e}")
        return None
    return None

async def _construct_gemini_messages(messages, key, redis_client):
    """Constructs the Gemini 'contents' payload, injecting signatures from Redis/Content."""
    google_contents = []

    for msg in messages:
        # Map roles.
        # Note: Gemini `contents` supports 'user', 'model'. 'system' is usually handled separately.
        # But if passed here, we map to 'user' to ensure it appears in the chat stream if not extracted.
        role = "model" if msg.get("role") == "assistant" else "user"

        if msg.get("role") == "tool":
            # Function Response
            tool_name = msg.get("name", "unknown_tool")
            original_content = msg.get("content", "")
            try:
                tool_response_data = json_lib.loads(original_content)
            except (json_lib.JSONDecodeError, TypeError):
                tool_response_data = {"content": original_content}

            google_contents.append({
                "role": "function",
                "parts": [{
                    "functionResponse": {
                        "name": tool_name,
                        "response": tool_response_data,
                    }
                }]
            })

        elif msg.get("role") == "assistant" and msg.get("tool_calls"):
            # Model message with Function Call(s)
            parts = []

            # 1. Handle Text Content (if any)
            if msg.get("content"):
                text_parts = await _process_message_content(msg.get("content"), key, redis_client)
                parts.extend(text_parts)

            # 2. Handle Tool Calls
            for tc in msg.get("tool_calls"):
                func = tc.get("function", {})
                args = {}
                try:
                    args = json_lib.loads(func.get("arguments", "{}"))
                except:
                    pass

                fc_part = {
                    "functionCall": {
                        "name": func.get("name"),
                        "args": args
                    }
                }

                # INJECT SIGNATURE FROM REDIS
                tool_call_id = tc.get("id")
                if tool_call_id and redis_client:
                    sig_key = f"google_signature:{tool_call_id}"
                    signature = await redis_client.get(sig_key)
                    if signature:
                        if isinstance(signature, bytes):
                            signature = signature.decode('utf-8')
                        fc_part["thought_signature"] = signature

                parts.append(fc_part)

            google_contents.append({"role": "model", "parts": parts})

        else:
            # Standard Text Message
            if msg.get("role") == "assistant" and not msg.get("content"):
                continue

            parts = await _process_message_content(msg.get("content", ""), key, redis_client)
            if not parts:
                 continue
            google_contents.append({"role": role, "parts": parts})

    return google_contents

async def proxy_google_chat(
    req: ChatCompletionRequest, model_config: dict, key: str, **kwargs
) -> ChatCompletionResponse:
    """Proxies a standard chat request to Google Gemini."""
    model_alias = model_config["model_params"]["model"]
    real_model_name = await rotation_manager.get_next_model("google", model_alias)
    redis_client = kwargs.get("redis_client")

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{real_model_name}:generateContent"

    # 1. Normalize Messages
    processed_messages = MessageNormalizer.normalize_for_gemini(req.messages)

    # 2. Construct Full Payload (Contents) FIRST (to include inlineData)
    google_contents = await _construct_gemini_messages(processed_messages, key, redis_client)

    # 3. Try to Create/Get Cache using the constructed contents
    # We pass the full contents; the cache function determines what to cache (everything except last).
    cached_content_name = await _get_or_create_gemini_cache_from_contents(google_contents, real_model_name, key, redis_client)

    # 4. Prepare Final Payload
    # If cached, we send only the delta (the last message usually).
    # But wait, `google_contents` has EVERYTHING.
    # If `cached_content_name` is present, we must ONLY send the messages that are NOT in the cache.
    # The cache function caches `contents[:-1]`. So we send `[contents[-1]]`.

    final_contents = google_contents
    if cached_content_name:
        if len(google_contents) > 0:
            final_contents = [google_contents[-1]]
        else:
            final_contents = [] # Should not happen if we have a user query

    payload = {"contents": final_contents}

    if cached_content_name:
        payload["cachedContent"] = cached_content_name

    if req.tools:
        payload["tools"] = [{"functionDeclarations": [t["function"] for t in req.tools]}]

    generation_config = {}
    if req.temperature is not None: generation_config["temperature"] = req.temperature
    if req.top_p is not None: generation_config["topP"] = req.top_p
    if req.max_tokens is not None: generation_config["maxOutputTokens"] = req.max_tokens
    if req.model_dump(exclude_none=True).get("response_format") == {"type": "json_object"}:
        generation_config["responseMimeType"] = "application/json"

    reasoning_config = REASONING_MODEL_CONFIGS.get(real_model_name)
    if reasoning_config and reasoning_config.get("provider") == "google":
        params = reasoning_config.get("params", {})
        budget = params.get("thinking_budget")
        if isinstance(budget, int) and budget != 0:
            generation_config["thinkingConfig"] = {
                "includeThoughts": True,
                "thinkingBudgetTokenLimit": budget
            }

    if generation_config: payload["generationConfig"] = generation_config
    if "safety_settings" in model_config.get("model_params", {}):
        payload["safetySettings"] = model_config["model_params"]["safety_settings"]

    headers = {"x-goog-api-key": key}

    async with _get_http_client(kwargs) as client:
        response = await client.post(api_url, json=payload, headers=headers, timeout=300.0)

    response.raise_for_status()
    google_resp = response.json()
    usage = google_resp.get("usageMetadata", {})
    finish_reason = "stop"

    if not google_resp.get("candidates"):
        finish_reason = "stop"
        message_content = f"[Blocked: {google_resp.get('promptFeedback', {}).get('blockReason')}]"
        tool_calls = None
    else:
        candidate = google_resp["candidates"][0]
        raw_finish = candidate.get("finishReason", "STOP")
        finish_reason = {"MAX_TOKENS": "length", "SAFETY": "content_filter", "TOOL_CALLS": "tool_calls"}.get(raw_finish, "stop")

        parts = candidate.get("content", {}).get("parts", [])
        extracted_content = ""
        extracted_thoughts = ""
        tool_calls = []

        last_thought_signature = None

        for part in parts:
            if "thought_signature" in part:
                last_thought_signature = part["thought_signature"]

            if "functionCall" in part:
                fc = part["functionCall"]
                call_id = f"call_{uuid.uuid4().hex}"
                tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": fc.get("name"),
                        "arguments": json_lib.dumps(fc.get("args", {})),
                    },
                })
                if last_thought_signature and redis_client:
                    sig_key = f"google_signature:{call_id}"
                    await redis_client.set(sig_key, last_thought_signature, ex=3600)

            if "text" in part:
                if part.get("thought", False):
                    extracted_thoughts += part.get("text", "")
                else:
                    extracted_content += part.get("text", "")

        message_content = extracted_content
        if extracted_thoughts:
            message_content = f"<think>\n{extracted_thoughts}\n</think>\n\n{message_content}"

        if last_thought_signature:
            message_content += f"\n<!-- google_signature: {last_thought_signature} -->"

    final_message = ChatCompletionMessage(
        role="assistant", content=message_content, tool_calls=tool_calls if tool_calls else None
    )
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        object="chat.completion",
        created=int(time.time()),
        model=req.model,
        choices=[ChatCompletionChoice(index=0, message=final_message, finish_reason=finish_reason)],
        usage={
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        },
    )

async def proxy_google_chat_stream(
    req: ChatCompletionRequest, model_config: dict, key: str, config: dict, **kwargs
):
    """Proxies a streaming chat request to Google Gemini."""
    model_alias = model_config["model_params"]["model"]
    real_model_name = await rotation_manager.get_next_model("google", model_alias)
    redis_client = kwargs.get("redis_client")

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{real_model_name}:streamGenerateContent?alt=sse"

    # 1. Normalize
    processed_messages = MessageNormalizer.normalize_for_gemini(req.messages)

    # 2. Construct Full Payload
    google_contents = await _construct_gemini_messages(processed_messages, key, redis_client)

    # 3. Cache
    cached_content_name = await _get_or_create_gemini_cache_from_contents(google_contents, real_model_name, key, redis_client)

    # 4. Prepare Final Payload
    final_contents = google_contents
    if cached_content_name:
        if len(google_contents) > 0:
            final_contents = [google_contents[-1]]
        else:
            final_contents = []

    payload = {"contents": final_contents}
    if cached_content_name: payload["cachedContent"] = cached_content_name

    generation_config = {}
    if req.temperature is not None: generation_config["temperature"] = req.temperature
    if req.top_p is not None: generation_config["topP"] = req.top_p
    if req.max_tokens is not None: generation_config["maxOutputTokens"] = req.max_tokens
    if req.model_dump(exclude_none=True).get("response_format") == {"type": "json_object"}:
        generation_config["responseMimeType"] = "application/json"

    reasoning_config = REASONING_MODEL_CONFIGS.get(real_model_name)
    if reasoning_config and reasoning_config.get("provider") == "google":
        params = reasoning_config.get("params", {})
        budget = params.get("thinking_budget")
        if isinstance(budget, int) and budget != 0:
            generation_config["thinkingConfig"] = {
                "includeThoughts": True,
                "thinkingBudgetTokenLimit": budget
            }

    if generation_config: payload["generationConfig"] = generation_config
    if "safety_settings" in model_config.get("model_params", {}):
        payload["safetySettings"] = model_config["model_params"]["safety_settings"]

    chunk_id = f"chatcmpl-stream-gemini-{uuid.uuid4()}"
    created_ts = int(time.time())
    headers = {"x-goog-api-key": key}

    async with _get_http_client(kwargs) as client:
        timeout = httpx.Timeout(600.0, connect=15.0)
        async with client.stream("POST", api_url, json=payload, headers=headers, timeout=timeout) as response:
            response.raise_for_status()
            is_first_chunk_sent = False
            last_thought_signature = None

            async for line in response.aiter_lines():
                if not line.startswith("data:"): continue
                try:
                    google_chunk = json_lib.loads(line[6:])
                except: continue
                if not google_chunk.get("candidates"): continue

                if not is_first_chunk_sent:
                    yield f"data: {ChatCompletionChunk(id=chunk_id, created=created_ts, model=req.model, choices=[ChatCompletionChunkChoice(index=0, delta=ChatCompletionChunkDelta(role='assistant'))]).model_dump_json(exclude_none=True)}\n\n"
                    is_first_chunk_sent = True

                candidates = google_chunk.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        if "thought_signature" in part:
                            last_thought_signature = part["thought_signature"]

                        if part.get("thought", False):
                            yield f"data: {ChatCompletionChunk(id=chunk_id, created=created_ts, model=req.model, choices=[ChatCompletionChunkChoice(index=0, delta=ChatCompletionChunkDelta(reasoning_content=part.get('text', '')))]).model_dump_json(exclude_none=True)}\n\n"
                        elif "text" in part:
                            yield f"data: {ChatCompletionChunk(id=chunk_id, created=created_ts, model=req.model, choices=[ChatCompletionChunkChoice(index=0, delta=ChatCompletionChunkDelta(content=part.get('text', '')))]).model_dump_json(exclude_none=True)}\n\n"

                try:
                    part = google_chunk["candidates"][0]["content"]["parts"][0]
                    if "functionCall" in part:
                        fc = part["functionCall"]
                        tool_call_id = f"call_{uuid.uuid4().hex}"
                        from core.common.models import ToolCall, FunctionCall

                        if last_thought_signature and redis_client:
                            await redis_client.set(f"google_signature:{tool_call_id}", last_thought_signature, ex=3600)

                        tc = ToolCall(index=0, id=tool_call_id, type="function", function=FunctionCall(name=fc.get("name"), arguments=json_lib.dumps(fc.get("args", {}))))
                        yield f"data: {ChatCompletionChunk(id=chunk_id, created=created_ts, model=req.model, choices=[ChatCompletionChunkChoice(index=0, delta=ChatCompletionChunkDelta(tool_calls=[tc]))]).model_dump_json(exclude_none=True)}\n\n"
                except: pass

            if last_thought_signature:
                signature_content = f"\n<!-- google_signature: {last_thought_signature} -->"
                yield f"data: {ChatCompletionChunk(id=chunk_id, created=created_ts, model=req.model, choices=[ChatCompletionChunkChoice(index=0, delta=ChatCompletionChunkDelta(content=signature_content))]).model_dump_json(exclude_none=True)}\n\n"

            yield f"data: {ChatCompletionChunk(id=chunk_id, created=created_ts, model=req.model, choices=[ChatCompletionChunkChoice(index=0, delta=ChatCompletionChunkDelta(), finish_reason='stop')]).model_dump_json(exclude_none=True)}\n\n"
            yield "data: [DONE]\n\n"

async def proxy_google_tts(req: SpeechCreationRequest, model_config: dict, key: str, **kwargs) -> StreamingResponse:
    """Proxies TTS request."""
    # (Existing TTS logic unchanged)
    api_url = "https://texttospeech.googleapis.com/v1/text:synthesize"
    voice_name = req.voice or "ru-RU-Wavenet-D"
    response_format = req.response_format or "mp3"
    speed = req.speed or 1.0
    lang_code = "ru-RU"
    if len(voice_name.split("-")) >= 2:
        lang_code = "-".join(voice_name.split("-")[:2])

    audio_encoding = {"mp3": "MP3", "opus": "OGG_OPUS", "aac": "MP3", "flac": "FLAC"}.get(response_format.lower(), "MP3")
    payload = {"input": {"text": req.input}, "voice": {"languageCode": lang_code, "name": voice_name}, "audioConfig": {"audioEncoding": audio_encoding, "speakingRate": speed}}
    headers = {"x-goog-api-key": key}

    async with httpx.AsyncClient() as client:
        response = await client.post(api_url, json=payload, headers=headers, timeout=120.0)
    response.raise_for_status()

    audio_bytes = base64.b64decode(response.json().get("audioContent", ""))
    async def audio_streamer(): yield audio_bytes
    return StreamingResponse(audio_streamer(), media_type=f"audio/{'mpeg' if response_format in ['mp3', 'aac'] else response_format}")
