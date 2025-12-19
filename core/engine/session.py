import asyncio
import logging
import uuid
from typing import Optional
import redis.asyncio as redis

logger = logging.getLogger("UniversalAIGateway")

OWNER_LEASE_TTL_MS = 60_000
TASK_HASH_TTL_S = 1800

def _owner_key(task_id: str) -> str:
    return f"owner:{task_id}"

def _task_key(task_id: str) -> str:
    return f"task:{task_id}"

class SessionStateStore:
    def __init__(self, redis_client: redis.Redis, session_id: str):
        self.redis_client = redis_client
        self.session_id = session_id
        self.worker_id = f"worker-{uuid.uuid4().hex}"
        self.generation_id = str(uuid.uuid4())

    async def acquire_lease(self) -> bool:
        if not self.redis_client:
            return True
        lease_acquired = await self.redis_client.set(
            _owner_key(self.session_id), self.worker_id, px=OWNER_LEASE_TTL_MS, nx=True
        )
        if lease_acquired:
            task_details = {
                "status": "running",
                "owner": self.worker_id,
                "generation_id": self.generation_id,
                "last_seq": 0,
                "created_at": asyncio.get_event_loop().time(),
            }
            await self.redis_client.hset(
                _task_key(self.session_id), mapping=task_details
            )
            await self.redis_client.expire(_task_key(self.session_id), TASK_HASH_TTL_S)
            logger.info(f"Acquired lease for session {self.session_id}")
            return True
        logger.warning(f"Could not acquire lease for session {self.session_id}")
        return False

    async def release_lease(self):
        if not self.redis_client:
            return
        script = """if redis.call("get", KEYS[1]) == ARGV[1] then return redis.call("del", KEYS[1]) else return 0 end"""
        result = await self.redis_client.eval(
            script, 1, _owner_key(self.session_id), self.worker_id
        )
        await self.redis_client.hset(_task_key(self.session_id), "status", "done")
        logger.info(f"Released lease for session {self.session_id}, result: {result}")

    async def is_cancelled(self) -> bool:
        if not self.redis_client:
            return False
        status = await self.redis_client.hget(_task_key(self.session_id), "status")
        return status == "cancelled"

    @staticmethod
    async def cancel_session(redis_client: redis.Redis, session_id: str) -> bool:
        task_key = _task_key(session_id)
        if await redis_client.exists(task_key):
            await redis_client.hset(task_key, "status", "cancelled")
            logger.info(f"Cancelled session {session_id}")
            return True
        logger.warning(f"Session {session_id} not found for cancellation")
        return False

    async def get_draft(self) -> str:
        if not self.redis_client:
            return ""
        draft = await self.redis_client.hget(_task_key(self.session_id), "draft")
        return draft if draft else ""

    async def save_draft(self, content: str):
        if not self.redis_client:
            return
        await self.redis_client.hset(_task_key(self.session_id), "draft", content)

    async def get_phase(self) -> int:
        if not self.redis_client:
            return 0
        phase = await self.redis_client.hget(_task_key(self.session_id), "phase")
        try:
            return int(phase) if phase else 0
        except:
            return 0

    async def save_phase(self, phase: int):
        if not self.redis_client:
            return
        await self.redis_client.hset(_task_key(self.session_id), "phase", str(phase))
