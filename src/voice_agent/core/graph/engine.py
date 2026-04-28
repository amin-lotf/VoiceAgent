from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any, AsyncIterator, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_agent.core.graph.graph import build_call_graph
from voice_agent.core.graph.node_timing import (
    format_node_timing_summary,
    format_turn_timing_summary,
    reset_node_timing_data,
)
from voice_agent.core.graph.utils import RunControl, sanitize_spoken_text
from voice_agent.core.settings import settings
from voice_agent.core.store.redis_store import RedisStateStore
from voice_agent.core.types import (
    CallEvent,
    CallPhase,
    CallState,
    ChunkKind,
    EngineChunk,
    RunResult, NextAction, AssistantPhase,
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
    Streaming LangGraph engine with barge-in buffering for non-interruptible sections.

    Behavior:
    - interruptible active run:
        cancel current run, then start new one immediately
    - non-interruptible active run:
        keep appending user text into a per-call pending buffer
        and process it after the protected run finishes
    - only one graph run is active per call at a time
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

        # Runtime-only pending user text accumulated during non-interruptible sections.
        self._pending_texts: dict[str, str] = {}

        # Runtime-only latest deferred event/meta to use when draining buffered text.
        self._pending_event_meta: dict[str, tuple[CallEvent, dict[str, Any]]] = {}

    def _append_or_replace_message(
            self,
            messages: list[dict[str, str]] | None,
            *,
            role: str,
            content: str | None,
            limit: int = settings.MESSAGE_HISTORY_SIZE,
            replace_if_prefix: bool = False,
    ) -> list[dict[str, str]]:
        text = (content or "").strip()
        if not text:
            return list(messages or [])

        out = list(messages or [])

        if (
                replace_if_prefix
                and out
                and out[-1].get("role") == role
        ):
            prev = (out[-1].get("content") or "").strip()
            if prev and (text.startswith(prev) or prev.startswith(text)):
                out[-1] = {"role": role, "content": text}
                return out[-limit:]

        out.append({"role": role, "content": text})
        return out[-limit:]

    def _append_message(
            self,
            messages: list[dict[str, str]] | None,
            *,
            role: str,
            content: str | None,
            limit: int = 20,
    ) -> list[dict[str, str]]:
        text = (content or "").strip()
        if not text:
            return list(messages or [])

        out = list(messages or [])
        out.append({"role": role, "content": text})
        return out[-limit:]

    def _should_record_user_event(self, event: CallEvent) -> bool:
        return event == CallEvent.USER_TURN

    def _apply_turn_history_on_start(
            self,
            *,
            state: CallState,
            event: CallEvent,
            user_text: str | None,
    ) -> None:
        text = (user_text or "").strip()
        if not text:
            return
        if not self._should_record_user_event(event):
            return

        state["messages"] = self._append_or_replace_message(
            state.get("messages"),
            role="user",
            content=text,
            replace_if_prefix=True,
        )
        state["prev_user_text"] = text

    def _apply_turn_history_on_finish(
            self,
            *,
            state: CallState,
    ) -> None:
        assistant_text = sanitize_spoken_text((state.get("assistant_text") or "").strip())
        if assistant_text:
            state["assistant_text"] = assistant_text
            state["messages"] = self._append_message(
                state.get("messages"),
                role="assistant",
                content=assistant_text,
            )
            state["prev_assistant_text"] = assistant_text

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

    async def cancel_active(self, *, call_id: str, force: bool = False) -> bool:
        """
        Cancel current active run for this call unless it is in a non-interruptible section.

        Returns:
            True  -> caller may start a new run now
            False -> caller must not start a new run now
        """
        active = self._active.get(call_id)
        if not active:
            return True

        task = active.task
        if task.done():
            return True

        if not force and not active.interruptible:
            logger.info(
                "Skipping cancel for call_id=%s because active run is non-interruptible",
                call_id,
            )
            return False

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return True

    def _cleanup_active_if_current(self, *, call_id: str, task: asyncio.Task[Any]) -> None:
        """
        Remove active entry only if it still points to this exact task.
        """
        active = self._active.get(call_id)
        if active and active.task is task:
            self._active.pop(call_id, None)

    # ----------------------------
    # Pending-input helpers
    # ----------------------------

    def _append_pending_text(self, *, call_id: str, text: str | None) -> None:
        stripped = (text or "").strip()
        if not stripped:
            return

        prev = self._pending_texts.get(call_id, "").strip()
        if not prev:
            self._pending_texts[call_id] = stripped
            return

        if stripped.startswith(prev) or prev.startswith(stripped):
            self._pending_texts[call_id] = stripped
        else:
            self._pending_texts[call_id] = f"{prev} {stripped}".strip()

    def _set_pending_event_meta(
        self,
        *,
        call_id: str,
        event: CallEvent,
        meta: dict[str, Any] | None,
    ) -> None:
        self._pending_event_meta[call_id] = (event, meta or {})

    def _pop_pending_followup(
            self,
            *,
            call_id: str,
    ) -> tuple[CallEvent, str | None, dict[str, Any]]:
        text = self._pending_texts.pop(call_id, "").strip() or None
        event, meta = self._pending_event_meta.pop(call_id, (CallEvent.USER_TURN, {}))
        return event, text, meta

    def _has_pending_followup(self, *, call_id: str) -> bool:
        parts = self._pending_texts.get(call_id, [])
        return any(bool(p and p.strip()) for p in parts)

    def _clear_runtime_buffers(self, *, call_id: str) -> None:
        self._pending_texts.pop(call_id, None)
        self._pending_event_meta.pop(call_id, None)

    # ----------------------------
    # State helpers
    # ----------------------------

    async def _load_state(self, *, call_id: str) -> CallState:
        state = await self._store.get(call_id)
        if state is None:
            state = {
                "call_id": call_id,
                "phase": CallPhase.GREETING,
                "assistant_phase":AssistantPhase.COLLECTING_USER_INTENT,
                "messages": [],
                "assistant_text": "",
                "assistant_streamed": False,
                "node_data": {},
                "appointment_draft": {},
                "appointment_patch": {},
                "end_call": False,
                "prev_user_text": "",
                "prev_assistant_text": "",
                "internal_call": False,
            }
        else:
            state.setdefault("messages", [])
            state.setdefault("node_data", {})
            state.setdefault("appointment_draft", {})
            state.setdefault("appointment_patch", {})
            state.setdefault("end_call", False)
            state.setdefault("prev_user_text", "")
            state.setdefault("prev_assistant_text", "")
            state.setdefault('internal_call', False)

        return state

    def _sanitize_state_for_persist(self, state: CallState) -> CallState:
        clean = dict(state)
        clean.pop("_run_control", None)
        clean.pop("assistant_streamed", None)
        if clean.get("assistant_text"):
            clean["assistant_text"] = sanitize_spoken_text(str(clean["assistant_text"]))
        if clean.get("prev_assistant_text"):
            clean["prev_assistant_text"] = sanitize_spoken_text(str(clean["prev_assistant_text"]))
        return clean

    def _log_node_timing_summary(
        self,
        *,
        call_id: str,
        event: CallEvent,
        state: CallState,
        turn_total_delay_s: float,
    ) -> None:
        logger.info(
            "delay summary for   event=%s:\n%s\n%s",
            event,
            format_turn_timing_summary(state=state, total_delay_s=turn_total_delay_s),
            format_node_timing_summary(state),
            extra={"call_id": call_id},
        )

    async def _persist_or_delete(
            self,
            *,
            call_id: str,
            final_state: CallState,
            event: CallEvent,
    ) -> None:
        self._apply_turn_history_on_finish(state=final_state)

        safe_state = self._sanitize_state_for_persist(final_state)
        end_call = bool(safe_state.get("end_call", False))

        if end_call or event == CallEvent.CALL_ENDED:
            await self._store.delete(call_id)
            self._clear_runtime_buffers(call_id=call_id)
        else:
            await self._store.set(call_id, safe_state)

    # ----------------------------
    # Single-run executor
    # ----------------------------

    async def _stream_single_run(
        self,
        *,
        call_id: str,
        event: CallEvent,
        user_text: str | None,
        meta: dict[str, Any] | None,
        reset_timings: bool = False,
    ) -> AsyncIterator[EngineChunk]:
        """
        Execute exactly one graph run and stream its chunks.
        Does not auto-drain buffered follow-ups.
        Does not emit FINAL.
        """
        lock = self._lock_for(call_id)

        async with lock:
            state = await self._load_state(call_id=call_id)
            if reset_timings:
                reset_node_timing_data(state)
            state["assistant_text"] = ""
            state["assistant_streamed"] = False
            state["event"] = event
            state["user_text"] = user_text
            state["meta"] = meta or {}
            state["next_action"] = NextAction.OTHER
            state["internal_call"] = False

            self._apply_turn_history_on_start(
                state=state,
                event=event,
                user_text=user_text,
            )

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
                                        await aio_queue.put(EngineChunk(ChunkKind.TOKEN, payload))
                                    else:
                                        await aio_queue.put(
                                            EngineChunk(ChunkKind.DEBUG, (event_type, payload))
                                        )

                            elif mode == "values":
                                if isinstance(data, dict):
                                    final_state = cast(CallState, data)

                        elif isinstance(chunk, dict):
                            final_state = cast(CallState, chunk)

                except asyncio.CancelledError:
                    logger.info("Graph run cancelled", extra={"call_id": call_id})
                    raise
                except Exception:
                    logger.exception("Graph run failed", extra={"call_id": call_id})
                    raise
                finally:
                    await aio_queue.put(None)

            task = asyncio.create_task(_drive_graph())
            self._active[call_id] = ActiveRun(task=task, interruptible=True)

        try:
            while True:
                item = await aio_queue.get()
                if item is None:
                    break
                yield item

        except asyncio.CancelledError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

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
            raise

        try:
            await task
        except asyncio.CancelledError:
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

        if final_state is None:
            final_state = state

        async with lock:
            await self._persist_or_delete(
                call_id=call_id,
                final_state=final_state,
                event=event,
            )
            self._cleanup_active_if_current(call_id=call_id, task=task)

        # Stash latest completed final state on the instance for the outer loop.
        # This avoids duplicating the whole single-run implementation shape.
        self._last_final_state = self._sanitize_state_for_persist(final_state)

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
        Stream tokens/debug chunks and emit FINAL only after all deferred buffered
        text has been drained.
        """
        turn_started_at = perf_counter()
        self._last_final_state: CallState | None = None

        can_start = await self.cancel_active(call_id=call_id)

        if not can_start:
            self._append_pending_text(call_id=call_id, text=user_text)
            self._set_pending_event_meta(call_id=call_id, event=event, meta=meta)
            return

        next_event = event
        next_user_text = user_text
        next_meta = meta or {}
        last_safe_state: CallState | None = None
        reset_timings = True

        while True:
            async for chunk in self._stream_single_run(
                call_id=call_id,
                event=next_event,
                user_text=next_user_text,
                meta=next_meta,
                reset_timings=reset_timings,
            ):
                yield chunk
            reset_timings = False

            if self._last_final_state is not None:
                last_safe_state = self._last_final_state

            if not self._has_pending_followup(call_id=call_id):
                break

            next_event, next_user_text, next_meta = self._pop_pending_followup(call_id=call_id)

            if not next_user_text:
                break

        if last_safe_state is None:
            lock = self._lock_for(call_id)
            async with lock:
                state = await self._load_state(call_id=call_id)
                last_safe_state = self._sanitize_state_for_persist(state)

        self._log_node_timing_summary(
            call_id=call_id,
            event=event,
            state=last_safe_state,
            turn_total_delay_s=perf_counter() - turn_started_at,
        )
        yield EngineChunk(ChunkKind.FINAL, last_safe_state)

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
        Non-streaming version with the same buffering rule:
        - interruptible active run -> cancel and start now
        - non-interruptible active run -> append text and return current state
        """
        lock = self._lock_for(call_id)
        turn_started_at = perf_counter()

        can_start = await self.cancel_active(call_id=call_id)

        if not can_start:
            self._append_pending_text(call_id=call_id, text=user_text)
            self._set_pending_event_meta(call_id=call_id, event=event, meta=meta)

            async with lock:
                state = await self._load_state(call_id=call_id)
                safe_state = self._sanitize_state_for_persist(state)

            assistant_text = (safe_state.get("assistant_text") or "").strip()
            return RunResult(assistant_text=assistant_text, state=safe_state)

        next_event = event
        next_user_text = user_text
        next_meta = meta or {}
        final_state: CallState | None = None
        reset_timings = True

        while True:
            async with lock:
                state = await self._load_state(call_id=call_id)
                if reset_timings:
                    reset_node_timing_data(state)
                    reset_timings = False
                state["assistant_text"] = ""
                state["assistant_streamed"] = False
                state["event"] = next_event
                state["user_text"] = next_user_text
                state["meta"] = next_meta

                self._apply_turn_history_on_start(
                    state=state,
                    event=next_event,
                    user_text=next_user_text,
                )

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
                    event=next_event,
                )
                self._cleanup_active_if_current(call_id=call_id, task=task)

            if not self._has_pending_followup(call_id=call_id):
                break

            next_event, next_user_text, next_meta = self._pop_pending_followup(call_id=call_id)
            if not next_user_text:
                break

        if final_state is None:
            async with lock:
                final_state = await self._load_state(call_id=call_id)

        safe_state = self._sanitize_state_for_persist(final_state)
        assistant_text = (safe_state.get("assistant_text") or "").strip()
        self._log_node_timing_summary(
            call_id=call_id,
            event=event,
            state=safe_state,
            turn_total_delay_s=perf_counter() - turn_started_at,
        )
        return RunResult(assistant_text=assistant_text, state=safe_state)
