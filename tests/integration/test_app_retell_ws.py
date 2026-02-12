import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import voice_agent.core.graph.nodes.greeting as greeting_node
import voice_agent.core.graph.nodes.triage as triage_node
from voice_agent.core.api.v1.fastapi_app import fastapi_app
from voice_agent.core.api.v1.schemas import RetellConfigOut, RetellResponseOut
from voice_agent.core.graph.engine import InterviewEngine
from voice_agent.core.store.interface import StateStore


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
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def astream(self, prompt):
        for token in self._tokens:
            yield _FakeChunk(token)

    async def ainvoke(self, prompt):
        return _FakeChunk("".join(self._tokens))


@pytest.fixture()
def app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    greeting_llm = _FakeLLM(["Hi ", "there!"])
    emergency_message = "Please hang up and call 911 now."
    triage_llm = _FakeLLM([f'{{"decision":"emergency","message":"{emergency_message}"}}'])

    monkeypatch.setattr(greeting_node, "LLM", greeting_llm)
    monkeypatch.setattr(triage_node, "LLM", triage_llm)
    monkeypatch.setattr(triage_node, "EMERGENCY_FALLBACK_MESSAGE", emergency_message)

    # Reuse the actual app but bypass lifespan to avoid connecting to Redis.
    app = fastapi_app
    store = _InMemoryStore()
    app.state.store = store
    app.state.engine = InterviewEngine(store=store)

    return TestClient(app, lifespan="off")


def _drain_greeting(ws) -> None:
    while True:
        payload = ws.receive_json()
        if payload.get("response_type") == "ping_pong":
            continue
        response = RetellResponseOut.model_validate(payload)
        if response.response_id != 0:
            continue
        if response.content_complete:
            break


def test_app_retell_ws_greeting(app_client: TestClient):
    with app_client.websocket_connect("/hubspot/llm/app-call") as ws:
        config_payload = ws.receive_json()
        RetellConfigOut.model_validate(config_payload)

        tokens: list[str] = []
        final_seen = False

        for _ in range(20):
            payload = ws.receive_json()
            if payload.get("response_type") == "ping_pong":
                continue
            response = RetellResponseOut.model_validate(payload)
            if response.response_id != 0:
                continue
            if response.content_complete:
                final_seen = True
                break
            tokens.append(response.content)

        assert final_seen
        assert "".join(tokens) == "Hi there!"


def test_app_retell_ws_greeting_then_triage(app_client: TestClient):
    with app_client.websocket_connect("/hubspot/llm/app-call-2") as ws:
        ws.receive_json()  # config frame
        _drain_greeting(ws)

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

        assert final_seen
        assert "".join(tokens).strip() == "Please hang up and call 911 now."
        assert end_call_flag is True
