import os
import json
import logging
import httpx
import random
import asyncio
import traceback
import itertools
from typing import Optional, Dict, Any, List
from core.common.clock import get_current_datetime_str
from core.providers.key_manager import ApiKeyManager
from core.tools.native.google_search import GoogleSearchTool
from core.config.default_config import CONFIG
from core.common.utils import get_model_config_by_name

logger = logging.getLogger("UniversalAIGateway")

# --- Configuration Constants ---
# Limits how many workers execute asynchronously at once.
MAX_CONCURRENT_WORKERS = 5
# How many queries the planner should generate.
DEFAULT_NUM_QUERIES = 3

# Defines roles and their model priorities.
# Uses global aliases or provider/model syntax.
SMART_SEARCH_CONFIG = {
    "planner": {
        "main": ["moonshotai/kimi-k2-instruct"],
        "fallback": ["gemma-3-27b-it"]
    },
    "worker": {
        # Models here are rotated Round-Robin for each task
        "main": ["gemma-3-27b-it","Meta-Llama-3.1-8B-Instruct", "llama-3.1-8b-instant", "allam-2-7b", "llama3.1-8b"],
        "fallback": []
    },
    "aggregator": {
        "main": ["moonshotai/kimi-k2-instruct"],
        "fallback": ["gemma-3-27b-it"]
    }
}

class SmartSearchTool:
    """
    Smart Search 2.0: Internal Swarm / Map-Reduce Architecture.

    1. Planner: Generates search queries (up to DEFAULT_NUM_QUERIES).
    2. Workers: Execute search & summarize (Queue-based, limited by MAX_CONCURRENT_WORKERS).
    3. Aggregator: Combines summaries into a final report.
    """

    def __init__(self, google_search_tool: GoogleSearchTool):
        self.google_tool = google_search_tool
        # Injected KeyManager
        self.key_manager = None
        self._initialized = False

        # Initialize worker model iterator for simple Round Robin
        self._worker_model_iterator = itertools.cycle(SMART_SEARCH_CONFIG["worker"]["main"])

    def set_key_manager(self, key_manager: ApiKeyManager):
        """Sets the global ApiKeyManager instance."""
        self.key_manager = key_manager
        # Propagate to the dependent tool
        if hasattr(self.google_tool, "set_key_manager"):
            self.google_tool.set_key_manager(key_manager)

    async def ensure_initialized(self):
        # Rely on injection, but fallback to lazy load if needed (e.g. unit tests)
        if not self.key_manager:
            logger.warning("SmartSearchTool: KeyManager not injected! Lazy loading.")
            self.key_manager = ApiKeyManager([])
            await self.key_manager.load_all_keys()
            self._initialized = True
            # Also init google tool if it wasn't
            if hasattr(self.google_tool, "key_manager") and not self.google_tool.key_manager:
                self.google_tool.key_manager = self.key_manager

        await self.google_tool.ensure_initialized()

    def _mask_key(self, text: str, api_key: str) -> str:
        if api_key and api_key in text:
            return text.replace(api_key, "***MASKED***")
        return text

    def _resolve_model_config(self, model_alias: str) -> Optional[tuple[str, str, str]]:
        """
        Resolves model configuration using the global system config.
        Returns: (provider, real_model_id, api_base_url)
        """
        # 1. Use the global helper to look up the model configuration (Chain/Profile aware)
        model_config = get_model_config_by_name(CONFIG, model_alias)
        
        # 1.1 Extended Lookup: If get_model_config_by_name fails, check MODEL_ALIASES values.
        # This handles cases where 'model_alias' is a value inside a list (e.g. 'gemini-flash-lite-latest'),
        # but not necessarily a top-level key.
        if not model_config:
            model_aliases = CONFIG.get("model_aliases", {})
            for prov, aliases_map in model_aliases.items():
                # Check keys first
                if model_alias in aliases_map:
                    real_id = aliases_map[model_alias][0]
                    model_config = {"provider": prov, "model_params": {"model": real_id}}
                    break
                # Check values (lists)
                for key, val_list in aliases_map.items():
                    if model_alias in val_list:
                        model_config = {"provider": prov, "model_params": {"model": model_alias}}
                        break
                if model_config:
                    break

        if not model_config:
            # Fallback: Try parsing 'provider/model' manually if not found in aliases
            if "/" in model_alias:
                provider, model_id = model_alias.split("/", 1)
                # Fallback map for explicit strings not in model_list
                fallback_bases = {
                    "sambanova": "https://api.sambanova.ai/v1/chat/completions",
                    "groq": "https://api.groq.com/openai/v1/chat/completions",
                    "cerebras": "https://api.cerebras.ai/v1/chat/completions",
                    "mistral": "https://api.mistral.ai/v1/chat/completions",
                    "openai": "https://api.openai.com/v1/chat/completions",
                    "cohere": "https://api.cohere.com/v2/chat",
                    "google": "https://generativelanguage.googleapis.com/v1beta"
                }
                if provider in fallback_bases:
                    base = fallback_bases[provider]
                    if provider == "google":
                         return provider, model_id, f"{base}/models/{model_id}:generateContent"
                    return provider, model_id, base
            
            logger.warning(f"SmartSearch: Could not resolve config for alias '{model_alias}'")
            return None

        # 2. Extract Details
        provider = model_config.get("provider")
        model_params = model_config.get("model_params", {})
        real_model_id = model_params.get("model", model_alias)
        api_base = model_params.get("api_base")
        
        # 3. Handle Google Specifics
        if provider == "google":
                # Google provider logic often constructs URL dynamically:
                # https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
                if not api_base:
                    api_base = "https://generativelanguage.googleapis.com/v1beta"
                
                # Check if api_base already has the suffix (unlikely for google base)
                if ":generateContent" not in api_base:
                    full_url = f"{api_base}/models/{real_model_id}:generateContent"
                else:
                    full_url = api_base
                return provider, real_model_id, full_url
        
        # 4. Handle OpenAI-Compatible (Groq, Cerebras, Sambanova, etc.)
        elif api_base:
                if provider == "cohere":
                    full_url = f"{api_base}/chat" 
                else:
                    if not api_base.endswith("/chat/completions"):
                        full_url = f"{api_base.rstrip('/')}/chat/completions"
                    else:
                        full_url = api_base
                return provider, real_model_id, full_url
        
        # 5. Config found but no api_base? (e.g. raw lookup from aliases)
        # Use hardcoded standard defaults based on provider name
        defaults = {
            "sambanova": "https://api.sambanova.ai/v1/chat/completions",
            "groq": "https://api.groq.com/openai/v1/chat/completions",
            "cerebras": "https://api.cerebras.ai/v1/chat/completions",
            "mistral": "https://api.mistral.ai/v1/chat/completions",
            "openai": "https://api.openai.com/v1/chat/completions",
            "cohere": "https://api.cohere.com/v2/chat"
        }
        if provider in defaults:
            return provider, real_model_id, defaults[provider]

        return None

    async def _call_model(self, system_prompt: str, user_content: str, role: str = "worker", specific_model: str = None, retry_count: int = 0, json_mode: bool = False) -> str:
        """
        Generic internal LLM caller.
        """
        if retry_count > 3:
            return "{}" if json_mode else "Error: Max retries reached."

        # 1. Select Model
        if specific_model:
            alias_to_try = specific_model
        else:
            role_config = SMART_SEARCH_CONFIG.get(role, SMART_SEARCH_CONFIG["worker"])
            candidates = role_config.get("main", []) + role_config.get("fallback", [])
            if not candidates:
                return "Error: No models configured for role."
            alias_to_try = random.choice(candidates)

        # 2. Resolve
        resolved = self._resolve_model_config(alias_to_try)
        if not resolved:
             if specific_model: # Retry without specific if failed
                 return await self._call_model(system_prompt, user_content, role, specific_model=None, retry_count=retry_count + 1, json_mode=json_mode)
             return await self._call_model(system_prompt, user_content, role, retry_count=retry_count + 1, json_mode=json_mode)

        provider, real_model_id, full_url = resolved

        # 3. Get Key
        api_key = await self.key_manager.get_key(provider)
        if not api_key:
             logger.warning(f"SmartSearch: No key for provider {provider}. Retrying.")
             await asyncio.sleep(0.5)
             return await self._call_model(system_prompt, user_content, role, retry_count=retry_count + 1, json_mode=json_mode)

        # 4. Execute Call
        headers = {"Content-Type": "application/json"}
        payload = {}

        try:
            if provider == "google":
                # Google format
                headers["x-goog-api-key"] = api_key
                generation_config = {"temperature": 0.3}
                if json_mode:
                    generation_config["response_mime_type"] = "application/json"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_prompt}\n\nUser Task: {user_content}"}]}],
                    "generationConfig": generation_config
                }
            elif provider == "cohere":
                # Cohere V2 format
                headers["Authorization"] = f"Bearer {api_key}"
                headers["Accept"] = "application/json"
                payload = {
                    "model": real_model_id,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    "temperature": 0.3
                }
            else:
                # OAI Compatible (Groq, Cerebras, Mistral, SambaNova, OpenAI)
                headers["Authorization"] = f"Bearer {api_key}"
                payload = {
                    "model": real_model_id,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    "temperature": 0.3,
                }
                if json_mode:
                    payload["response_format"] = {"type": "json_object"}
                    if "json" not in system_prompt.lower():
                        payload["messages"][0]["content"] += " You must return a valid JSON object."

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(full_url, json=payload, headers=headers)

            if response.status_code == 429:
                await self.key_manager.quarantine_key(provider, api_key, "Rate Limit (429)")
                await asyncio.sleep(1.0 * (retry_count + 1))
                return await self._call_model(system_prompt, user_content, role, specific_model, retry_count + 1, json_mode)

            if response.status_code != 200:
                await self.key_manager.quarantine_key(provider, api_key, f"Error {response.status_code}")
                masked_error = self._mask_key(response.text, api_key)
                logger.warning(f"Internal Model Error ({provider}/{real_model_id}): {response.status_code} - {masked_error}")
                await asyncio.sleep(0.5 * (retry_count + 1))
                return await self._call_model(system_prompt, user_content, role, specific_model, retry_count + 1, json_mode)

            await self.key_manager.release_key(provider, api_key)
            data = response.json()

            # Parse Response
            result_text = ""
            if provider == "google":
                try: result_text = data["candidates"][0]["content"]["parts"][0]["text"]
                except: result_text = "{}" if json_mode else "Error parsing Gemini response."
            elif provider == "cohere":
                 try: result_text = data["message"]["content"][0]["text"]
                 except: result_text = "{}" if json_mode else "Error parsing Cohere response."
            else:
                try: result_text = data["choices"][0]["message"]["content"]
                except: result_text = "{}" if json_mode else "Error parsing OAI response."

            return result_text

        except Exception as e:
            if api_key:
                await self.key_manager.release_key(provider, api_key)
            tb = traceback.format_exc()
            logger.error(f"Internal Call Exception: {e}\nTraceback: {tb}")
            await asyncio.sleep(0.5 * (retry_count + 1))
            return await self._call_model(system_prompt, user_content, role, specific_model, retry_count + 1, json_mode)

    async def search(self, query: str) -> str:
        """
        Executes the Swarm Search Pipeline with Queue-based Workers.
        """
        await self.ensure_initialized()
        current_date = get_current_datetime_str()

        # Step 1: Planner
        logger.info(f"SmartSearch Planner starting for: {query}")
        planner_sys = (
            f"You are a Research Planner. Current Date: {current_date}. "
            f"Break down the user query into up to {DEFAULT_NUM_QUERIES} distinct, specific Google search queries. "
            "Output JSON: {\"queries\": [\"query1\", \"query2\", ...]}"
        )
        planner_resp = await self._call_model(planner_sys, query, role="planner", json_mode=True)

        try:
            clean = planner_resp.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1]
                if clean.endswith("```"):
                    clean = clean.rsplit("\n", 1)[0]
                if clean.endswith("```json"):
                     clean = clean.replace("```json", "").replace("```", "")
            planner_data = json.loads(clean)
            search_queries = planner_data.get("queries", [])
            if not isinstance(search_queries, list):
                search_queries = [query]
        except Exception as e:
            logger.warning(f"Planner JSON Parse Error: {e}")
            search_queries = [query]

        search_queries = search_queries[:DEFAULT_NUM_QUERIES]
        logger.info(f"SmartSearch Queries ({len(search_queries)}): {search_queries}")

        # Step 2: Queue-based Workers (Concurrency Limited)
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_WORKERS)
        
        async def worker_task(sub_query):
            async with semaphore:
                # 1. Select Model (Round Robin from Iterator)
                model_to_use = next(self._worker_model_iterator)
                logger.info(f"Worker picking task '{sub_query}' with model '{model_to_use}'")

                # 2. Perform Search
                raw_res = await self.google_tool.search(sub_query, num_results=5)
                if "Error" in raw_res:
                    return json.dumps({"query": sub_query, "success": False, "error": "Search failed"})

                # 3. Summarize
                worker_sys = (
                    f"You are a Research Worker. Current Date: {current_date}. "
                    "Analyze the search results. Extract key facts and sources. "
                    "Output JSON: {\"summary\": \"...\", \"facts\": [\"fact1\", ...], \"sources\": [{\"title\": \"...\", \"url\": \"...\"}]}"
                )
                worker_resp = await self._call_model(
                    worker_sys, 
                    f"Query: {sub_query}\nResults:\n{raw_res}", 
                    role="worker", 
                    specific_model=model_to_use, 
                    json_mode=True
                )
                return worker_resp

        # Create all tasks (they will wait on semaphore)
        tasks = [worker_task(q) for q in search_queries]
        worker_results_json = await asyncio.gather(*tasks)

        # Step 3: Aggregator
        agg_context = []
        for res in worker_results_json:
            try:
                res_obj = json.loads(res)
                agg_context.append(res_obj)
            except:
                agg_context.append({"raw_text": res})

        context_str = json.dumps(agg_context, indent=2)

        aggregator_sys = (
            f"You are a Research Editor. Current Date: {current_date}. "
            "Compile the provided structured worker reports into a final answer. "
            "Verify temporal relevance. "
            "Output JSON: {\"final_answer\": \"Comprehensive text answer...\", \"meta_comment\": \"Note on data freshness or conflicts\"}"
        )
        final_resp = await self._call_model(aggregator_sys, f"User Request: {query}\n\nWorker Reports:\n{context_str}", role="aggregator", json_mode=True)

        try:
            final_obj = json.loads(final_resp)
            final_text = final_obj.get("final_answer", final_resp)
            meta = final_obj.get("meta_comment", "")
            if meta:
                return f"{final_text}\n\n[System Note: {meta}]"
            return final_text
        except:
            return f"{final_resp}\n\n[SEARCH COMPLETE] (Raw Aggregation)"

# --- Native Tool Definition ---
SMART_SEARCH_DEF = {
    "type": "function",
    "function": {
        "name": "smart_search",
        "description": "Performs an intelligent web search using a swarm of agents. Use this to find comprehensive information. It automatically plans, searches multiple sources, and compiles a final report.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."}
            },
            "required": ["query"],
        },
    },
}
