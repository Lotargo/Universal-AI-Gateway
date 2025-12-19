import logging
import json as json_lib
import uuid
import collections

from fastapi import APIRouter, Request, HTTPException, Form, UploadFile, File, Depends
from fastapi.responses import StreamingResponse

from core.api.auth_utils import get_current_user
from core.common.models import User
from core.common.models import (
    ChatCompletionRequest,
    ModelCard,
    ModelList,
    EmbeddingRequest,
    EmbeddingResponse,
    TranscriptionModel,
    TranscriptionResponse,
    SpeechCreationRequest,
)
from core.common.utils import get_model_config_by_name
from core.api.services import (
    route_request,
    get_all_runnable_models,
    PROVIDER_MAP_CHAT,
    PROVIDER_MAP_CHAT_STREAM,
    PROVIDER_MAP_EMBEDDING,
    PROVIDER_MAP_TRANSCRIPTION,
    PROVIDER_MAP_TTS,
)
from core.api.adapters.oai_adapter import oai_stream_adapter
from core.api.adapters.oai_react_adapter import oai_react_adapter
from core.engine.manager import StreamingManager
from core.api.middleware.rate_limit import limiter
from core.providers.rotation_manager import rotation_manager

logger = logging.getLogger("UniversalAIGateway")

router = APIRouter()


@router.get(
    "/v1/models", response_model=ModelList, summary="OAI-compatible model list endpoint"
)
async def handle_get_models(request: Request):
    """Returns a list of available models in OpenAI-compatible format."""
    logger.info("Received request for OAI model list.")
    runnable_models = await get_all_runnable_models(request)
    oai_models_list = [ModelCard(id=model["id"]) for model in runnable_models]
    return ModelList(data=oai_models_list)


@router.get("/v1/models/all-runnable")
async def handle_get_all_runnable_models(request: Request):
    return await get_all_runnable_models(request)


@router.post("/v1/chat/completions", summary="Unified OAI-compatible chat endpoint")
@limiter.limit("60/minute")
async def handle_unified_chat_completions(
    request: Request,
    user: User = Depends(get_current_user)
):
    """Handles chat completion requests, routing them to the appropriate provider or agent engine."""
    logger.info(f"Chat completion request received. User: {user.username if user else 'Anonymous'}")
    try:
        json_body = await request.json()
        pydantic_request = ChatCompletionRequest(**json_body)
    except json_lib.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Fetch configuration with potential user overrides
    proxy_config = await request.app.state.config_manager.get_config_for_session(
        user=user
    )
    requested_alias = pydantic_request.model

    logger.info(f"--- DISPATCHER STARTING for model: '{requested_alias}' ---")

    priority_chain = (
        proxy_config.get("router_settings", {})
        .get("model_group_alias", {})
        .get(requested_alias)
    )
    if not priority_chain:
        logger.error(
            f"Dispatcher Error: Model alias '{requested_alias}' not found in router_settings."
        )
        raise HTTPException(
            status_code=404,
            detail=f"Model alias '{requested_alias}' not found in router_settings.",
        )

    # --- Runtime Load Balancing ---
    # Retrieve metadata to check if we need to rotate the start of the chain
    agent_metadata = proxy_config.get("router_settings", {}).get("agent_metadata", {})
    if requested_alias in agent_metadata:
        meta = agent_metadata[requested_alias]
        main_length = meta.get("main_length", 0)

        if main_length > 1:
            # Rotate the 'main' part of the chain (first N elements)
            # based on a global round-robin index for this alias.
            rotation_index = await rotation_manager.get_rotation_index(requested_alias, main_length)

            # Use deque for efficient rotation if needed, but slicing is fine for small N
            main_part = collections.deque(priority_chain[:main_length])
            main_part.rotate(-rotation_index)

            # Reassemble chain: Rotated Main + Fallbacks
            priority_chain = list(main_part) + priority_chain[main_length:]

            logger.info(f"Load Balancing: Rotated start for '{requested_alias}' to index {rotation_index}. New Start: {priority_chain[0]}")

    primary_model_profile_name = priority_chain[0]
    primary_model_config = get_model_config_by_name(
        proxy_config, primary_model_profile_name
    )

    reasoning_mode = None
    output_format = None
    if primary_model_config:
        agent_settings = primary_model_config.get("model_params", {}).get("agent_settings", {})
        reasoning_mode = agent_settings.get("reasoning_mode")
        output_format = agent_settings.get("output_format")

        logger.info(
            f"Model '{requested_alias}' -> Found Profile '{primary_model_profile_name}'."
        )
        logger.info(
            f"Profile '{primary_model_profile_name}' -> Mode: {reasoning_mode}, Format: {output_format}"
        )
    else:
        logger.warning(
            f"Model '{requested_alias}' -> Could NOT find profile '{primary_model_profile_name}' in model_list."
        )

    is_agent = bool(reasoning_mode) or (pydantic_request.tools is not None)
    logger.info(f"--- DISPATCHER DECISION: is_agent = {is_agent} ---")

    if is_agent:
        logger.info(f"Dispatching as AGENT request for model: {requested_alias}")

        user_query = ""
        if (
            pydantic_request.messages
            and pydantic_request.messages[-1].get("role") == "user"
        ):
            user_query = pydantic_request.messages[-1].get("content", "")

        system_prompt = next(
            (
                m.get("content")
                for m in pydantic_request.messages
                if m.get("role") == "system"
            ),
            None,
        )

        initial_payload = {
            "user_query": user_query,
            "temperature": pydantic_request.temperature,
            "top_p": pydantic_request.top_p,
            "max_tokens": pydantic_request.max_tokens,
            "final_system_instruction": system_prompt,
            "client_manifests": [],
            "tools_list_text": (
                json_lib.dumps(pydantic_request.tools) if pydantic_request.tools else ""
            ),
        }

        manager = StreamingManager(
            request=request,
            session_id=f"oai-session-{uuid.uuid4()}",
            initial_payload=initial_payload,
            priority_chain=priority_chain,
            user=user,
        )

        custom_stream = manager.stream_response()

        if reasoning_mode and reasoning_mode != "native_tool_calling":
            oai_stream = oai_react_adapter(custom_stream, requested_alias, output_format=output_format)
        else:
            oai_stream = oai_stream_adapter(custom_stream, requested_alias)

        return StreamingResponse(oai_stream, media_type="text/event-stream")

    else:
        logger.info(
            f"Dispatching as STANDARD chat request for model: {requested_alias}"
        )

        if pydantic_request.stream:
            logger.info("Standard chat: Calling route_request for stream...")
            provider_map = PROVIDER_MAP_CHAT_STREAM
            result_generator = await route_request(
                request, pydantic_request, provider_map, user=user
            )
            return StreamingResponse(result_generator, media_type="text/event-stream")
        else:
            provider_map = PROVIDER_MAP_CHAT
            result_object = await route_request(request, pydantic_request, provider_map, user=user)
            return result_object


@router.post("/v1/embeddings", response_model=EmbeddingResponse)
async def handle_embeddings(req: EmbeddingRequest, request: Request):
    return await route_request(request, req, PROVIDER_MAP_EMBEDDING)


@router.post("/v1/audio/transcriptions", response_model=TranscriptionResponse)
async def handle_transcriptions(
    request: Request, file: UploadFile = File(...), model: str = Form(...)
):
    pydantic_request = TranscriptionModel(model=model)
    return await route_request(
        request, pydantic_request, PROVIDER_MAP_TRANSCRIPTION, file=file
    )


@router.post("/v1/audio/speech", response_class=StreamingResponse)
async def handle_speech_creation(req: SpeechCreationRequest, request: Request):
    return await route_request(request, req, PROVIDER_MAP_TTS)
