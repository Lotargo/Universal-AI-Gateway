import asyncio
import time
import logging
import random
import os
import glob
from typing import List, Dict, Any, Optional
from core.common.logging_config import ApiKeyFilter

logger = logging.getLogger("UniversalAIGateway")

# --- Main Switch ---
ENABLE_QUARANTINE = True

# --- Other Settings ---
GET_KEY_TIMEOUT_SECONDS = 15  # Timeout waiting for key in queue
QUARANTINE_DURATION_SECONDS = 300


class ProviderUnavailableError(Exception):
    pass


class GetKeyTimeoutError(Exception):
    pass


class ApiKeyManager:
    """Manages API keys for various providers, handling rotation, quarantine, and retirement."""

    def __init__(self, providers: List[str]):
        """Initializes the ApiKeyManager.

        Args:
            providers: A list of initial provider names to manage keys for.
        """
        self._pools: Dict[str, Dict[str, Any]] = {
            provider: {
                "available": asyncio.Queue(),
                "quarantined": {},
                "retired": {},
                "total_keys": 0,
                "free_keys": [],
                "paid_keys": [],
            }
            for provider in providers
        }
        # Metadata to store key type (free/paid)
        self.key_metadata: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._checker_task: Optional[asyncio.Task] = None

    def _get_key_identifier(self, key: str) -> str:
        return f"key_{key[:4]}...{key[-4:]}"

    def _load_keys_from_file(self, file_path: str) -> List[str]:
        if not os.path.exists(file_path):
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return [
                    line.strip()
                    for line in f
                    if line.strip() and not line.startswith("#")
                ]
        except Exception as e:
            logger.error(f"Error reading key file {file_path}: {e}")
            return []

    def _init_provider_pool(self, provider: str):
        """Initializes the pool structure for a new provider if it doesn't exist."""
        if provider not in self._pools:
            self._pools[provider] = {
                "available": asyncio.Queue(),
                "quarantined": {},
                "retired": {},
                "total_keys": 0,
                "free_keys": [],
                "paid_keys": [],
            }

    async def load_all_keys(self):
        async with self._lock:
            # 1. Discovery Phase: Scan keys_pool/ directory for all providers
            discovered_providers = set()
            keys_pool_dir = "keys_pool"
            if os.path.exists(keys_pool_dir):
                # Match pattern: keys_pool/*_free.env and keys_pool/*_paid.env
                for file_path in glob.glob(os.path.join(keys_pool_dir, "*_*.env")):
                    filename = os.path.basename(file_path)
                    # Expected format: {provider}_free.env or {provider}_paid.env
                    if filename.endswith("_free.env"):
                        provider_name = filename[:-9] # Remove _free.env
                        discovered_providers.add(provider_name)
                    elif filename.endswith("_paid.env"):
                        provider_name = filename[:-9] # Remove _paid.env
                        discovered_providers.add(provider_name)

            # Initialize pools for any newly discovered providers
            for provider in discovered_providers:
                self._init_provider_pool(provider)

            # 2. Loading Phase: Load keys for all known providers (initial + discovered)
            for provider in self._pools.keys():
                if provider.startswith("local"):
                    continue

                # Map complex providers to base file names if necessary
                # (Currently google-embedding etc share google keys, this logic is preserved)
                key_source_provider = (
                    "google"
                    if provider in ["google-embedding", "google-stt", "google-tts"]
                    else provider
                )

                # Load Free and Paid keys
                free_keys = self._load_keys_from_file(
                    f"keys_pool/{key_source_provider}_free.env"
                )
                paid_keys = self._load_keys_from_file(
                    f"keys_pool/{key_source_provider}_paid.env"
                )

                # Legacy fallback: try original .env file if specific files are empty
                if not free_keys and not paid_keys:
                    legacy_keys = self._load_keys_from_file(
                        f"keys_pool/keys_pool_{key_source_provider}.env"
                    )
                    # Treat legacy keys as "paid" by default or just mixed?
                    # Let's assume they are 'free' to be safe, or just add them.
                    free_keys.extend(legacy_keys)

                # Update pools lists
                self._pools[provider]["free_keys"] = free_keys
                self._pools[provider]["paid_keys"] = paid_keys

                # Update metadata
                for k in free_keys:
                    self.key_metadata[k] = "free"
                for k in paid_keys:
                    self.key_metadata[k] = "paid"

                # Fill Queue (Clear first)
                while not self._pools[provider]["available"].empty():
                    self._pools[provider]["available"].get_nowait()

                all_keys = free_keys + paid_keys
                # Shuffle to distribute load? Or Keep strict order?
                # Random shuffle is better to avoid hot-spotting one key.
                random.shuffle(all_keys)

                for key in all_keys:
                    await self._pools[provider]["available"].put(key)

                self._pools[provider]["total_keys"] = len(all_keys)

                # Register keys with the logging filter for safety
                ApiKeyFilter.add_sensitive_keys(all_keys)

                # Only log if keys were found to reduce noise, or log 0 if expected
                logger.info(
                    f"-> [{provider.upper()}] Loaded {len(all_keys)} keys ({len(free_keys)} Free, {len(paid_keys)} Paid)."
                )

    async def get_key(self, provider: str) -> Optional[str]:
        if provider.startswith("local"):
            return "local-key-placeholder"

        pool = self._pools.get(provider)
        if not pool:
            # Try to lazy-load if it's a new provider not yet initialized (edge case)
            # But normally load_all_keys handles this.
            return None

        try:
            key = await asyncio.wait_for(
                pool["available"].get(), timeout=GET_KEY_TIMEOUT_SECONDS
            )
            if key in pool["retired"]:
                logger.warning(
                    f"[{provider.upper()}] Retrieved retired key {self._get_key_identifier(key)}. Retrying."
                )
                return await self.get_key(provider)
            return key
        except asyncio.TimeoutError:
            logger.error(f"[{provider.upper()}] Key pool exhausted/timeout.")
            raise GetKeyTimeoutError(f"Timeout waiting for key from {provider}")

    async def release_key(self, provider: str, key: str):
        if provider.startswith("local"):
            return
        pool = self._pools.get(provider)
        if not pool:
            return
        if key in pool["retired"] or key in pool["quarantined"]:
            return
        await pool["available"].put(key)

    async def quarantine_key(
        self,
        provider: str,
        key: str,
        reason: str,
        duration: int = QUARANTINE_DURATION_SECONDS,
    ):
        if provider.startswith("local"):
            return
        if not ENABLE_QUARANTINE:
            logger.warning(
                f"[{provider.upper()}] Quarantine disabled. Key {self._get_key_identifier(key)} returned. Reason: {reason}"
            )
            await self.release_key(provider, key)
            return

        async with self._lock:
            pool = self._pools.get(provider)
            if not pool:
                return
            end_time = time.time() + duration
            pool["quarantined"][key] = {"reason": reason, "end_time": end_time}
            logger.warning(
                f"[{provider.upper()}] Key {self._get_key_identifier(key)} QUARANTINED for {duration}s. Reason: {reason}"
            )

    async def retire_key(self, provider: str, key: str, reason: str):
        if provider.startswith("local"):
            return
        async with self._lock:
            pool = self._pools.get(provider)
            if not pool or key in pool["retired"]:
                return
            if key in pool["quarantined"]:
                del pool["quarantined"][key]
            pool["retired"][key] = reason
            self._pools[provider]["total_keys"] = max(
                0, self._pools[provider]["total_keys"] - 1
            )
            logger.critical(
                f"[{provider.upper()}] Key {self._get_key_identifier(key)} RETIRED. Reason: {reason}"
            )

    async def _check_quarantine(self):
        while True:
            await asyncio.sleep(10)
            try:
                current_time = time.time()
                keys_to_release_by_provider = {}
                async with self._lock:
                    for provider, pool in self._pools.items():
                        if provider.startswith("local") or not pool.get("quarantined"):
                            continue
                        keys_to_release = [
                            key
                            for key, data in pool["quarantined"].items()
                            if current_time >= data["end_time"]
                        ]
                        if keys_to_release:
                            keys_to_release_by_provider[provider] = keys_to_release
                            for key in keys_to_release:
                                del pool["quarantined"][key]
                for provider, keys in keys_to_release_by_provider.items():
                    for key in keys:
                        await self._pools[provider]["available"].put(key)
                        logger.info(
                            f"[{provider.upper()}] Key {self._get_key_identifier(key)} released from quarantine."
                        )
            except Exception as e:
                logger.error(f"Critical error in _check_quarantine: {e}", exc_info=True)

    async def start_background_tasks(self):
        if ENABLE_QUARANTINE and (not self._checker_task or self._checker_task.done()):
            self._checker_task = asyncio.create_task(self._check_quarantine())

    async def stop_background_tasks(self):
        if self._checker_task and not self._checker_task.done():
            self._checker_task.cancel()
            try:
                await self._checker_task
            except asyncio.CancelledError:
                pass

    async def get_full_status(self):
        async with self._lock:
            status = {}
            for provider, data in self._pools.items():
                status[provider] = {
                    "available": data["available"].qsize(),
                    "quarantined": len(data["quarantined"]),
                    "retired": len(data["retired"]),
                    "total_keys": data["total_keys"],
                }
            return status

    def get_verification_key(self, provider: str) -> Optional[str]:
        """
        Returns a key suitable for model verification.
        Prefers a random 'free' key. If none, returns a 'paid' key.
        Does NOT remove the key from the pool.
        """
        pool = self._pools.get(provider)
        if not pool:
            return None

        if pool["free_keys"]:
            return random.choice(pool["free_keys"])
        if pool["paid_keys"]:
            return random.choice(pool["paid_keys"])
        return None
