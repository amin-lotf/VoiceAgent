from __future__ import annotations

from types import SimpleNamespace

import pytest

from voice_agent.core.graph.node_timing import (
    INPUT_TOKENS_KEY,
    OUTPUT_TOKENS_KEY,
    TOTAL_TOKENS_KEY,
    with_node_timing,
)
from voice_agent.core.llm.openai_llm import _TimedChatOpenAI


class _FakeChunk:
    def __init__(self, content: str, usage_metadata: dict | None = None) -> None:
        self.content = content
        self.usage_metadata = usage_metadata


class _FakeStreamingChatOpenAI:
    async def astream(self, *args, **kwargs):
        yield _FakeChunk("hello")
        yield _FakeChunk(
            "",
            {
                INPUT_TOKENS_KEY: 74,
                OUTPUT_TOKENS_KEY: 25,
                TOTAL_TOKENS_KEY: 99,
            },
        )


class _FakeInvokeChatOpenAI:
    async def ainvoke(self, *args, **kwargs):
        return SimpleNamespace(
            content="hello",
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 5,
                    "total_tokens": 17,
                }
            },
        )


@pytest.mark.asyncio
async def test_timed_chat_openai_records_stream_usage_from_last_chunk():
    llm = _TimedChatOpenAI(_FakeStreamingChatOpenAI())

    async def fake_node(state):
        async for _chunk in llm.astream("prompt"):
            pass
        return {}

    timed_node = with_node_timing("fake_node", fake_node)
    result = await timed_node({"node_data": {}})
    bucket = result["node_data"]["fake_node"]

    assert bucket[INPUT_TOKENS_KEY] == 74
    assert bucket[OUTPUT_TOKENS_KEY] == 25
    assert bucket[TOTAL_TOKENS_KEY] == 99


@pytest.mark.asyncio
async def test_timed_chat_openai_records_invoke_usage_from_response_metadata():
    llm = _TimedChatOpenAI(_FakeInvokeChatOpenAI())

    async def fake_node(state):
        await llm.ainvoke("prompt")
        return {}

    timed_node = with_node_timing("fake_node", fake_node)
    result = await timed_node({"node_data": {}})
    bucket = result["node_data"]["fake_node"]

    assert bucket[INPUT_TOKENS_KEY] == 12
    assert bucket[OUTPUT_TOKENS_KEY] == 5
    assert bucket[TOTAL_TOKENS_KEY] == 17
