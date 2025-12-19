# mcp_server_manager.py
# Redis-Backed MCPServerManager with JSON File Persistence
import logging
import json
import asyncio
import os
import aiofiles
from typing import List, Dict, Any, Optional
import httpx
import uuid
import redis.asyncio as redis
from core.config.mcp_models import MCPConfig, MCPToolSettings

logger = logging.getLogger("UniversalAIGateway")

class MCPServerManager:
    """Manages MCP server states using Redis for circuit breaking and a JSON file for config persistence.

    Features:
    - **Persistence**: Stores tool settings (enabled/disabled) in `core/config/mcp_tools.json`.
    - **Hot Reload**: Watches the JSON file for changes and updates memory automatically.
    - **Discovery**: Merges discovered tools with existing config, preserving user toggles.
    """

    def __init__(
        self,
        mcp_servers_config: List[Dict[str, str]],
        redis_client: Optional[redis.Redis],
        http_client: Optional[httpx.AsyncClient] = None,
        config_path: str = "core/config/mcp_tools.json"
    ):
        self.config_map = {srv["name"]: srv for srv in mcp_servers_config}
        self.redis = redis_client
        self.http_client = http_client
        self._internal_http_client = None

        self.protocol_version = "2025-06-18"
        self.config_path = config_path

        # Internal State
        self.mcp_config = MCPConfig()
        self._last_mtime = 0.0
        self._watcher_task = None
        self._stop_event = asyncio.Event()

        # Redis Keys
        self.KEY_PREFIX_STATUS = "mcp:server:{name}:status"
        self.KEY_PREFIX_TOOLS = "mcp:server:{name}:tools"

        if not self.redis:
            logger.warning("MCPServerManager initialized WITHOUT Redis. Status tracking will be transient.")

        # Ensure directory exists
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

        # Initial Load (Sync for safety during startup)
        self._load_config_sync()

    # --- Config Management ---

    def _load_config_sync(self):
        """Loads config from disk synchronously (for init)."""
        if not os.path.exists(self.config_path):
            logger.info(f"MCP config file not found at {self.config_path}. Creating new.")
            self._save_config_sync()
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip():
                    self.mcp_config = MCPConfig()
                else:
                    data = json.loads(content)
                    self.mcp_config = MCPConfig(**data)

            self._last_mtime = os.path.getmtime(self.config_path)
            logger.info(f"Loaded MCP config from {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to load MCP config: {e}. Using empty default.")
            self.mcp_config = MCPConfig()

    def _save_config_sync(self):
        """Saves config to disk synchronously."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                f.write(self.mcp_config.model_dump_json(indent=2))
            self._last_mtime = os.path.getmtime(self.config_path)
        except Exception as e:
            logger.error(f"Failed to save MCP config: {e}")

    async def _load_config_async(self):
        """Loads config from disk asynchronously."""
        if not os.path.exists(self.config_path):
            return

        try:
            async with aiofiles.open(self.config_path, mode="r", encoding="utf-8") as f:
                content = await f.read()
                if not content.strip():
                     self.mcp_config = MCPConfig()
                else:
                    data = json.loads(content)
                    self.mcp_config = MCPConfig(**data)

            self._last_mtime = os.path.getmtime(self.config_path)
            logger.info("Reloaded MCP config from disk (Hot Reload).")
        except Exception as e:
            logger.error(f"Hot Reload failed: {e}")

    async def _save_config_async(self):
        """Saves config to disk asynchronously."""
        try:
            async with aiofiles.open(self.config_path, mode="w", encoding="utf-8") as f:
                await f.write(self.mcp_config.model_dump_json(indent=2))
            self._last_mtime = os.path.getmtime(self.config_path)
        except Exception as e:
            logger.error(f"Failed to save MCP config: {e}")

    # --- Watcher ---

    async def start_watcher(self):
        """Starts the background file watcher."""
        if self._watcher_task:
            return
        self._stop_event.clear()
        self._watcher_task = asyncio.create_task(self._file_watcher_loop())
        logger.info("MCP Config Watcher started.")

    async def stop_watcher(self):
        """Stops the background file watcher."""
        if self._watcher_task:
            self._stop_event.set()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
            self._watcher_task = None
            logger.info("MCP Config Watcher stopped.")

    async def _file_watcher_loop(self):
        """Polls file mtime to detect external changes."""
        while not self._stop_event.is_set():
            try:
                if os.path.exists(self.config_path):
                    current_mtime = os.path.getmtime(self.config_path)
                    # Use a small epsilon for float comparison, or strictly greater
                    if current_mtime > self._last_mtime:
                        logger.info("Detected change in MCP config file. Reloading...")
                        await self._load_config_async()
            except Exception as e:
                logger.error(f"Error in MCP watcher loop: {e}")

            await asyncio.sleep(2.0) # Check every 2 seconds

    # --- Lifecycle & Discovery ---

    async def _get_client(self) -> httpx.AsyncClient:
        if self.http_client:
            return self.http_client
        if not self._internal_http_client:
            self._internal_http_client = httpx.AsyncClient(timeout=10.0)
        return self._internal_http_client

    async def close(self):
        await self.stop_watcher()
        if self._internal_http_client:
            await self._internal_http_client.aclose()

    async def refresh_registry(self):
        """
        Connects to servers, discovers tools, updates Config (preserving toggles),
        saves Config to disk, and updates Redis status.
        """
        logger.info("Starting MCP Registry Refresh...")
        client = await self._get_client()

        # reload config first to ensure we have latest user edits
        await self._load_config_async()

        config_changed = False

        for name, config in self.config_map.items():
            url = config.get("url")
            if not url: continue

            try:
                tools = await self._fetch_tools_from_server(client, name, url)

                # Update Config
                if name not in self.mcp_config.tools:
                    self.mcp_config.tools[name] = {}

                server_tools_config = self.mcp_config.tools[name]

                for tool in tools:
                    # tool["name"] is "server::tool"
                    full_name = tool["name"]
                    short_name = full_name.split("::", 1)[1] if "::" in full_name else full_name

                    if short_name not in server_tools_config:
                        # New tool found!
                        server_tools_config[short_name] = MCPToolSettings(
                            enabled=True,
                            description=tool.get("description", "")
                        )
                        config_changed = True
                        logger.info(f"Added new MCP tool to config: {full_name}")

                # Update Redis
                await self._set_server_online(name, tools)

            except Exception as e:
                logger.warning(f"MCP Server '{name}' unavailable: {e}")
                await self.report_failure(name)

        if config_changed:
            await self._save_config_async()

        logger.info("MCP Registry Refresh Complete.")

    async def get_active_tools(self) -> List[Dict[str, Any]]:
        """
        Returns tools that are ONLINE in Redis AND ENABLED in Config.
        """
        if not self.redis:
            return []

        all_tools = []

        for name in self.config_map.keys():
            status = await self.redis.get(self.KEY_PREFIX_STATUS.format(name=name))
            if status == "ONLINE":
                tools_json = await self.redis.get(self.KEY_PREFIX_TOOLS.format(name=name))
                if tools_json:
                    try:
                        raw_tools = json.loads(tools_json)

                        # Filter based on self.mcp_config
                        server_conf = self.mcp_config.tools.get(name, {})

                        for tool in raw_tools:
                            full_name = tool["name"]
                            short_name = full_name.split("::", 1)[1] if "::" in full_name else full_name

                            tool_settings = server_conf.get(short_name)

                            # Default to True if not in config yet (shouldn't happen if refreshed, but safe fallback)
                            is_enabled = tool_settings.enabled if tool_settings else True

                            if is_enabled:
                                all_tools.append(tool)

                    except json.JSONDecodeError:
                        await self.report_failure(name)

        return all_tools

    # --- Redis Helpers ---

    async def report_failure(self, server_name: str, error: str = "Unknown"):
        if not self.redis: return
        pipeline = self.redis.pipeline()
        pipeline.set(self.KEY_PREFIX_STATUS.format(name=server_name), "OFFLINE")
        pipeline.delete(self.KEY_PREFIX_TOOLS.format(name=server_name))
        await pipeline.execute()

    async def _set_server_online(self, server_name: str, tools: List[Dict[str, Any]]):
        if not self.redis: return
        pipeline = self.redis.pipeline()
        pipeline.set(self.KEY_PREFIX_STATUS.format(name=server_name), "ONLINE")
        pipeline.set(self.KEY_PREFIX_TOOLS.format(name=server_name), json.dumps(tools))
        await pipeline.execute()

    async def _fetch_tools_from_server(self, client: httpx.AsyncClient, server_name: str, url: str) -> List[Dict[str, Any]]:
        headers = {
            "Content-Type": "application/json",
            "Mcp-Protocol-Version": self.protocol_version,
            "Mcp-Session-Id": f"discovery-{uuid.uuid4()}",
        }
        # Initialize
        await client.post(url, json={
            "jsonrpc": "2.0", "method": "initialize", "id": "init",
            "params": {"protocolVersion": self.protocol_version, "capabilities": {}, "clientInfo": {"name": "Gateway", "version": "1.0"}}
        }, headers=headers)

        # List Tools
        resp = await client.post(url, json={
            "jsonrpc": "2.0", "method": "tools/list", "id": "tools"
        }, headers=headers)
        resp.raise_for_status()

        fetched = resp.json().get("result", {}).get("tools", [])
        for t in fetched:
            t["name"] = f"{server_name}::{t['name']}"
        return fetched

    # Legacy Compat
    async def get_online_servers(self):
        # We need this for ToolOrchestrator
        if not self.redis: return []
        online = []
        for name, data in self.config_map.items():
            if await self.get_server_status(name) == "HEALTHY":
                online.append(data)
        return online

    async def get_server_status(self, name):
        if not self.redis: return "UNHEALTHY"
        status = await self.redis.get(self.KEY_PREFIX_STATUS.format(name=name))
        return "HEALTHY" if status == "ONLINE" else "UNHEALTHY"
