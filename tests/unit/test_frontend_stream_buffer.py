from __future__ import annotations

import queue
from typing import Any

from voice_agent.frontend.stream_buffer import (
    begin_response,
    buffer_ws_message,
    ensure_stream_state,
    stream_for_rid,
)


def _make_state() -> dict[str, Any]:
    state: dict[str, Any] = {
        "inbox": queue.Queue(),
        "last_error": "",
        "ws_status": "disconnected",
    }
    ensure_stream_state(state)
    return state


def test_stream_for_rid_keeps_future_response_tokens_buffered() -> None:
    state = _make_state()
    inbox: "queue.Queue[dict[str, Any]]" = state["inbox"]

    inbox.put({"response_id": 1, "content": "Okay, one moment please.", "content_complete": False})
    inbox.put({"response_id": 2, "content": "What is ", "content_complete": False})
    inbox.put({"response_id": 1, "content": "", "content_complete": True})
    inbox.put({"response_id": 2, "content": "your name for the appointment?", "content_complete": False})
    inbox.put({"response_id": 2, "content": "", "content_complete": True})

    first_response = "".join(stream_for_rid(state, 1))
    second_response = "".join(stream_for_rid(state, 2))

    assert first_response == "Okay, one moment please."
    assert second_response == "What is your name for the appointment?"


def test_begin_response_drops_stale_partial_streams() -> None:
    state = _make_state()
    inbox: "queue.Queue[dict[str, Any]]" = state["inbox"]

    buffer_ws_message(
        state,
        {"response_id": 1, "content": "I can help with that. What is ", "content_complete": False},
    )
    begin_response(state, 2)

    assert 1 not in state["streams"]

    inbox.put({"response_id": 1, "content": "your name?", "content_complete": False})
    inbox.put({"response_id": 2, "content": "What is ", "content_complete": False})
    inbox.put({"response_id": 2, "content": "your name for the appointment?", "content_complete": False})
    inbox.put({"response_id": 2, "content": "", "content_complete": True})

    assert "".join(stream_for_rid(state, 2)) == "What is your name for the appointment?"
    assert 1 not in state["streams"]
