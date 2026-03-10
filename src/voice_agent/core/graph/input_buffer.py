from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from voice_agent.core.graph.engine import InterviewEngine
from voice_agent.core.types import CallEvent, EngineChunk, TurnInputMode

logger = logging.getLogger(__name__)


@dataclass
class PendingInput:
    parts: list[str] = field(default_factory=list)
    started_at: float = 0.0
    flush_task: asyncio.Task[None] | None = None
    barge_in_sent: bool = False
    latest_meta: dict[str, Any] | None = None


class CallInputBuffer:
    """
    Buffers short user pauses before flushing one combined turn to the engine.

    Responsibilities:
    - immediately cancel assistant generation on first user speech (barge-in)
    - accumulate short user chunks
    - choose debounce/max-wait from engine input policy
    - flush combined text to engine.stream_event(...)
    """

    def __init__(
        self,
        *,
        engine: InterviewEngine,
        on_engine_chunk: Callable[[str, EngineChunk], Awaitable[None]],
    ) -> None:
        self._engine = engine
        self._on_engine_chunk = on_engine_chunk
        self._pending: dict[str, PendingInput] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, call_id: str) -> asyncio.Lock:
        lock = self._locks.get(call_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[call_id] = lock
        return lock

    async def add_user_text(
        self,
        *,
        call_id: str,
        text: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """
        Add a recognized user chunk.

        Typical use:
        - call this for finalized ASR chunks
        - optionally call for stable partials if your ASR is reliable
        """
        text = self._normalize_text(text)
        if not text:
            return

        # 1) immediately barge in on first chunk of this pending utterance
        async with self._lock_for(call_id):
            pending = self._pending.get(call_id)
            now = time.monotonic()

            if pending is None:
                pending = PendingInput(started_at=now)
                self._pending[call_id] = pending

            if not pending.barge_in_sent:
                pending.barge_in_sent = True
                # Important: cancel assistant immediately, do not wait for debounce
                await self._engine.cancel_active(call_id=call_id)

            pending.parts.append(text)
            pending.latest_meta = meta or pending.latest_meta

            if pending.flush_task and not pending.flush_task.done():
                pending.flush_task.cancel()

        # 2) get current input policy from engine state
        policy = await self._engine.get_input_policy(call_id=call_id)

        # 3) schedule flush based on debounce / max wait
        async with self._lock_for(call_id):
            pending = self._pending.get(call_id)
            if pending is None:
                return

            elapsed_ms = int((time.monotonic() - pending.started_at) * 1000)
            delay_ms = 0 if elapsed_ms >= policy.max_wait_ms else policy.debounce_ms

            # optional early flush if the content already looks complete
            if self._should_flush_early(
                text=self._join_parts(pending.parts),
                mode=await self._engine.get_input_mode(call_id=call_id),
            ):
                delay_ms = 0

            pending.flush_task = asyncio.create_task(
                self._flush_later(
                    call_id=call_id,
                    delay_ms=delay_ms,
                )
            )

    async def flush_now(
        self,
        *,
        call_id: str,
    ) -> None:
        """
        Force immediate flush.
        Useful when ASR emits a strong end-of-utterance signal.
        """
        async with self._lock_for(call_id):
            await self._flush_locked(call_id=call_id)

    async def discard(
        self,
        *,
        call_id: str,
    ) -> None:
        """
        Drop pending input for a call.
        Useful on hangup/reset.
        """
        async with self._lock_for(call_id):
            pending = self._pending.pop(call_id, None)
            if pending and pending.flush_task and not pending.flush_task.done():
                pending.flush_task.cancel()

    async def _flush_later(
        self,
        *,
        call_id: str,
        delay_ms: int,
    ) -> None:
        try:
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)
            async with self._lock_for(call_id):
                await self._flush_locked(call_id=call_id)
        except asyncio.CancelledError:
            return

    async def _flush_locked(
        self,
        *,
        call_id: str,
    ) -> None:
        pending = self._pending.get(call_id)
        if pending is None:
            return

        if pending.flush_task and not pending.flush_task.done():
            pending.flush_task.cancel()

        combined_text = self._join_parts(pending.parts)
        meta = pending.latest_meta
        self._pending.pop(call_id, None)

        if not combined_text:
            return

        logger.info("Flushing buffered user text for %s: %r", call_id, combined_text)

        # Important: do NOT hold buffer lock while streaming engine chunks
        asyncio.create_task(
            self._run_engine_stream(
                call_id=call_id,
                text=combined_text,
                meta=meta,
            )
        )

    async def _run_engine_stream(
        self,
        *,
        call_id: str,
        text: str,
        meta: dict[str, Any] | None,
    ) -> None:
        try:
            async for chunk in self._engine.stream_event(
                call_id=call_id,
                event=CallEvent.USER_TURN,
                user_text=text,
                meta=meta,
            ):
                await self._on_engine_chunk(call_id, chunk)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Engine stream failed for call_id=%s", call_id)

    def _normalize_text(self, text: str) -> str:
        return " ".join((text or "").strip().split())

    def _join_parts(self, parts: list[str]) -> str:
        clean = [p.strip() for p in parts if p and p.strip()]
        return " ".join(clean).strip()

    def _should_flush_early(
        self,
        *,
        text: str,
        mode: TurnInputMode,
    ) -> bool:
        """
        Optional fast-paths so the agent feels quicker.
        """
        t = text.strip().lower()

        if not t:
            return False

        if mode == TurnInputMode.YES_NO:
            return t in {
                "yes", "yeah", "yep", "correct", "right", "no", "nope", "wrong"
            }

        if mode == TurnInputMode.PHONE:
            digits = "".join(ch for ch in t if ch.isdigit())
            return len(digits) >= 8

        return False