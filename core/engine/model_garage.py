import asyncio
import json
import logging
import httpx
import random
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("UniversalAIGateway")

GARAGE_FILE = Path("models_garage.json")


class ModelGarage:
    def __init__(self, key_manager):
        self.key_manager = key_manager
        self.garage_data: Dict[str, List[str]] = {}
        self._load_garage_from_disk()

    def _load_garage_from_disk(self):
        if GARAGE_FILE.exists():
            try:
                with open(GARAGE_FILE, "r", encoding="utf-8") as f:
                    self.garage_data = json.load(f)
                logger.info(
                    f"Loaded {sum(len(v) for v in self.garage_data.values())} verified models from disk."
                )
            except Exception as e:
                logger.error(f"Failed to load garage from disk: {e}")

    async def update_garage(self):
        """Discovers and verifies available models from providers.

        Updates the local garage file with the list of verified models.
        """
        logger.info("Starting Model Garage update...")

        providers = ["google", "mistral", "cerebras", "groq", "cohere"]

        discovered_models = {}

        async with httpx.AsyncClient(timeout=30.0) as client:
            for provider in providers:
                key = self.key_manager.get_verification_key(provider)
                if not key:
                    logger.warning(
                        f"Skipping provider '{provider}': No verification key available."
                    )
                    continue

                logger.info(f"[{provider}] Fetching model list using key: {key[:4]}...")
                try:
                    models = await self._fetch_model_list(client, provider, key)
                    logger.info(
                        f"[{provider}] Found {len(models)} models. Starting verification..."
                    )

                    verified_models = []
                    # Limit concurrent checks to avoid rate limits
                    sem = asyncio.Semaphore(5)

                    async def verify_worker(model_name):
                        async with sem:
                            if await self._verify_model(
                                client, provider, model_name, key
                            ):
                                verified_models.append(model_name)

                    await asyncio.gather(*[verify_worker(m) for m in models])

                    discovered_models[provider] = sorted(verified_models)
                    logger.info(
                        f"[{provider}] Verified {len(verified_models)}/{len(models)} models."
                    )

                except Exception as e:
                    logger.error(f"[{provider}] Error updating garage: {e}")

        self.garage_data = discovered_models
        self._save_garage(discovered_models)
        logger.info("Model Garage update completed.")

    def get_model_for_tier(self, tier: str, config: Dict[str, Any]) -> Optional[str]:
        """Selects a model profile for a given tier from available verified models.

        Args:
            tier: The tier name (e.g., "lite", "pro").
            config: The main configuration dictionary.

        Returns:
            The name of the selected model profile, or None if no suitable model is found.
        """
        candidates = [m for m in config.get("model_list", []) if m.get("tier") == tier]

        if not candidates:
            logger.warning(f"No model profiles found for tier '{tier}' in config.")
            return None

        # Shuffle to distribute load
        random.shuffle(candidates)

        for candidate in candidates:
            provider = candidate.get("provider")
            raw_model = candidate.get("model_params", {}).get("model")

            # Check if this specific raw model is verified in our garage
            verified_list = self.garage_data.get(provider, [])
            if raw_model in verified_list:
                return candidate["model_name"]

        logger.warning(
            f"No verified models found for tier '{tier}'. Falling back to first configured candidate."
        )
        # Fallback: if no verified models found (maybe garage is empty/outdated), return the first candidate
        # to avoid complete failure.
        return candidates[0]["model_name"] if candidates else None

    async def _fetch_model_list(
        self, client: httpx.AsyncClient, provider: str, key: str
    ) -> List[str]:
        if provider == "google":
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            return [
                m["name"].replace("models/", "")
                for m in data.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]

        elif provider == "mistral":
            url = "https://api.mistral.ai/v1/models"
            resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]

        elif provider == "cerebras":
            url = "https://api.cerebras.ai/v1/models"
            resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]

        elif provider == "groq":
            url = "https://api.groq.com/openai/v1/models"
            resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]

        elif provider == "cohere":
            url = "https://api.cohere.com/v1/models"
            resp = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            # Cohere returns list of objects, filter for chat capability
            return [
                m["name"]
                for m in data.get("models", [])
                if "chat" in m.get("endpoints", [])
            ]

        return []

    async def _verify_model(
        self, client: httpx.AsyncClient, provider: str, model_name: str, key: str
    ) -> bool:
        retries = 3
        for attempt in range(retries):
            try:
                if provider == "google":
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"
                    payload = {
                        "contents": [{"parts": [{"text": "Hi"}]}],
                        "generationConfig": {"maxOutputTokens": 1},
                    }
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    return True

                elif provider in ["mistral", "cerebras", "groq"]:
                    if provider == "mistral":
                        base = "https://api.mistral.ai/v1/chat/completions"
                    elif provider == "cerebras":
                        base = "https://api.cerebras.ai/v1/chat/completions"
                    elif provider == "groq":
                        base = "https://api.groq.com/openai/v1/chat/completions"

                    payload = {
                        "model": model_name,
                        "messages": [{"role": "user", "content": "Hi"}],
                        "max_tokens": 1,
                    }
                    resp = await client.post(
                        base, json=payload, headers={"Authorization": f"Bearer {key}"}
                    )
                    resp.raise_for_status()
                    return True

                elif provider == "cohere":
                    url = "https://api.cohere.com/v1/chat"
                    payload = {"model": model_name, "message": "Hi", "max_tokens": 1}
                    resp = await client.post(
                        url,
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Accept": "application/json",
                        },
                    )
                    resp.raise_for_status()
                    return True

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning(
                        f"[{provider}] Rate limit hit for '{model_name}' (Attempt {attempt+1}/{retries}). Sleeping..."
                    )
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                logger.warning(
                    f"[{provider}] Model '{model_name}' verification failed: {e}"
                )
                return False
            except Exception as e:
                logger.warning(
                    f"[{provider}] Model '{model_name}' verification failed: {e}"
                )
                return False
        return False

    def _save_garage(self, data: Dict[str, List[str]]):
        try:
            with open(GARAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Garage saved to {GARAGE_FILE}")
        except Exception as e:
            logger.error(f"Failed to save garage file: {e}")
