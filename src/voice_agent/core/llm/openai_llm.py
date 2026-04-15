from __future__ import annotations

import time
from typing import Any

from langchain_openai import ChatOpenAI

from voice_agent.core.graph.node_timing import record_node_ai_delay
from voice_agent.core.settings import settings


class _TimedChatOpenAI:
    def __init__(self, inner: ChatOpenAI) -> None:
        self._inner = inner

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._inner, attr)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        try:
            return await self._inner.ainvoke(*args, **kwargs)
        finally:
            record_node_ai_delay(time.perf_counter() - started_at)

    async def astream(self, *args: Any, **kwargs: Any):
        started_at = time.perf_counter()
        try:
            async for chunk in self._inner.astream(*args, **kwargs):
                yield chunk
        finally:
            record_node_ai_delay(time.perf_counter() - started_at)


LLM = _TimedChatOpenAI(
    ChatOpenAI(
        model=settings.REPLY_MODEL,
        temperature=settings.REPLY_TEMPERATURE,
        api_key=settings.OPENAI_API_KEY,
        seed=settings.RANDOM_SEED,
    )
)
