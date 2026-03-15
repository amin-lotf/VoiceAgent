from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_agent.core.graph.graph import build_call_graph
from voice_agent.core.graph.utils import RunControl
from voice_agent.core.store.redis_store import RedisStateStore
from voice_agent.core.types import (
    CallEvent,
    CallPhase,
    CallState,
    ChunkKind,
    EngineChunk,
    RunResult
)

logger = logging.getLogger(__name__)




@dataclass
class ActiveRun:
    """
    Tracks the active graph task for one call.
    """
    task: asyncio.Task[Any]
    interruptible: bool = True





class InterviewEngine:
    """
    Streaming LangGraph engine with proper barge-in handling.

    Key behavior:
    - tokens are yielded as soon as they are produced
    - per-call lock protects only short critical sections
      (load/register/persist), not the whole stream
    - active generation can be canceled on barge-in
    - non-interruptible critical sections are supported for DB commits, etc.
    - runtime-only fields are stripped before persistence
    """

    def __init__(
        self,
        *,
        store: RedisStateStore,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        self._graph = build_call_graph(sessionmaker)
        self._store = store
        self._locks: dict[str, asyncio.Lock] = {}
        self._active: dict[str, ActiveRun] = {}

    # ----------------------------
    # Per-call lock helpers
    # ----------------------------

    def _lock_for(self, call_id: str) -> asyncio.Lock:
        lock = self._locks.get(call_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[call_id] = lock
        return lock

    # ----------------------------
    # Active-run helpers
    # ----------------------------

    def _set_active_interruptible(self, call_id: str, interruptible: bool) -> None:
        active = self._active.get(call_id)
        if active and not active.task.done():
            active.interruptible = interruptible

    async def cancel_active(self, *, call_id: str, force: bool = False) -> None:
        """
        Cancel current active run for this call, unless it is in a non-interruptible section.

        force=True should be rare; useful only for hard shutdown behavior.
        """
        active = self._active.get(call_id)
        if not active:
            return

        task = active.task
        if task.done():
            return

        if not force and not active.interruptible:
            logger.info(
                "Skipping cancel for call_id=%s because active run is non-interruptible",
                call_id,
            )
            return

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    #

    def _cleanup_active_if_current(self, *, call_id: str, task: asyncio.Task[Any]) -> None:
        """
        Remove active entry only if it still points to this exact task.
        Prevents an older run from deleting a newer run's entry.
        """
        active = self._active.get(call_id)
        if active and active.task is task:
            self._active.pop(call_id, None)

    # ----------------------------
    # State helpers
    # ----------------------------

    async def _load_state(self, *, call_id: str) -> CallState:
        state = await self._store.get(call_id)
        if state is None:
            state = {
                "call_id": call_id,
                "phase": CallPhase.GREETING,
                "messages": [],
                "assistant_text": "",
                "assistant_streamed": False,
                "node_data": {},
                "appointment_draft": {},
                "appointment_patch": {},
                "end_call": False,
            }
        else:
            # defensive normalization for old states
            state.setdefault("messages", [])
            state.setdefault("node_data", {})
            state.setdefault("appointment_draft", {})
            state.setdefault("appointment_patch", {})
            state.setdefault("end_call", False)

        return state

    def _sanitize_state_for_persist(self, state: CallState) -> CallState:
        """
        Remove runtime-only objects before storing to Redis.
        """
        clean = dict(state)
        clean.pop("_run_control", None)
        clean.pop("assistant_streamed", None)
        return cast(CallState, clean)

    async def _persist_or_delete(
        self,
        *,
        call_id: str,
        final_state: CallState,
        event: CallEvent,
    ) -> None:
        safe_state = self._sanitize_state_for_persist(final_state)
        end_call = bool(safe_state.get("end_call", False))

        if end_call or event == CallEvent.CALL_ENDED:
            await self._store.delete(call_id)
        else:
            await self._store.set(call_id, safe_state)

    # ----------------------------
    # Public streaming API
    # ----------------------------

    async def stream_event(
        self,
        *,
        call_id: str,
        event: CallEvent,
        user_text: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AsyncIterator[EngineChunk]:
        """
        Stream tokens/debug chunks and finally emit FINAL with the final state.

        Important:
        - We cancel any active run BEFORE starting the new run.
        - We do not hold the per-call lock while yielding the stream.
        """
        lock = self._lock_for(call_id)

        # 1) try barge-in cancellation before starting the next run
        await self.cancel_active(call_id=call_id)

        # 2) prepare state + register new active task inside short critical section
        async with lock:
            state = await self._load_state(call_id=call_id)
            state["assistant_text"] = ""
            state["assistant_streamed"] = False
            state["event"] = event
            state["user_text"] = user_text
            state["meta"] = meta or {}

            control = RunControl(
                set_interruptible=lambda value: self._set_active_interruptible(call_id, value)
            )
            state["_run_control"] = control

            final_state: CallState | None = None
            aio_queue: asyncio.Queue[EngineChunk | None] = asyncio.Queue()

            async def _drive_graph() -> None:
                nonlocal final_state
                try:
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
                                        await aio_queue.put(
                                            EngineChunk(ChunkKind.TOKEN, payload)
                                        )
                                    else:
                                        await aio_queue.put(
                                            EngineChunk(
                                                ChunkKind.DEBUG,
                                                (event_type, payload),
                                            )
                                        )

                            elif mode == "values":
                                if isinstance(data, dict):
                                    final_state = cast(CallState, data)

                        elif isinstance(chunk, dict):
                            final_state = cast(CallState, chunk)

                except asyncio.CancelledError:
                    logger.info("Graph run cancelled for call_id=%s", call_id)
                    raise
                except Exception:
                    logger.exception("Graph run failed for call_id=%s", call_id)
                    raise
                finally:
                    # Always close the queue so the outer streamer can finish.
                    with contextlib.suppress(asyncio.QueueFull):
                        await aio_queue.put(None)

            task = asyncio.create_task(_drive_graph())
            self._active[call_id] = ActiveRun(task=task, interruptible=True)

        # 3) stream outside the lock
        try:
            while True:
                item = await aio_queue.get()
                if item is None:
                    break
                yield item

        except asyncio.CancelledError:
            # If the caller consuming this async generator gets cancelled,
            # cancel the graph task too.
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

            if final_state is None:
                final_state = state

            # Persist best-effort state after cancellation.
            with contextlib.suppress(Exception):
                async with lock:
                    await asyncio.shield(
                        self._persist_or_delete(
                            call_id=call_id,
                            final_state=final_state,
                            event=event,
                        )
                    )
                    self._cleanup_active_if_current(call_id=call_id, task=task)
            raise

        # 4) wait for task completion after queue closes
        try:
            await task
        except asyncio.CancelledError:
            # Canceled by barge-in or external cancellation.
            if final_state is None:
                final_state = state

            with contextlib.suppress(Exception):
                async with lock:
                    await asyncio.shield(
                        self._persist_or_delete(
                            call_id=call_id,
                            final_state=final_state,
                            event=event,
                        )
                    )
                    self._cleanup_active_if_current(call_id=call_id, task=task)
            return

        except Exception:
            # Graph failed with an exception. Persist best-effort state.
            if final_state is None:
                final_state = state

            async with lock:
                with contextlib.suppress(Exception):
                    await self._persist_or_delete(
                        call_id=call_id,
                        final_state=final_state,
                        event=event,
                    )
                self._cleanup_active_if_current(call_id=call_id, task=task)
            raise

        # 5) normal completion
        if final_state is None:
            final_state = state

        async with lock:
            await self._persist_or_delete(
                call_id=call_id,
                final_state=final_state,
                event=event,
            )
            self._cleanup_active_if_current(call_id=call_id, task=task)

        yield EngineChunk(
            ChunkKind.FINAL,
            self._sanitize_state_for_persist(final_state),
        )

    # ----------------------------
    # Public non-streaming API
    # ----------------------------

    async def run_event(
        self,
        *,
        call_id: str,
        event: CallEvent,
        user_text: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> RunResult:
        """
        Non-streaming version.
        """
        lock = self._lock_for(call_id)

        await self.cancel_active(call_id=call_id)

        async with lock:
            state = await self._load_state(call_id=call_id)
            state["assistant_text"] = ""
            state["assistant_streamed"] = False
            state["event"] = event
            state["user_text"] = user_text
            state["meta"] = meta or {}

            control = RunControl(
                set_interruptible=lambda value: self._set_active_interruptible(call_id, value)
            )
            state["_run_control"] = control

            task = asyncio.create_task(self._graph.ainvoke(state))
            self._active[call_id] = ActiveRun(task=task, interruptible=True)

        try:
            raw_final_state = await task
        except asyncio.CancelledError:
            async with lock:
                self._cleanup_active_if_current(call_id=call_id, task=task)
            raise
        except Exception:
            async with lock:
                self._cleanup_active_if_current(call_id=call_id, task=task)
            raise

        if not isinstance(raw_final_state, dict):
            final_state = state
        else:
            final_state = cast(CallState, raw_final_state)

        async with lock:
            await self._persist_or_delete(
                call_id=call_id,
                final_state=final_state,
                event=event,
            )
            self._cleanup_active_if_current(call_id=call_id, task=task)

        safe_state = self._sanitize_state_for_persist(final_state)
        assistant_text = (safe_state.get("assistant_text") or "").strip()
        return RunResult(assistant_text=assistant_text, state=safe_state)