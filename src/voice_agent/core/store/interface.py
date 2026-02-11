from typing import Optional

from voice_agent.core.types import CallState


class StateStore:
    async def get(self, call_id: str) -> Optional[CallState]:
        ...

    async def set(self, call_id: str, state: CallState) -> None:
        ...

    async def delete(self, call_id: str) -> None:
        ...