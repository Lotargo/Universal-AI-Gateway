import json
import logging
import asyncio
from typing import AsyncGenerator, Dict, Any, List, Optional

from core.mcp.client import MCPManager
from core.tools.native_tools import NATIVE_TOOL_FUNCTIONS, GATEKEEPER_TOOLS

logger = logging.getLogger("UniversalAIGateway")

class ToolOrchestrator:
    def __init__(self, app_state, session_id: str):
        self.app_state = app_state
        self.session_id = session_id
        self.mcp_manager: Optional[MCPManager] = None
        self.tools_initialized = False
        self.tools_list_json = "[]"

    async def initialize_tools(
        self, allowed_server_names: Optional[List[str]] = None, pre_provided_tools: str = ""
    ) -> AsyncGenerator[Dict[str, Any], None]:

        if self.tools_initialized:
            return

        # OAI path (tools already provided)
        if pre_provided_tools and pre_provided_tools != "[]":
            logger.info("Tools provided via OAI request.")
            try:
                server_configs = self.app_state.config.get("mcp_servers", [])
                if not self.mcp_manager:
                    self.mcp_manager = MCPManager(
                        online_server_configs=server_configs,
                        http_client=self.app_state.http_client,
                        user_session_id=self.session_id,
                    )
                # Optimization: Do we REALLY need to init sessions if tools are provided?
                # Yes, to call them. But maybe lazy?
                # For now, keep existing logic.
                await self.mcp_manager.initialize_all_sessions()
                self.tools_initialized = True
                yield {"type": "info", "payload": {"message": "Sessions initialized for OAI-provided tools."}}
            except Exception as e:
                logger.warning(f"Failed to initialize tools in OAI path: {e}")
                self.tools_initialized = True
                # Suppress user-facing warning
                logger.debug(f"Suppressed OAI init warning: {e}")
                # yield {"type": "warning", "payload": {"message": f"Tool initialization failed (OAI path): {e}"}}

            self.tools_list_json = pre_provided_tools
            return

        # Standard path
        yield {"type": "info", "payload": {"message": "Discovering available tools..."}}

        # --- 1. MCP Tools Discovery ---
        tools_list = []

        health_checker = getattr(self.app_state, "mcp_server_manager", None)
        if health_checker:
             try:
                # Passive Circuit Breaker (Redis Backed): Get servers considered HEALTHY
                all_online_servers = await health_checker.get_online_servers()

                if all_online_servers:
                    final_servers = all_online_servers
                    if allowed_server_names:
                        server_set = set(allowed_server_names)
                        final_servers = [s for s in all_online_servers if s["name"] in server_set]
                        if not final_servers:
                             logger.warning(f"Required servers offline: {allowed_server_names}")

                    if final_servers:
                        if not self.mcp_manager:
                            self.mcp_manager = MCPManager(
                                online_server_configs=final_servers,
                                http_client=self.app_state.http_client,
                                user_session_id=self.session_id,
                            )
                            # Inject the Circuit Breaker manager to report success/failure
                            self.mcp_manager.set_server_manager(health_checker)

                        # This now hits Redis (fast) via MCPManager -> MCPServerManager
                        mcp_tools = await self.mcp_manager.initialize_all_sessions()
                        tools_list.extend(mcp_tools)
                        logger.info(f"MCP Tools discovered for session {self.session_id}: {len(mcp_tools)}")

             except Exception as e:
                logger.error(f"MCP Tool init failed: {e}", exc_info=True)
        else:
            logger.debug("MCPServerManager not configured - skipping MCP tool discovery.")

        # --- 2. Native Tools Discovery ---
        # Add enabled native tools to the list so ReAct agents see them in {tools_list_text}
        toggles = self.app_state.config.get("native_tool_toggles", {})
        native_count = 0
        for tool_def in GATEKEEPER_TOOLS:
            fn_name = tool_def.get("function", {}).get("name")
            if not fn_name:
                continue

            # Check toggle
            if toggles.get(fn_name, True):
                tools_list.append(tool_def)
                native_count += 1

        if native_count > 0:
            logger.info(f"Native Tools added: {native_count}")

        self.tools_list_json = json.dumps(tools_list, indent=2, ensure_ascii=False)
        yield {"type": "info", "payload": {"message": f"Found {len(tools_list)} tools."}}
        self.tools_initialized = True


    async def call_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        # Native Check
        if tool_name in NATIVE_TOOL_FUNCTIONS:
             toggles = self.app_state.config.get("native_tool_toggles", {})
             if not toggles.get(tool_name, True):
                 return {"error": f"Tool {tool_name} is disabled by configuration."}

             try:
                 return await NATIVE_TOOL_FUNCTIONS[tool_name](**kwargs)
             except Exception as e:
                 return {"error": str(e)}

        if not self.mcp_manager:
            return {"error": "MCPManager not initialized."}

        # Fuzzy logic (copied from manager.py)
        full_tool_name = tool_name
        if "::" in tool_name:
            server_part, tool_part = tool_name.split("::", 1)
            # Use .servers instead of .session_map
            available_servers = list(self.mcp_manager.servers.keys())
            if server_part not in available_servers:
                if server_part.replace("servers", "server") in available_servers:
                     full_tool_name = f"{server_part.replace('servers', 'server')}::{tool_part}"
                elif server_part.replace("server", "servers") in available_servers:
                     full_tool_name = f"{server_part.replace('server', 'servers')}::{tool_part}"

        if "::" not in full_tool_name:
            # Default server fallback
            if mcp_servers := self.app_state.config.get("mcp_servers", []):
                # Try to use the first configured server as default
                default_server = mcp_servers[0]["name"]
                full_tool_name = f"{default_server}::{tool_name}"
            else:
                return {"error": "No MCP servers configured."}

        try:
            return await self.mcp_manager.call_tool(full_tool_name, arguments=kwargs)
        except Exception as e:
            return {"error": str(e)}

    async def get_server_status_text(self) -> str:
        # Passive Check (Circuit Breaker) - reads directly from Redis
        health_checker = getattr(self.app_state, "mcp_server_manager", None)
        if not health_checker:
            return "."

        lines = ["**CURRENT LIVE MCP SERVER STATUS:**"]
        has_any = False

        # Use config_map to get known names, as get_server_status requires a name
        for name in health_checker.config_map.keys():
            # AWAIT the status check
            status = await health_checker.get_server_status(name)

            # SILENT MODE: Only report ONLINE servers.
            if status == "HEALTHY": # Corresponds to ONLINE in Redis
                lines.append(f"- {name}: ONLINE")
                has_any = True
            # else: skip

        if not has_any:
            # If no servers are online, return "." (empty) so no header is injected in manager.py
            return "."

        return "\n".join(lines)
