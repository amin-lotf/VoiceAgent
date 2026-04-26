from __future__ import annotations

import queue
from collections.abc import Iterator, MutableMapping
from typing import Any


SessionState = MutableMapping[str, Any]
StreamFrame = dict[str, Any]


def ensure_stream_state(state: SessionState) -> None:
    state.setdefault("streams", {})
    state.setdefault("response_floor", 0)
    state.setdefault("pending_ws_error", None)


def reset_stream_state(state: SessionState) -> None:
    state["streams"] = {}
    state["response_floor"] = 0
    state["pending_ws_error"] = None


def begin_response(state: SessionState, response_id: int) -> None:
    state["response_floor"] = response_id

    streams: dict[int, list[StreamFrame]] = state.setdefault("streams", {})
    for stale_rid in [rid for rid in streams if rid < response_id]:
        del streams[stale_rid]


def buffer_ws_message(state: SessionState, payload: dict[str, Any]) -> None:
    message_type = payload.get("_type")
    if message_type == "error":
        error = str(payload.get("error", "ws error"))
        state["last_error"] = error
        state["pending_ws_error"] = error
        state["ws_status"] = "error"
        return

    if message_type == "open":
        state["ws_status"] = "connected"
        return

    if message_type == "close":
        state["ws_status"] = "disconnected"
        return

    if "response_id" not in payload:
        return

    response_id = int(payload["response_id"])
    if response_id < int(state.get("response_floor", 0)):
        return

    streams: dict[int, list[StreamFrame]] = state.setdefault("streams", {})
    streams.setdefault(response_id, []).append(
        {
            "response_id": response_id,
            "content": payload.get("content") or "",
            "content_complete": bool(payload.get("content_complete", False)),
            "end_call": payload.get("end_call"),
        }
    )


def drain_inbox(state: SessionState) -> None:
    inbox: "queue.Queue[dict[str, Any]] | None" = state.get("inbox")
    if inbox is None:
        return

    while True:
        try:
            payload = inbox.get_nowait()
        except queue.Empty:
            return

        buffer_ws_message(state, payload)


def pop_buffered_frame(state: SessionState, response_id: int) -> StreamFrame | None:
    streams: dict[int, list[StreamFrame]] = state.setdefault("streams", {})
    buffered_frames = streams.get(response_id)
    if not buffered_frames:
        return None

    frame = buffered_frames.pop(0)
    if not buffered_frames:
        streams.pop(response_id, None)
    return frame


def take_pending_ws_error(state: SessionState) -> str | None:
    error = state.get("pending_ws_error")
    state["pending_ws_error"] = None
    return error


def stream_for_rid(
    state: SessionState,
    response_id: int,
    *,
    poll_timeout_s: float = 0.1,
) -> Iterator[str]:
    inbox: "queue.Queue[dict[str, Any]]" = state["inbox"]

    while True:
        frame = pop_buffered_frame(state, response_id)
        if frame is None:
            error = take_pending_ws_error(state)
            if error:
                raise RuntimeError(error)

            try:
                payload = inbox.get(timeout=poll_timeout_s)
            except queue.Empty:
                continue

            buffer_ws_message(state, payload)

            error = take_pending_ws_error(state)
            if error:
                raise RuntimeError(error)

            frame = pop_buffered_frame(state, response_id)
            if frame is None:
                continue

        content = frame.get("content") or ""
        if content:
            yield content

        if bool(frame.get("content_complete", False)):
            return
