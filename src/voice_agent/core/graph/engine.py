from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal

from voice_agent.core.graph.graph import build_call_graph
from voice_agent.core.store.interface import StateStore
from voice_agent.core.types import CallState, EngineChunk, ChunkKind, CallPhase, CallEvent


class InterviewEngine:
    """
    True streaming:
    - yields tokens as soon as they are produced
    - persists only at the end (final values)
    - supports barge-in cancellation
    - per-call lock prevents concurrent turns corrupting state
    """

    def __init__(self, *, store: StateStore):
        self._graph = build_call_graph()
        self._store = store
        self._locks: dict[str, asyncio.Lock] = {}
        self._active: dict[str, asyncio.Task] = {}

    def _lock_for(self, call_id: str) -> asyncio.Lock:
        lock = self._locks.get(call_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[call_id] = lock
        return lock

    async def cancel_active(self, *, call_id: str) -> None:
        t = self._active.get(call_id)
        if t and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def stream_event(
        self,
        *,
        call_id: str,
        event: CallEvent,
        user_text: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AsyncIterator[EngineChunk]:
        lock = self._lock_for(call_id)

        async with lock:
            # 1) cancel any in-flight generation (barge-in)
            await self.cancel_active(call_id=call_id)

            # 2) load state
            state = await self._store.get(call_id)
            if state is None:
                state = {
                    "call_id": call_id,
                    "messages": [],
                    "assistant_text": "",
                    "phase": CallPhase.NEW,
                    "pending_question": None,
                    "event": None,
                    "user_text": None,
                    "meta": {},
                    "end_call": False,
                }

            # 3) inject event envelope
            state["event"] = event
            state["user_text"] = user_text
            state["meta"] = meta or {}

            # We'll update this once we receive final values from LangGraph
            final_state: CallState | None = None

            async def _drive_graph(queue:asyncio.Queue[EngineChunk | None]) -> None:
                nonlocal final_state
                async for chunk in self._graph.astream(
                    state,
                    stream_mode=["custom", "values"],
                ):
                    # True streaming: push tokens immediately to the outer generator
                    if isinstance(chunk, tuple) and len(chunk) == 2:
                        mode, data = chunk

                        if mode == "custom":
                            # Expect ("custom", (event_type, payload))
                            if isinstance(data, tuple) and len(data) == 2:
                                event_type, payload = data
                                if event_type == "assistant_token":
                                    queue.put_nowait(EngineChunk(ChunkKind.TOKEN, payload))
                                else:
                                    queue.put_nowait(EngineChunk(ChunkKind.DEBUG, (event_type, payload)))

                        elif mode == "values":
                            final_state = data

                    elif isinstance(chunk, dict):
                        final_state = chunk

                # Signal completion
                queue.put_nowait(None)

            # 4) run graph in a task and stream from a queue
            aio_queue: asyncio.Queue[EngineChunk | None] = asyncio.Queue()

            task = asyncio.create_task(_drive_graph(aio_queue))
            self._active[call_id] = task

            try:
                while True:
                    item = await aio_queue.get()
                    if item is None:
                        break
                    yield item
            except asyncio.CancelledError:
                # If the *consumer* cancels, stop graph too
                task.cancel()
                raise
            finally:
                # If generation is cancelled due to barge-in, don't persist partials here.
                # (You CAN choose to persist partial assistant_text; I recommend no.)
                pass

            # 5) Wait for the graph task to finish (or raise)
            try:
                await task
            except asyncio.CancelledError:
                # barge-in cancellation; no final persistence
                return

            # 6) Persist final state ONCE (after stream is done)
            if final_state is None:
                # Defensive fallback; treat the updated `state` as final if graph didn't emit values
                final_state = state

            end_call = bool(final_state.get("end_call", False))
            if end_call or event == CallEvent.HANGUP:
                await self._store.delete(call_id)
            else:
                await self._store.set(call_id, final_state)

            # 7) Yield final state (useful to your WS layer for logging/metrics)
            yield EngineChunk(ChunkKind.FINAL, final_state)
