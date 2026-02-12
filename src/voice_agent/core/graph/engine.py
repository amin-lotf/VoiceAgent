from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from voice_agent.core.graph.graph import build_call_graph
from voice_agent.core.store.redis_store import RedisStateStore
from voice_agent.core.types import CallState, EngineChunk, ChunkKind, CallPhase, CallEvent, RunResult

logger = logging.getLogger(__name__)





class InterviewEngine:
    """
    True streaming:
    - yields tokens as soon as they are produced
    - persists only at the end (final values)
    - supports barge-in cancellation
    - per-call lock prevents concurrent turns corrupting state

    Also supports non-streaming runs via run_event().
    """

    def __init__(self, *, store: RedisStateStore):
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

    async def _load_state(self, *, call_id: str) -> CallState:
        state = await self._store.get(call_id)
        if state is None:
            state = {
                "call_id": call_id,
                "messages": [],
                "assistant_text": "",
                "phase": CallPhase.GREETING,
                "pending_question": None,
                "event": None,
                "user_text": None,
                "meta": {},
                "end_call": False,
            }
        return state

    async def _persist_or_delete(
        self,
        *,
        call_id: str,
        final_state: CallState,
        event: CallEvent,
    ) -> None:
        end_call = bool(final_state.get("end_call", False))
        if end_call or event == CallEvent.HANGUP:
            await self._store.delete(call_id)
        else:
            await self._store.set(call_id, final_state)

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
            state = await self._load_state(call_id=call_id)
            logger.warning(f"? state: {state}")

            # 3) inject event envelope
            state["event"] = event
            state["user_text"] = user_text
            state["meta"] = meta or {}

            final_state: CallState | None = None

            async def _drive_graph(queue: asyncio.Queue[EngineChunk | None]) -> None:
                nonlocal final_state
                async for chunk in self._graph.astream(
                    state,
                    stream_mode=["custom", "values"],
                ):
                    if isinstance(chunk, tuple) and len(chunk) == 2:
                        mode, data = chunk

                        if mode == "custom":
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

                queue.put_nowait(None)

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
                task.cancel()
                raise
            finally:
                pass

            try:
                await task
            except asyncio.CancelledError:
                return

            if final_state is None:
                final_state = state

            await self._persist_or_delete(call_id=call_id, final_state=final_state, event=event)

            yield EngineChunk(ChunkKind.FINAL, final_state)

    async def run_event(
            self,
            *,
            call_id: str,
            event: CallEvent,
            user_text: str | None = None,
            meta: dict[str, Any] | None = None,
    ) -> RunResult:
        lock = self._lock_for(call_id)

        async with lock:
            await self.cancel_active(call_id=call_id)

            state = await self._load_state(call_id=call_id)
            state["event"] = event
            state["user_text"] = user_text
            state["meta"] = meta or {}

            # Use ainvoke for non-streaming final state
            task = asyncio.create_task(self._graph.ainvoke(state))
            self._active[call_id] = task

            try:
                final_state = await task
            except asyncio.CancelledError:
                raise

            if not isinstance(final_state, dict):
                # Defensive: LangGraph should return a dict-like state, but don't assume.
                final_state = state

            await self._persist_or_delete(call_id=call_id, final_state=final_state, event=event)

            assistant_text = (final_state.get("assistant_text") or "").strip()
            return RunResult(assistant_text=assistant_text, state=final_state)
