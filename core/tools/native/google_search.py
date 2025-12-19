import os
import json
import logging
import httpx
import traceback
import asyncio
from typing import Optional, Dict, Any, List
# ApiKeyManager is now injected, not instantiated
from core.providers.key_manager import ApiKeyManager
from core.common.logging_config import ApiKeyFilter

logger = logging.getLogger("UniversalAIGateway")

class GoogleSearchTool:
    """
    A native tool for performing Google Searches using the Custom Search JSON API.
    Supports key rotation via an injected ApiKeyManager instance.
    """

    def __init__(self):
        # KeyManager will be injected via set_key_manager
        self.key_manager = None
        self.provider_name = "google_search"
        self._initialized = False
        self.cx = os.getenv("GOOGLE_SEARCH_CX")

    def set_key_manager(self, key_manager: ApiKeyManager):
        """Sets the global ApiKeyManager instance."""
        self.key_manager = key_manager
        # We assume the manager is already initialized by the server

    def _mask_key(self, text: str, api_key: str) -> str:
        """
        Helper method to mask the API key in a given text.
        """
        if api_key and api_key in text:
            return text.replace(api_key, "***MASKED***")
        return text

    async def ensure_initialized(self):
        # No internal loading needed anymore, waiting for injection
        if not self.key_manager:
            logger.warning("GoogleSearchTool: KeyManager not injected! Attempting lazy load (not recommended).")
            # Fallback for tests or unexpected usage
            self.key_manager = ApiKeyManager(["google_search"])
            await self.key_manager.load_all_keys()
            self._initialized = True
        else:
             # Ensure the provider pool is initialized in the global manager if not present
             # The global manager usually does this, but for 'google_search' it might need a check
             if self.provider_name not in self.key_manager._pools:
                 # Trigger a re-scan or init if missing?
                 # Assuming global manager loaded everything.
                 pass

    async def search(self, query: str, num_results: int = 5) -> str:
        """
        Executes a Google Search.
        """
        if os.getenv("MOCK_MODE", "false").lower() == "true":
            return "[1] Mock Result\nSnippet: This is a mock search result for testing."

        if not self.cx:
            return "Error: GOOGLE_SEARCH_CX environment variable is not set. Cannot perform search."

        await self.ensure_initialized()

        api_key = await self.key_manager.get_key(self.provider_name)
        if not api_key:
            return "Error: No Google Search API keys available."

        try:
            # Safety: Ensure this specific key is registered for masking immediately before use
            ApiKeyFilter.add_sensitive_keys([api_key])

            url = "https://www.googleapis.com/customsearch/v1"
            # Use URL parameter 'key' for auth (required by Custom Search API)
            # The key is masked in logs by the ApiKeyFilter exact matching
            headers = {}
            params = {
                "key": api_key,
                "cx": self.cx,
                "q": query,
                "num": num_results
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params, headers=headers)

            if response.status_code == 429:
                await self.key_manager.quarantine_key(self.provider_name, api_key, "Rate Limit (429)")
                # Retry once with a new key with small delay
                await asyncio.sleep(0.5)
                return await self.search(query, num_results)

            if response.status_code != 200:
                await self.key_manager.quarantine_key(self.provider_name, api_key, f"Error {response.status_code}")
                # Mask key in logs/output
                masked_error = self._mask_key(response.text, api_key)
                return f"Google Search Error: {response.status_code} - {masked_error}"

            # Success
            await self.key_manager.release_key(self.provider_name, api_key)
            data = response.json()

            items = data.get("items", [])
            if not items:
                return "No results found."

            results_text = []
            for i, item in enumerate(items, 1):
                title = item.get("title", "No Title")
                link = item.get("link", "No Link")
                snippet = item.get("snippet", "No Description")
                results_text.append(f"[{i}] {title}\nURL: {link}\nSnippet: {snippet}\n")

            return "\n".join(results_text)

        except Exception as e:
            # Release key if it wasn't a logic error
            if api_key:
                await self.key_manager.release_key(self.provider_name, api_key)
            error_msg = str(e)
            masked_error = self._mask_key(error_msg, api_key)
            # Log full traceback for debugging empty exceptions
            tb = traceback.format_exc()
            logger.error(f"Google Search Exception: {masked_error}\nTraceback: {tb}")
            return f"Error performing search: {masked_error}"

# --- Native Tool Definition ---
GOOGLE_SEARCH_DEF = {
    "type": "function",
    "function": {
        "name": "google_search",
        "description": "Searches Google for information. Use this to verify facts or find data.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."}
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}
