import asyncio
import hashlib
import json as json_lib
import logging
import httpx
from typing import Dict, Any, Callable, Optional

from fastapi import Request, HTTPException, status, UploadFile
from pydantic import BaseModel

from core.common.models import User

from core.providers import (
    proxy_google_chat,
    proxy_openai_compat_chat,
    proxy_google_tts,
    proxy_google_chat_stream,
    proxy_openai_compat_chat_stream,
    proxy_cohere_chat,
    proxy_cohere_chat_stream,
)
from core.providers.key_manager import ProviderUnavailableError, GetKeyTimeoutError
from core.common import cache_manager
from core.common.utils import get_model_config_by_name
from core.common.models import ChatCompletionResponse
from core.providers.rotation_manager import rotation_manager
from core.common.cache_validator import is_content_safe_to_cache

logger = logging.getLogger("UniversalAIGateway")

PROVIDER_MAP_CHAT = {}
PROVIDER_MAP_EMBEDDING = {}
PROVIDER_MAP_TRANSCRIPTION = {}
PROVIDER_MAP_TTS = {}
PROVIDER_MAP_CHAT_STREAM = {}


def register_providers():
    """Registers provider proxy functions for different services."""
    PROVIDER_MAP_CHAT.update({
        "google": proxy_google_chat,
        "mistral": proxy_openai_compat_chat,
        "cerebras": proxy_openai_compat_chat,
        "groq": proxy_openai_compat_chat,
        "sambanova": proxy_openai_compat_chat,
        "cohere": proxy_cohere_chat,
    })
    PROVIDER_MAP_CHAT_STREAM.update({
        "google": proxy_google_chat_stream,
        "mistral": proxy_openai_compat_chat_stream,
        "cerebras": proxy_openai_compat_chat_stream,
        "groq": proxy_openai_compat_chat_stream,
        "sambanova": proxy_openai_compat_chat_stream,
        "cohere": proxy_cohere_chat_stream,
    })
    PROVIDER_MAP_TTS.update({"google-tts": proxy_google_tts})
    logger.info("Provider maps registered.")


def parse_error_message(e: httpx.HTTPStatusError) -> str:
    """Parses error messages from HTTPStatusError exceptions."""
    try:
        error_json = e.response.json()
        if isinstance(error_json, dict):
            error_details = error_json.get("error", {})
            if isinstance(error_details, dict) and "message" in error_details:
                return str(error_details["message"]).lower()
            if "detail" in error_json:
                return str(error_json["detail"]).lower()
    except (json_lib.JSONDecodeError, httpx.ResponseNotRead, httpx.StreamClosed):
        pass
    except Exception as e_json:
        logger.warning(f"Error parsing error message JSON: {e_json}")

    try:
        return e.response.text.lower()
    except (httpx.ResponseNotRead, httpx.StreamClosed):
        return str(e).lower()
    except Exception:
        return "unknown error"


async def _handle_request_execution(
    request: Request,
    pydantic_request: BaseModel,
    model_config: Dict[str, Any],
    proxy_function: Callable,
    is_streaming: bool,
    file: Optional[UploadFile] = None,
    user: Optional[User] = None,
):
    key_manager = request.app.state.key_manager
    provider = model_config["provider"]

    # --- Model Rotation Logic ---
    # Resolve the model alias to a concrete model ID if applicable
    raw_model_name = model_config.get("model_params", {}).get("model")
    if raw_model_name:
        concrete_model = await rotation_manager.get_next_model(provider, raw_model_name)
        if concrete_model != raw_model_name:
            # Create a shallow copy to avoid mutating the cached global config
            model_config = model_config.copy()
            model_config["model_params"] = model_config["model_params"].copy()
            model_config["model_params"]["model"] = concrete_model
            logger.info(f"[{provider}] Rotated model alias '{raw_model_name}' -> '{concrete_model}'")

    # User Key Priority
    user_key = None
    if user and user.provider_keys and provider in user.provider_keys:
        user_key = user.provider_keys[provider]
        logger.info(f"Using USER key for provider '{provider}' (User: {user.username})")

    if user_key:
        try:
            kwargs = {
                "req": pydantic_request,
                "model_config": model_config,
                "key": user_key,
                "config": request.app.state.config,
                "redis_client": request.app.state.redis_client,
            }
            if file:
                kwargs["file"] = file

            if is_streaming:
                return proxy_function(**kwargs) # Return generator directly
            else:
                return await proxy_function(**kwargs)
        except Exception as e:
            logger.error(f"User key failed for '{provider}': {e}")
            raise ProviderUnavailableError(f"User key failed for '{provider}': {e}")

    # System Key Rotation Logic

    if is_streaming:
        async def rotation_aware_stream_wrapper():
            provider_status = await key_manager.get_full_status()
            total_keys = provider_status.get(provider, {}).get("total_keys", 0)
            max_attempts = total_keys + 1 if not provider.startswith("local") else 1

            rate_limit_retries = 3
            rate_limit_attempt = 0
            last_exception = None

            for attempt in range(max_attempts):
                api_key = None
                stream_started = False
                try:
                    logger.info(f"[{provider}] Streaming attempt {attempt+1}/{max_attempts}")
                    api_key = await key_manager.get_key(provider)

                    kwargs = {
                        "req": pydantic_request,
                        "model_config": model_config,
                        "key": api_key,
                        "config": request.app.state.config,
                        "redis_client": request.app.state.redis_client,
                    }
                    if file:
                        kwargs["file"] = file

                    logger.info(f"[{provider}] stream_wrapper started with key: {api_key[:4]}...")
                    async for chunk in proxy_function(**kwargs):
                        stream_started = True
                        yield chunk

                    logger.info(f"[{provider}] stream_wrapper finished, releasing key")
                    await key_manager.release_key(provider, api_key)
                    return

                except GetKeyTimeoutError as e:
                    logger.warning(f"[{provider}] Key timeout during streaming attempt.")
                    last_exception = e
                    continue

                except Exception as e:
                    last_exception = e

                    # Handle Key Lifecycle
                    if api_key:
                        if isinstance(e, httpx.HTTPStatusError):
                            # Try to read response, but handle if stream is closed
                            try:
                                await e.response.aread()
                            except httpx.StreamClosed:
                                pass # Content might be partially read or stream closed, proceed with existing content
                            except Exception as read_err:
                                logger.warning(f"Could not read error response body: {read_err}")

                            code = e.response.status_code
                            error_msg = parse_error_message(e)
                            if code == 429:
                                await key_manager.quarantine_key(provider, api_key, f"HTTP 429: {error_msg}")
                                logger.warning(f"[{provider}] Rate limit (429). Fail Fast enabled. Switching to fallback.")

                                if not stream_started:
                                     # If stream hasn't started, we can raise this to trigger next provider in chain
                                     raise ProviderUnavailableError(f"HTTP 429: {error_msg}")
                                else:
                                    # If stream STARTED and then hit 429 (unlikely but possible mid-stream), we are stuck.
                                    # We can't cleanly rotate to another provider because we might have already sent bytes.
                                    # Raising exception here will kill the stream (as seen in logs).
                                    # Best effort: log and raise, client receives partial stream + disconnect.
                                    logger.error("429 received AFTER stream started. Cannot cleanly rotate.")
                                    raise e

                            elif code in [401, 403]:
                                await key_manager.retire_key(provider, api_key, f"HTTP {code}: {error_msg}")
                            elif code >= 500:
                                await key_manager.quarantine_key(provider, api_key, f"HTTP {code}: {error_msg}")
                            else:
                                await key_manager.release_key(provider, api_key)
                        else:
                            logger.error(f"[{provider}] Generic error: {e}")
                            await key_manager.release_key(provider, api_key)

                    if stream_started:
                        logger.error(f"Stream failed mid-transmission: {e}")
                        # If stream started, we must raise to signal error to client (even if it breaks the chunked encoding)
                        # We cannot swallow this because the client thinks data is coming.
                        raise e

                    # If stream NOT started, we loop to try next key in this provider
                    await asyncio.sleep(0.2)
                    continue

            # If we exhausted all keys for this provider and stream NEVER started,
            # we raise ProviderUnavailableError so the OUTER loop (route_request) can switch to the next provider/fallback.
            raise ProviderUnavailableError(f"Streaming failed after {max_attempts} attempts. Last error: {last_exception}")

        return rotation_aware_stream_wrapper()

    else:
        # Non-Streaming Rotation
        provider_status = await key_manager.get_full_status()
        total_keys = provider_status.get(provider, {}).get("total_keys", 0)
        max_attempts = total_keys + 1 if not provider.startswith("local") else 1
        last_exception = None
        rate_limit_retries = 3
        rate_limit_attempt = 0
        for attempt in range(max_attempts):
            api_key = None
            try:
                logger.info(f"[{provider}] Attempting to get key (attempt {attempt+1}/{max_attempts})")
                api_key = await key_manager.get_key(provider)
                logger.info(f"[{provider}] Got key: {api_key[:4]}...")
                kwargs = {
                    "req": pydantic_request,
                    "model_config": model_config,
                    "key": api_key,
                    "config": request.app.state.config,
                    "redis_client": request.app.state.redis_client,
                }
                if file:
                    kwargs["file"] = file

                result = await proxy_function(**kwargs)
                await key_manager.release_key(provider, api_key)
                return result
            except GetKeyTimeoutError as e:
                logger.warning(
                    f"[{provider.upper()}] All keys busy. Attempt {attempt + 1}/{max_attempts}."
                )
                last_exception = e
            except httpx.HTTPStatusError as e:
                try:
                    await e.response.aread()
                except httpx.StreamClosed:
                    pass
                except Exception as read_err:
                    logger.warning(f"Could not read error response body: {read_err}")

                error_message = parse_error_message(e)
                last_exception = e
                status_code = e.response.status_code
                if status_code in [401, 403]:
                    await key_manager.retire_key(
                        provider, api_key, f"HTTP {status_code}: {error_message}"
                    )
                elif status_code == 429:
                    await key_manager.quarantine_key(
                        provider, api_key, f"HTTP {status_code}: {error_message}"
                    )
                    logger.warning(f"[{provider.upper()}] Rate limit (429). Fail Fast enabled. Switching to fallback.")
                    raise ProviderUnavailableError(f"HTTP 429: {error_message}")

                elif status_code in [500, 502, 503, 504]:
                    await key_manager.quarantine_key(
                        provider, api_key, f"HTTP {status_code}: {error_message}"
                    )
                else:
                    await key_manager.release_key(provider, api_key)
                await asyncio.sleep(0.2)
            except Exception as e:
                last_exception = e
                if api_key:
                    await key_manager.release_key(provider, api_key)
        raise ProviderUnavailableError(
            f"Failed to execute request to '{provider}' after {max_attempts} attempts. Last error: {last_exception}"
        )


async def execute_request_with_key_rotation(
    request: Request,
    pydantic_request: BaseModel,
    model_config: Dict[str, Any],
    proxy_function: Callable,
    file: Optional[UploadFile] = None,
    user: Optional[User] = None,
):
    return await _handle_request_execution(
        request,
        pydantic_request,
        model_config,
        proxy_function,
        is_streaming=False,
        file=file,
        user=user,
    )


async def execute_streaming_request_with_key_rotation(
    request: Request,
    pydantic_request: BaseModel,
    model_config: Dict[str, Any],
    proxy_function: Callable,
    file: Optional[UploadFile] = None,
    user: Optional[User] = None,
):
    return await _handle_request_execution(
        request,
        pydantic_request,
        model_config,
        proxy_function,
        is_streaming=True,
        file=file,
        user=user,
    )


async def get_all_runnable_models(request: Request):
    config = request.app.state.config
    aliases_map = config.get("router_settings", {}).get("model_group_alias", {})
    model_list = config.get("model_list", [])
    runnable_models = []
    if not aliases_map:
        return []
    for alias_name, internal_name_chain in aliases_map.items():
        if not internal_name_chain:
            continue
        internal_name = internal_name_chain[0]
        model_config = next(
            (m for m in model_list if m.get("model_name") == internal_name), None
        )
        is_agent = False
        reasoning_mode = None
        if model_config:
            agent_settings = model_config.get("model_params", {}).get("agent_settings")
            if agent_settings and agent_settings.get("reasoning_mode"):
                is_agent = True
                reasoning_mode = agent_settings.get("reasoning_mode")
        runnable_models.append(
            {
                "id": alias_name,
                "name": alias_name,
                "is_agent": is_agent,
                "reasoning_mode": reasoning_mode,
            }
        )
    return runnable_models


async def route_request(
    request: Request,
    pydantic_request: BaseModel,
    provider_map: Dict,
    file: Optional[UploadFile] = None,
    user: Optional[User] = None,
):
    logger.info("Entering route_request")
    proxy_config = request.app.state.config
    requested_alias = pydantic_request.model
    is_streaming = getattr(pydantic_request, "stream", False)
    logger.info(f"is_streaming: {is_streaming}")

    priority_chain = (
        proxy_config.get("router_settings", {})
        .get("model_group_alias", {})
        .get(requested_alias)
    )

    if not priority_chain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model alias '{requested_alias}' not found.",
        )

    # --- Agent Load Balancing (Round Robin Start) ---
    # Check if this alias has load balancing metadata (main pool length)
    agent_metadata = proxy_config.get("router_settings", {}).get("agent_metadata", {})
    metadata = agent_metadata.get(requested_alias)

    if metadata and "main_length" in metadata:
        pool_size = metadata["main_length"]
        # Make a copy of the list so we don't mutate the global config
        # Note: priority_chain is likely a list reference from the global dict,
        # so slicing [:] or list() is needed.
        priority_chain = list(priority_chain)

        # Get rotation index (using Redis if available)
        start_index = await rotation_manager.get_rotation_index(
            requested_alias,
            pool_size,
            redis_client=request.app.state.redis_client
        )

        # --- LOAD BALANCING & FAILOVER STRATEGY ---
        # The chain structure is [main_pool_items..., fallback_items...]
        #
        # Strategy: "Pick One, Fail to Fallback"
        # 1. Select ONLY the single model at 'start_index' from the main pool.
        # 2. If that model fails, jump immediately to 'fallbacks'.
        # 3. DO NOT try other models in the main pool (they are for load balancing other requests, not redundancy here).

        if pool_size <= len(priority_chain):
            main_pool = priority_chain[:pool_size]
            fallbacks = priority_chain[pool_size:]

            # Select the target model for this request
            # Ensure index is within bounds (should be guaranteed by rotation logic, but safe guard)
            if start_index < len(main_pool):
                selected_model = main_pool[start_index]
                # Construct new chain: [Selected Target] + [Global Fallbacks]
                priority_chain = [selected_model] + fallbacks
                logger.info(f"Agent '{requested_alias}' LB: Selected '{selected_model}' (Index {start_index}/{pool_size}). Chain: {priority_chain}")
            else:
                logger.error(f"Agent '{requested_alias}' rotation index {start_index} out of bounds for pool size {len(main_pool)}. Using default.")

    # --- Caching Logic ---
    cache_key = None
    if not is_streaming and request.app.state.redis_client:
        try:
            primary_model_name = priority_chain[0]
            primary_model_config = get_model_config_by_name(proxy_config, primary_model_name)
            cache_settings = proxy_config.get("cache_settings", {})

            if primary_model_config:
                cache_key = cache_manager.create_cache_key(
                    pydantic_request, primary_model_config, cache_settings
                )

                if cache_key:
                    cached_response = await cache_manager.get_from_cache(
                        key=cache_key, redis_client=request.app.state.redis_client
                    )
                    # Add extra safety check on read as well
                    if cached_response and is_content_safe_to_cache(cached_response):
                        try:
                            # Verify valid JSON before returning
                            ChatCompletionResponse.model_validate_json(cached_response)
                            logger.info(
                                f"Cache HIT for model '{requested_alias}'. Key: '{cache_key}'"
                            )
                            return ChatCompletionResponse.model_validate_json(cached_response)
                        except Exception as e:
                             logger.warning(f"Cache HIT but invalid JSON for '{requested_alias}': {e}")
                    elif cached_response:
                        logger.warning(f"Cache HIT but UNSAFE content for '{requested_alias}'. Ignoring.")

        except Exception as e:
            logger.error(f"Cache read error for model '{requested_alias}': {e}", exc_info=True)

    last_provider_error = None
    for internal_model_name in priority_chain:
        model_config = get_model_config_by_name(proxy_config, internal_model_name)
        if not model_config:
            logger.warning(f"Model config not found for {internal_model_name}")
            continue

        provider = model_config.get("provider")
        proxy_function = provider_map.get(provider)
        if not proxy_function:
            logger.warning(f"Proxy function not found for provider {provider}")
            continue

        try:
            if is_streaming:
                logger.info(f"Calling execute_streaming_request_with_key_rotation for {provider}")
                # We need to explicitly iterate over the generator here to catch startup errors (like 429)
                # before returning the generator to Starlette.
                # HOWEVER, Starlette expects a generator.
                # To solve this: we wrap the generator in our own generator that handles the fallback logic.

                async def safe_stream_generator():
                    try:
                        generator = await execute_streaming_request_with_key_rotation(
                            request, pydantic_request, model_config, proxy_function, file=file, user=user
                        )
                        async for chunk in generator:
                            yield chunk
                    except ProviderUnavailableError as e:
                         # This catch allows the OUTER loop (for internal_model_name in priority_chain)
                         # to proceed to the next model if the stream failed BEFORE yielding any data.
                         raise e
                    except Exception as e:
                        logger.error(f"Stream error: {e}")
                        raise e

                # We try to "peek" or start the generator. But we can't easily peek an async generator without consuming.
                # The issue is `execute_streaming_request_with_key_rotation` returns a COROUTINE that returns a GENERATOR.
                # If we await it, we get the generator. The error (429) happens INSIDE the generator execution (when we iterate).

                # If we return the generator to Starlette, Starlette iterates it. If it raises, Starlette closes the connection (400/500).
                # To failover, we must iterate it OURSELVES. If it fails immediately, we catch and move on.
                # If it yields data, we yield that data and then continue yielding from it.

                # Optimized Strategy:
                # We create a manual iterator. We try to get the first chunk.
                # If getting first chunk raises 429 -> Catch, Loop to next provider.
                # If getting first chunk succeeds -> Yield it, then return the rest of the iterator.

                generator = await execute_streaming_request_with_key_rotation(
                    request, pydantic_request, model_config, proxy_function, file=file, user=user
                )

                # Check first chunk
                first_chunk = None
                try:
                    iterator = generator.__aiter__()
                    first_chunk = await iterator.__anext__()
                except StopAsyncIteration:
                    # Empty stream? Treat as success (empty response)
                    pass
                except ProviderUnavailableError:
                     # 429 caught here! Re-raise to trigger outer loop fallback
                     logger.warning(f"[{provider}] Failed start stream (429/Unavailable). Falling back.")
                     raise
                except Exception as e:
                     logger.error(f"[{provider}] Failed start stream (Generic): {e}")
                     raise ProviderUnavailableError(f"Stream startup failed: {e}") # Force fallback

                # If we got here, we have a valid stream (or at least one chunk).
                # We define a new generator that yields the first chunk then the rest.
                async def chained_generator():
                    if first_chunk:
                        yield first_chunk
                    async for chunk in iterator:
                        yield chunk

                return chained_generator()

            else:
                result = await execute_request_with_key_rotation(
                    request, pydantic_request, model_config, proxy_function, file=file, user=user
                )

                # --- CACHE WRITE VALIDATION ---
                # Ensure we do not cache empty or error-like responses (Poisoning prevention)
                should_cache = False
                if not is_streaming and request.app.state.redis_client and result and cache_key:
                    if result.choices and len(result.choices) > 0:
                        content = result.choices[0].message.content

                        # Enhanced validation logic
                        if is_content_safe_to_cache(content):
                            should_cache = True
                        else:
                            logger.warning(f"Skipping cache write for model '{requested_alias}': Content deemed unsafe.")
                    else:
                        logger.warning(f"Skipping cache write for model '{requested_alias}': Response has no choices.")

                if should_cache:
                    try:
                        cache_settings = proxy_config.get("cache_settings", {})
                        ttl = cache_settings.get("ttl_seconds", 3600)
                        await cache_manager.set_to_cache(
                            key=cache_key,
                            value=result.model_dump_json(),
                            redis_client=request.app.state.redis_client,
                            ttl_seconds=ttl,
                        )
                        logger.info(
                            f"Cache SET for model '{requested_alias}'. Key: '{cache_key}'"
                        )
                    except Exception as e:
                        logger.error(
                            f"Cache write error for model '{requested_alias}': {e}"
                        )

                return result
        except ProviderUnavailableError as e:
            logger.warning(
                f"PROVIDER [{provider.upper()}] UNAVAILABLE. Reason: {e}. Switching..."
            )
            last_provider_error = e
        except HTTPException as e:
            raise e

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"All providers for '{requested_alias}' are unavailable. Last error: {last_provider_error}",
    )
