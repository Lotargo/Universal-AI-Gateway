# mcp_manager.py 
import asyncio
import httpx
import logging
import os
from typing import List, Dict, Any, Optional
import uuid

logger = logging.getLogger("UniversalAIGateway")


class MCPError(Exception):
    pass


class MCPManager:
    """Manages sessions and tool calls for a SINGLE user request.

    Uses cached tool definitions from MCPServerManager (Redis).
    """

    def __init__(
        self,
        online_server_configs: List[Dict[str, str]],
        http_client: httpx.AsyncClient,
        user_session_id: str,
        server_manager=None
    ):
        self.servers = {
            server["name"]: server["url"] for server in online_server_configs
        }
        self.http_client = http_client
        self.user_session_id = user_session_id
        # Unique MCP-Session-Id for this specific session
        self.mcp_session_id = f"mcp-session-{self.user_session_id}-{uuid.uuid4().hex}"
        self.protocol_version = "2025-06-18"
        self.sessions_initialized = False
        self.server_manager = server_manager # Injected MCPServerManager

        # Default timeouts for MCP calls
        self.connect_timeout = 10.0
        self.read_timeout = 60.0

    def set_server_manager(self, manager):
        """Injects the MCPServerManager (if not passed in init)."""
        self.server_manager = manager

    async def initialize_all_sessions(self) -> List[Dict[str, Any]]:
        """
        Retrieves tools from the global Redis cache via MCPServerManager.
        NO network calls are made here.
        """
        if not self.server_manager:
            logger.warning("MCPManager initialized without MCPServerManager! Cannot fetch tools.")
            return []

        all_tools = await self.server_manager.get_active_tools()
        self.sessions_initialized = True
        logger.debug(
            f"MCP Tools Loaded from Cache ({self.mcp_session_id}). Count: {len(all_tools)}"
        )
        return all_tools

    async def call_tool(
        self, full_tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calls a tool on the appropriate MCP server."""
        if not self.sessions_initialized:
            raise MCPError("Sessions were not initialized before tool call.")

        try:
            server_name, tool_name = full_tool_name.split("::", 1)
        except ValueError:
            raise MCPError(f"Invalid tool name format: {full_tool_name}")

        # Check if server is configured
        if server_name not in self.servers:
             # It might be in the cache but not in our local config map (unlikely),
             # or we just need the URL.
             # We can try to get URL from server_manager if needed, but let's assume passed configs are correct.
             # Actually, if a server goes offline, get_active_tools won't return its tools.
             # But if the agent hallucinated a tool from a dead server, or used an old tool name...
             raise MCPError(f"MCP server '{server_name}' is not configured.")

        url = self.servers[server_name]

        # headers = {
        #     "Content-Type": "application/json",
        #     "Mcp-Session-Id": self.mcp_session_id,
        #     "X-Mcp-Sync": "true",
        # }
        # Note: Some servers require initialization before 'tools/call'.
        # However, HTTP MCP is often stateless.
        # If we need to Initialize JIT, we could do it here.
        # For now, we assume the server accepts calls with a session ID.

        headers = {
            "Content-Type": "application/json",
            "Mcp-Session-Id": self.mcp_session_id,
            "X-Mcp-Sync": "true",
        }

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": f"call-{uuid.uuid4()}",
            "params": {"name": tool_name, "arguments": arguments},
        }

        logger.info(f"[TOOL-CALL] --> {full_tool_name}")
        try:
            response = await self.http_client.post(
                url,
                json=payload,
                headers=headers,
                timeout=httpx.Timeout(self.connect_timeout, read=self.read_timeout)
            )
            response.raise_for_status()

            # Check for empty response body
            if not response.text.strip():
                logger.warning(
                    f"Tool '{full_tool_name}' returned an empty response (status: {response.status_code})."
                )
                return {"error": f"Tool '{full_tool_name}' returned an empty response."}

            response_json = response.json()

            # Async response logic
            if response.status_code == 202:
                logger.warning(
                    "Server responded 202 Accepted, but async processing is not yet implemented."
                )
                return {
                    "result": {
                        "output": "Request accepted by server, but result not yet received."
                    }
                }

            logger.info(f"[TOOL-RESULT] <-- {full_tool_name}")

            if "error" in response_json:
                return {"error": response_json["error"]}

            # Simplify result for agent
            result_content = response_json.get("result", {}).get("content", [])
            if result_content and isinstance(result_content, list):
                text_parts = [
                    item.get("text", "")
                    for item in result_content
                    if item.get("type") == "text"
                ]
                return {"result": {"output": "\n".join(text_parts)}}

            return {"result": response_json.get("result", {})}

        except httpx.RequestError as e:
            logger.error(f"Network error calling tool '{full_tool_name}': {e}")
            # FAIL FAST: Report failure to manager to mark offline
            if self.server_manager:
                await self.server_manager.report_failure(server_name, str(e))

            raise MCPError(f"MCP Server '{server_name}' is unavailable (Network Error). It has been marked OFFLINE.")

        except Exception as e:
            logger.error(f"Unexpected error calling tool '{full_tool_name}': {e}", exc_info=True)
            if isinstance(e, httpx.HTTPStatusError):
                # 500 error from server -> Server is alive but bugged.
                # Do we mark offline? Usually not, unless we want to avoid bugged servers.
                # User asked for "availability check". 500 means available.
                pass
            raise e
