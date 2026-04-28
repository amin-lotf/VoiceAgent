from __future__ import annotations

import asyncio
import json

import pytest

from voice_agent.core.api.v1.retell.router import stream_engine_to_retell
from voice_agent.core.api.v1.schemas import RetellResponseOut
from voice_agent.const import TOTAL_TOKENS_KEY
from voice_agent.core.types import CallEvent, ChunkKind, EngineChunk


class _FakeWebSocket:
    def __init__(self) -> None:
        self.frames: list[str] = []

    async def send_text(self, text: str) -> None:
        self.frames.append(text)


class _FakeEngine:
    async def stream_event(self, **kwargs):
        _ = kwargs
        yield EngineChunk(ChunkKind.TOKEN, "Hi ")
        yield EngineChunk(ChunkKind.TOKEN, "there!")
        yield EngineChunk(
            ChunkKind.FINAL,
            {
                "node_data": {
                    "call_operator": {
                        TOTAL_TOKENS_KEY: 99,
                    }
                }
            },
        )


class _FakeSplitTokenEngine:
    async def stream_event(self, **kwargs):
        _ = kwargs
        yield EngineChunk(ChunkKind.TOKEN, "10:30 A")
        yield EngineChunk(ChunkKind.TOKEN, "M.")
        yield EngineChunk(
            ChunkKind.FINAL,
            {
                "node_data": {
                    "call_operator": {
                        TOTAL_TOKENS_KEY: 2,
                    }
                }
            },
        )


class _FakeRecorder:
    def __init__(self) -> None:
        self.turns: list[dict[str, object]] = []

    async def record_turn(self, **kwargs) -> None:
        self.turns.append(kwargs)

    async def record_status(self, **kwargs) -> None:
        _ = kwargs

    async def finish_call(self, **kwargs) -> None:
        _ = kwargs


@pytest.mark.asyncio
async def test_stream_engine_records_assistant_turn_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    perf_values = iter([10.0, 10.4, 11.6])
    monkeypatch.setattr(
        "voice_agent.core.api.v1.retell.router.time.perf_counter",
        lambda: next(perf_values),
    )

    websocket = _FakeWebSocket()
    recorder = _FakeRecorder()

    await stream_engine_to_retell(
        websocket=websocket,
        engine=_FakeEngine(),
        recorder=recorder,
        call_id="call-123",
        response_id=1,
        event=CallEvent.USER_TURN,
        user_text="hello",
        meta={},
        cancel_guard=asyncio.Event(),
    )

    assert len(recorder.turns) == 1
    assert recorder.turns[0]["content"] == "Hi there!"
    assert recorder.turns[0]["total_tokens"] == 99
    assert recorder.turns[0]["total_delay_s"] == 1.6
    assert recorder.turns[0]["first_token_delay_s"] == 0.4


@pytest.mark.asyncio
async def test_stream_engine_forwards_tokens_without_router_buffering() -> None:
    websocket = _FakeWebSocket()
    recorder = _FakeRecorder()

    await stream_engine_to_retell(
        websocket=websocket,
        engine=_FakeSplitTokenEngine(),
        recorder=recorder,
        call_id="call-456",
        response_id=7,
        event=CallEvent.USER_TURN,
        user_text="hello",
        meta={},
        cancel_guard=asyncio.Event(),
    )

    response_frames = [RetellResponseOut.model_validate(json.loads(frame)) for frame in websocket.frames]
    partial_frames = [frame for frame in response_frames if not frame.content_complete]

    assert [frame.content for frame in partial_frames] == ["10:30 A", "M."]
    assert recorder.turns[0]["content"] == "10:30 AM."
