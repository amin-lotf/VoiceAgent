import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import voice_agent.core.graph.nodes.greeting as greeting_node
import voice_agent.core.graph.nodes.triage as triage_node
from voice_agent.core.api.v1.hubspot import router as hubspot_router
from voice_agent.core.api.v1.schemas import (
    RetellConfigOut,
    RetellResponseOut,
)
from voice_agent.core.graph.engine import InterviewEngine
from voice_agent.core.store.interface import StateStore
from voice_agent.core.types import CallEvent, CallPhase, ChunkKind


class _InMemoryStore(StateStore):
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def get(self, call_id: str):
        return self._data.get(call_id)

    async def set(self, call_id: str, state):
        self._data[call_id] = state

    async def delete(self, call_id: str):
        self._data.pop(call_id, None)


class _FakeChunk:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """Tiny stand-in for ChatOpenAI; yields a couple tokens then finishes."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def astream(self, prompt):
        for token in self._tokens:
            yield _FakeChunk(token)

    async def ainvoke(self, prompt):
        return _FakeChunk("".join(self._tokens))


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    greeting_llm = _FakeLLM(["Hi ", "there!"])
    emergency_message = "Please hang up and call 911 now."
    triage_llm = _FakeLLM([f'{{"decision":"emergency","message":"{emergency_message}"}}'])

    monkeypatch.setattr(greeting_node, "LLM", greeting_llm)
    monkeypatch.setattr(triage_node, "LLM", triage_llm)
    monkeypatch.setattr(triage_node, "EMERGENCY_FALLBACK_MESSAGE", emergency_message)

    app = FastAPI()
    store = _InMemoryStore()
    app.state.store = store
    app.state.engine = InterviewEngine(store=store)
    app.include_router(hubspot_router.router)
    return TestClient(app)


def test_retell_ws_greeting_streams_tokens(client: TestClient):
    """Connect to the Retell-compatible WS and ensure greeting tokens stream."""
    with client.websocket_connect("/hubspot/llm/test-call") as ws:
        config_payload = ws.receive_json()
        # Validate shape against Retell schema
        RetellConfigOut.model_validate(config_payload)

        # Stream until we see the final message for response_id=0
        tokens: list[str] = []
        final_seen = False

        for _ in range(20):
            payload = ws.receive_json()
            # Ping frames may interleave; ignore them
            if payload.get("response_type") == "ping_pong":
                continue

            # Parse/validate via schema
            response = RetellResponseOut.model_validate(payload)
            if response.response_id != 0:
                continue

            if response.content_complete:
                final_seen = True
                break

            tokens.append(response.content)

        assert final_seen, "Did not receive final greeting frame"
        assert "".join(tokens) == "Hi there!", "Greeting tokens should be streamed in order"


@pytest.mark.asyncio
async def test_engine_triage_streams_emergency(monkeypatch: pytest.MonkeyPatch):
    emergency_message = "Please hang up and call 911 now."
    triage_llm = _FakeLLM([f'{{"decision":"emergency","message":"{emergency_message}"}}'])
    monkeypatch.setattr(triage_node, "LLM", triage_llm)
    monkeypatch.setattr(triage_node, "EMERGENCY_FALLBACK_MESSAGE", emergency_message)

    store = _InMemoryStore()
    engine = InterviewEngine(store=store)

    tokens: list[str] = []
    final_state = None
    async for chunk in engine.stream_event(
        call_id="call-1",
        event=CallEvent.USER_TURN,
        user_text="I have chest pain and trouble breathing.",
        meta={},
    ):
        if chunk.kind == ChunkKind.TOKEN:
            tokens.append(str(chunk.data))
        if chunk.kind == ChunkKind.FINAL:
            final_state = chunk.data

    assert "".join(tokens).strip() == emergency_message
    assert final_state is not None
    assert final_state.get("phase") == CallPhase.DONE
    assert final_state.get("end_call") is True
    assert final_state.get("assistant_text") == emergency_message


def test_retell_ws_greeting_then_triage(client: TestClient):
    """Full path: greeting streams, then user speaks emergency and triage streams."""
    with client.websocket_connect("/hubspot/llm/test-call") as ws:
        ws.receive_json()  # config

        # Drain greeting stream
        while True:
            payload = ws.receive_json()
            if payload.get("response_type") == "ping_pong":
                continue
            response = RetellResponseOut.model_validate(payload)
            if response.response_id != 0:
                continue
            if response.content_complete:
                break

        # Send user message that should trigger triage
        ws.send_text(
            json.dumps(
                {
                    "interaction_type": "response_required",
                    "response_id": 1,
                    "transcript": [{"role": "user", "content": "I have chest pain"}],
                }
            )
        )

        tokens: list[str] = []
        final_seen = False
        end_call_flag = False

        for _ in range(40):
            payload = ws.receive_json()
            if payload.get("response_type") == "ping_pong":
                continue

            response = RetellResponseOut.model_validate(payload)
            if response.response_id != 1:
                continue

            if response.content_complete:
                final_seen = True
                end_call_flag = bool(response.end_call)
                break

            tokens.append(response.content)

        assert final_seen, "Did not receive final triage frame"
        assert "".join(tokens).strip() == "Please hang up and call 911 now."
        assert end_call_flag is True
