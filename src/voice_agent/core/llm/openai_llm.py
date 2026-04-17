from __future__ import annotations

import time
from typing import Any, Mapping

from langchain_openai import ChatOpenAI

from voice_agent.core.graph.node_timing import record_node_ai_delay, record_node_token_usage
from voice_agent.core.settings import settings


class _TimedChatOpenAI:
    def __init__(self, inner: ChatOpenAI) -> None:
        self._inner = inner

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._inner, attr)

    @staticmethod
    def _extract_usage_metadata(value: Any) -> Mapping[str, Any] | None:
        usage_metadata = getattr(value, "usage_metadata", None)
        if isinstance(usage_metadata, Mapping):
            return usage_metadata

        if isinstance(value, Mapping):
            usage_metadata = value.get("usage_metadata")
            if isinstance(usage_metadata, Mapping):
                return usage_metadata

        response_metadata = getattr(value, "response_metadata", None)
        if not isinstance(response_metadata, Mapping) and isinstance(value, Mapping):
            response_metadata = value.get("response_metadata")

        if not isinstance(response_metadata, Mapping):
            return None

        token_usage = response_metadata.get("token_usage") or response_metadata.get("usage")
        if not isinstance(token_usage, Mapping):
            return None

        return {
            "input_tokens": token_usage.get("prompt_tokens", token_usage.get("input_tokens")),
            "output_tokens": token_usage.get(
                "completion_tokens",
                token_usage.get("output_tokens"),
            ),
            "total_tokens": token_usage.get("total_tokens"),
        }

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        try:
            result = await self._inner.ainvoke(*args, **kwargs)
            record_node_token_usage(self._extract_usage_metadata(result))
            return result
        finally:
            record_node_ai_delay(time.perf_counter() - started_at)

    async def astream(self, *args: Any, **kwargs: Any):
        started_at = time.perf_counter()
        latest_usage_metadata: Mapping[str, Any] | None = None
        try:
            async for chunk in self._inner.astream(*args, **kwargs):
                usage_metadata = self._extract_usage_metadata(chunk)
                if usage_metadata is not None:
                    latest_usage_metadata = usage_metadata
                yield chunk
        finally:
            record_node_token_usage(latest_usage_metadata)
            record_node_ai_delay(time.perf_counter() - started_at)


LLM = _TimedChatOpenAI(
    ChatOpenAI(
        model=settings.REPLY_MODEL,
        temperature=settings.REPLY_TEMPERATURE,
        api_key=settings.OPENAI_API_KEY,
        seed=settings.RANDOM_SEED,
        model_kwargs={
            "stream_options": {"include_usage": True}
        },
    )
)

LLM_Non_stream = _TimedChatOpenAI(
    ChatOpenAI(
        model=settings.REPLY_MODEL,
        temperature=settings.REPLY_TEMPERATURE,
        api_key=settings.OPENAI_API_KEY,
        seed=settings.RANDOM_SEED,
    )
)
