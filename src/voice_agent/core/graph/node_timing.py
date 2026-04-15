from __future__ import annotations

import inspect
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping

from voice_agent.core.types import CallState

TOTAL_DELAY_KEY = "total_delay_s"
AI_DELAY_KEY = "ai_delay_s"
NON_AI_DELAY_KEY = "non_ai_delay_s"
NODE_TIMING_KEYS = (TOTAL_DELAY_KEY, AI_DELAY_KEY, NON_AI_DELAY_KEY)


@dataclass(slots=True)
class NodeTimingContext:
    ai_delay_s: float = 0.0


_current_node_timing: ContextVar[NodeTimingContext | None] = ContextVar(
    "current_node_timing",
    default=None,
)


def _coerce_delay(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def get_node_timing_fields(bucket: Mapping[str, Any] | None) -> dict[str, float]:
    if not isinstance(bucket, Mapping):
        return {}

    fields: dict[str, float] = {}
    for key in NODE_TIMING_KEYS:
        if key in bucket:
            fields[key] = round(_coerce_delay(bucket.get(key)), 6)
    return fields


def reset_node_timing_data(state: CallState | dict[str, Any]) -> None:
    node_data = state.get("node_data")
    if not isinstance(node_data, dict):
        return

    for bucket in node_data.values():
        if not isinstance(bucket, dict):
            continue
        for key in NODE_TIMING_KEYS:
            bucket.pop(key, None)


def record_node_ai_delay(duration_s: float) -> None:
    ctx = _current_node_timing.get()
    if ctx is None:
        return
    ctx.ai_delay_s += max(0.0, duration_s)


def build_node_timing_payload(
    *,
    previous_bucket: Mapping[str, Any] | None,
    total_delay_s: float,
    ai_delay_s: float,
) -> dict[str, float]:
    prev_total = _coerce_delay((previous_bucket or {}).get(TOTAL_DELAY_KEY))
    prev_ai = _coerce_delay((previous_bucket or {}).get(AI_DELAY_KEY))

    total = prev_total + max(0.0, total_delay_s)
    ai = prev_ai + max(0.0, ai_delay_s)
    non_ai = max(total - ai, 0.0)

    return {
        TOTAL_DELAY_KEY: round(total, 6),
        AI_DELAY_KEY: round(ai, 6),
        NON_AI_DELAY_KEY: round(non_ai, 6),
    }


def build_turn_timing_payload(
    *,
    state: CallState,
    total_delay_s: float,
) -> dict[str, float]:
    ai_delay_s = 0.0
    node_data = state.get("node_data") or {}

    for bucket in node_data.values():
        if not isinstance(bucket, Mapping):
            continue
        ai_delay_s += _coerce_delay(bucket.get(AI_DELAY_KEY))

    total = max(0.0, total_delay_s)
    ai = max(0.0, ai_delay_s)
    non_ai = max(total - ai, 0.0)

    return {
        TOTAL_DELAY_KEY: round(total, 6),
        AI_DELAY_KEY: round(ai, 6),
        NON_AI_DELAY_KEY: round(non_ai, 6),
    }


def _set_node_timing(
    target_state: dict[str, Any],
    *,
    node_name: str,
    payload: dict[str, float],
) -> None:
    node_data = target_state.setdefault("node_data", {})
    bucket = node_data.setdefault(node_name, {})
    if not isinstance(bucket, dict):
        bucket = {}
        node_data[node_name] = bucket
    bucket.update(payload)


def with_node_timing(node_name: str, node_fn):
    async def timed_node(state: CallState):
        previous_bucket = ((state.get("node_data") or {}).get(node_name)) or {}
        ctx = NodeTimingContext()
        token = _current_node_timing.set(ctx)
        started_at = perf_counter()
        result: Any = None

        try:
            result = node_fn(state)
            if inspect.isawaitable(result):
                result = await result
            return result
        finally:
            _current_node_timing.reset(token)
            target_state = result if isinstance(result, dict) else state
            if isinstance(target_state, dict):
                _set_node_timing(
                    target_state,
                    node_name=node_name,
                    payload=build_node_timing_payload(
                        previous_bucket=previous_bucket,
                        total_delay_s=perf_counter() - started_at,
                        ai_delay_s=ctx.ai_delay_s,
                    ),
                )

    return timed_node


def format_node_timing_summary(state: CallState) -> str:
    rows: list[tuple[str, float, float, float]] = []
    node_data = state.get("node_data") or {}

    for node_name, bucket in node_data.items():
        if not isinstance(bucket, Mapping):
            continue
        if not any(key in bucket for key in NODE_TIMING_KEYS):
            continue

        total_delay_s = _coerce_delay(bucket.get(TOTAL_DELAY_KEY))
        ai_delay_s = _coerce_delay(bucket.get(AI_DELAY_KEY))
        non_ai_delay_s = _coerce_delay(bucket.get(NON_AI_DELAY_KEY))
        rows.append((node_name, total_delay_s, ai_delay_s, non_ai_delay_s))

    if not rows:
        return "no node delays recorded"

    rows.sort(key=lambda row: (-row[1], row[0]))
    return "\n".join(
        f"{node_name}: total={total_delay_s:.3f}s ai={ai_delay_s:.3f}s non_ai={non_ai_delay_s:.3f}s"
        for node_name, total_delay_s, ai_delay_s, non_ai_delay_s in rows
    )


def format_turn_timing_summary(
    *,
    state: CallState,
    total_delay_s: float,
) -> str:
    payload = build_turn_timing_payload(state=state, total_delay_s=total_delay_s)
    return (
        f"turn: total={payload[TOTAL_DELAY_KEY]:.3f}s "
        f"ai={payload[AI_DELAY_KEY]:.3f}s "
        f"non_ai={payload[NON_AI_DELAY_KEY]:.3f}s"
    )
