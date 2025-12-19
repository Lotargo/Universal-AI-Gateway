import logging
import json as json_lib
import asyncio
import os

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel

from core.api.auth_utils import get_current_user_strict
from core.engine.model_garage import ModelGarage
from core.engine.pattern_loader import get_available_react_patterns

logger = logging.getLogger("UniversalAIGateway")

router = APIRouter(dependencies=[Depends(get_current_user_strict)])


class ConfigUpdateRequest(BaseModel):
    content: str


@router.get("/admin/config", response_model=ConfigUpdateRequest)
async def get_admin_config(request: Request):
    """Returns the current in-memory configuration as JSON."""
    try:
        content = json_lib.dumps(request.app.state.config, indent=2, ensure_ascii=False)
        return ConfigUpdateRequest(content=content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to serialize config: {e}")


@router.post("/admin/config")
async def update_admin_config(req: ConfigUpdateRequest, request: Request):
    """Updates the in-memory configuration from JSON (Non-persistent)."""
    try:
        new_config_data = json_lib.loads(req.content)
        request.app.state.config_manager.update_global_config(new_config_data)
        # Update the reference in app.state.config
        request.app.state.config = request.app.state.config_manager.get_active_config()

        logger.info(
            "Configuration updated and hot-reloaded in app state (Memory Only)."
        )
        return {"status": "success", "message": "Configuration updated in memory."}
    except json_lib.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON format: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update config: {e}")


@router.post("/admin/garage/verify")
async def verify_garage_models(request: Request, background_tasks: BackgroundTasks):
    """
    Triggers a background task to fetch and verify available models from providers.
    """
    garage = ModelGarage(request.app.state.key_manager)
    background_tasks.add_task(garage.update_garage)
    return {"status": "success", "message": "Model verification started in background."}




@router.get("/admin/react_patterns")
async def get_react_patterns_endpoint():
    return get_available_react_patterns()


@router.get("/admin/provider_models")
async def get_provider_models(request: Request):
    config = request.app.state.config
    provider_models = config.get("provider_model_lists", {})
    return provider_models




@router.post("/admin/restart")
async def restart_server():
    logger.info("Restart endpoint called. Forcing server exit.")

    async def delayed_exit():
        await asyncio.sleep(1)
        os._exit(0)

    asyncio.create_task(delayed_exit())
    return {"message": "Server is restarting..."}
