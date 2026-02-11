from __future__ import annotations

import json
from typing import Optional

import redis.asyncio as redis

from voice_agent.core.types import CallState


class RedisStateStore:
    """
    Stores per-call state in Redis as JSON.

    Keys:
      voice_agent:call:<call_id> -> JSON-serialized CommunicationState
    """

    def __init__(
        self,
        client: redis.Redis,
        *,
        key_prefix: str = "voice_agent:call:",
        ttl_seconds: int = 60 * 60,  # 1 hour
    ) -> None:
        self._client = client
        self._prefix = key_prefix
        self._ttl = ttl_seconds

    def _key(self, call_id: str) -> str:
        return f"{self._prefix}{call_id}"

    async def get(self, call_id: str) -> Optional[CallState]:
        raw = await self._client.get(self._key(call_id))
        if raw is None:
            return None
        # If decode_responses=True, raw is str; else bytes
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def set(self, call_id: str, state: CallState) -> None:
        raw = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        # SETEX gives atomic set + ttl
        await self._client.setex(self._key(call_id), self._ttl, raw)

    async def delete(self, call_id: str) -> None:
        await self._client.delete(self._key(call_id))

    async def touch(self, call_id: str) -> None:
        """
        Optional: refresh TTL without overwriting value.
        Useful if you want to keep calls alive even with long pauses.
        """
        await self._client.expire(self._key(call_id), self._ttl)
