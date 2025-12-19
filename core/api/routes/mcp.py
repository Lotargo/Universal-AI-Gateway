from fastapi import APIRouter, Depends, HTTPException, Request
from core.api.auth_utils import get_current_user_strict

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])

@router.post("/refresh")
async def refresh_mcp_registry(
    request: Request,
    user: dict = Depends(get_current_user_strict)
):
    """
    Triggers a manual refresh of the MCP Server Registry.
    Discovers tools from all configured servers and updates the Redis cache.
    """
    mcp_manager = request.app.state.mcp_server_manager
    if not mcp_manager:
        raise HTTPException(status_code=503, detail="MCP Manager is not initialized (no servers configured).")

    await mcp_manager.refresh_registry()

    # Return current status
    # We can fetch tools to show what we found, or just status.
    # Let's return a simple summary.
    # Note: get_active_tools is async
    tools = await mcp_manager.get_active_tools()

    return {
        "status": "success",
        "message": "MCP Registry Refreshed",
        "total_tools": len(tools),
        "active_servers": [
            srv for srv in mcp_manager.config_map.keys()
            # We can check status if we want, but get_active_tools implicitly filters them.
            # Let's keep it simple.
        ]
    }
