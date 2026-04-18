from __future__ import annotations

import inspect
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping, Sequence

from voice_agent.core.types import CallState

TOTAL_DELAY_KEY = "total_delay_s"
AI_DELAY_KEY = "ai_delay_s"
NON_AI_DELAY_KEY = "non_ai_delay_s"
INPUT_TOKENS_KEY = "input_tokens"
OUTPUT_TOKENS_KEY = "output_tokens"
TOTAL_TOKENS_KEY = "total_tokens"
FIRST_TOKEN_DELAY_KEY = "first_token_delay_s"
DELAY_KEYS = (TOTAL_DELAY_KEY, AI_DELAY_KEY, NON_AI_DELAY_KEY)
TOKEN_KEYS = (INPUT_TOKENS_KEY, OUTPUT_TOKENS_KEY, TOTAL_TOKENS_KEY)
NODE_TIMING_KEYS = DELAY_KEYS + TOKEN_KEYS


@dataclass(slots=True)
class NodeTimingContext:
    ai_delay_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


_current_node_timing: ContextVar[NodeTimingContext | None] = ContextVar(
    "current_node_timing",
    default=None,
)


def _coerce_delay(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _coerce_token_count(value: Any) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def get_node_timing_fields(bucket: Mapping[str, Any] | None) -> dict[str, float | int]:
    if not isinstance(bucket, Mapping):
        return {}

    fields: dict[str, float | int] = {}
    for key in DELAY_KEYS:
        if key in bucket:
            fields[key] = round(_coerce_delay(bucket.get(key)), 6)
    for key in TOKEN_KEYS:
        if key in bucket:
            fields[key] = _coerce_token_count(bucket.get(key))
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


def record_node_token_usage(usage: Mapping[str, Any] | None) -> None:
    ctx = _current_node_timing.get()
    if ctx is None or not isinstance(usage, Mapping):
        return

    input_tokens = _coerce_token_count(usage.get(INPUT_TOKENS_KEY))
    output_tokens = _coerce_token_count(usage.get(OUTPUT_TOKENS_KEY))

    total_value = usage.get(TOTAL_TOKENS_KEY)
    total_tokens = (
        _coerce_token_count(total_value)
        if total_value is not None
        else input_tokens + output_tokens
    )

    if input_tokens == 0 and output_tokens == 0 and total_tokens == 0:
        return

    ctx.input_tokens += input_tokens
    ctx.output_tokens += output_tokens
    ctx.total_tokens += total_tokens


def build_node_timing_payload(
    *,
    previous_bucket: Mapping[str, Any] | None,
    total_delay_s: float,
    ai_delay_s: float,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
) -> dict[str, float | int]:
    prev_total = _coerce_delay((previous_bucket or {}).get(TOTAL_DELAY_KEY))
    prev_ai = _coerce_delay((previous_bucket or {}).get(AI_DELAY_KEY))
    prev_input_tokens = _coerce_token_count((previous_bucket or {}).get(INPUT_TOKENS_KEY))
    prev_output_tokens = _coerce_token_count((previous_bucket or {}).get(OUTPUT_TOKENS_KEY))
    prev_total_tokens = _coerce_token_count((previous_bucket or {}).get(TOTAL_TOKENS_KEY))

    total = prev_total + max(0.0, total_delay_s)
    ai = prev_ai + max(0.0, ai_delay_s)
    non_ai = max(total - ai, 0.0)
    input_tokens = prev_input_tokens + _coerce_token_count(input_tokens)
    output_tokens = prev_output_tokens + _coerce_token_count(output_tokens)
    total_tokens = prev_total_tokens + _coerce_token_count(total_tokens)

    return {
        TOTAL_DELAY_KEY: round(total, 6),
        AI_DELAY_KEY: round(ai, 6),
        NON_AI_DELAY_KEY: round(non_ai, 6),
        INPUT_TOKENS_KEY: input_tokens,
        OUTPUT_TOKENS_KEY: output_tokens,
        TOTAL_TOKENS_KEY: total_tokens,
    }


def build_turn_timing_payload(
    *,
    state: CallState,
    total_delay_s: float,
) -> dict[str, float | int]:
    ai_delay_s = 0.0
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    node_data = state.get("node_data") or {}

    for bucket in node_data.values():
        if not isinstance(bucket, Mapping):
            continue
        ai_delay_s += _coerce_delay(bucket.get(AI_DELAY_KEY))
        bucket_input_tokens = _coerce_token_count(bucket.get(INPUT_TOKENS_KEY))
        bucket_output_tokens = _coerce_token_count(bucket.get(OUTPUT_TOKENS_KEY))
        bucket_total_raw = bucket.get(TOTAL_TOKENS_KEY)
        bucket_total_tokens = (
            _coerce_token_count(bucket_total_raw)
            if bucket_total_raw is not None
            else bucket_input_tokens + bucket_output_tokens
        )
        input_tokens += bucket_input_tokens
        output_tokens += bucket_output_tokens
        total_tokens += bucket_total_tokens

    total = max(0.0, total_delay_s)
    ai = max(0.0, ai_delay_s)
    non_ai = max(total - ai, 0.0)

    return {
        TOTAL_DELAY_KEY: round(total, 6),
        AI_DELAY_KEY: round(ai, 6),
        NON_AI_DELAY_KEY: round(non_ai, 6),
        INPUT_TOKENS_KEY: input_tokens,
        OUTPUT_TOKENS_KEY: output_tokens,
        TOTAL_TOKENS_KEY: total_tokens,
    }


def build_recorded_turn_metrics(
    *,
    state: CallState,
    total_delay_s: float,
    first_token_delay_s: float | None = None,
) -> dict[str, float | int | None]:
    payload = build_turn_timing_payload(state=state, total_delay_s=total_delay_s)
    total_delay = _coerce_delay(payload.get(TOTAL_DELAY_KEY))
    first_token_delay: float | None = None

    if first_token_delay_s is not None:
        first_token_delay = round(min(_coerce_delay(first_token_delay_s), total_delay), 6)

    return {
        TOTAL_TOKENS_KEY: _coerce_token_count(payload.get(TOTAL_TOKENS_KEY)),
        TOTAL_DELAY_KEY: round(total_delay, 6),
        FIRST_TOKEN_DELAY_KEY: first_token_delay,
    }


def get_recorded_turn_metrics(turn: Mapping[str, Any] | None) -> dict[str, float | int | None]:
    if not isinstance(turn, Mapping):
        return {
            TOTAL_TOKENS_KEY: None,
            TOTAL_DELAY_KEY: None,
            FIRST_TOKEN_DELAY_KEY: None,
        }

    total_tokens_raw = turn.get(TOTAL_TOKENS_KEY)
    total_delay_raw = turn.get(TOTAL_DELAY_KEY)
    first_token_delay_raw = turn.get(FIRST_TOKEN_DELAY_KEY)

    total_tokens = (
        _coerce_token_count(total_tokens_raw)
        if total_tokens_raw is not None
        else None
    )
    total_delay = round(_coerce_delay(total_delay_raw), 6) if total_delay_raw is not None else None
    first_token_delay = (
        round(_coerce_delay(first_token_delay_raw), 6)
        if first_token_delay_raw is not None
        else None
    )

    if total_delay is not None and first_token_delay is not None:
        first_token_delay = round(min(first_token_delay, total_delay), 6)

    return {
        TOTAL_TOKENS_KEY: total_tokens,
        TOTAL_DELAY_KEY: total_delay,
        FIRST_TOKEN_DELAY_KEY: first_token_delay,
    }


def summarize_recorded_turn_metrics(
    turns: Sequence[Mapping[str, Any] | dict[str, Any]] | None,
) -> dict[str, float | int | None]:
    total_tokens = 0
    total_delays: list[float] = []
    first_token_delays: list[float] = []

    for turn in turns or []:
        metrics = get_recorded_turn_metrics(turn if isinstance(turn, Mapping) else None)

        if metrics[TOTAL_TOKENS_KEY] is not None:
            total_tokens += _coerce_token_count(metrics[TOTAL_TOKENS_KEY])

        if metrics[TOTAL_DELAY_KEY] is not None:
            total_delays.append(_coerce_delay(metrics[TOTAL_DELAY_KEY]))

        if metrics[FIRST_TOKEN_DELAY_KEY] is not None:
            first_token_delays.append(_coerce_delay(metrics[FIRST_TOKEN_DELAY_KEY]))

    avg_total_delay = (
        round(sum(total_delays) / len(total_delays), 6)
        if total_delays
        else None
    )
    avg_first_token_delay = (
        round(sum(first_token_delays) / len(first_token_delays), 6)
        if first_token_delays
        else None
    )

    return {
        TOTAL_TOKENS_KEY: total_tokens,
        "avg_total_delay_s": avg_total_delay,
        "avg_first_token_delay_s": avg_first_token_delay,
    }


def _set_node_timing(
    target_state: dict[str, Any],
    *,
    node_name: str,
    payload: dict[str, float | int],
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
                        input_tokens=ctx.input_tokens,
                        output_tokens=ctx.output_tokens,
                        total_tokens=ctx.total_tokens,
                    ),
                )

    return timed_node


def format_node_timing_summary(state: CallState) -> str:
    rows: list[tuple[str, float, float, float, int, int, int]] = []
    node_data = state.get("node_data") or {}

    for node_name, bucket in node_data.items():
        if not isinstance(bucket, Mapping):
            continue
        if not any(key in bucket for key in NODE_TIMING_KEYS):
            continue

        total_delay_s = _coerce_delay(bucket.get(TOTAL_DELAY_KEY))
        ai_delay_s = _coerce_delay(bucket.get(AI_DELAY_KEY))
        non_ai_delay_s = _coerce_delay(bucket.get(NON_AI_DELAY_KEY))
        input_tokens = _coerce_token_count(bucket.get(INPUT_TOKENS_KEY))
        output_tokens = _coerce_token_count(bucket.get(OUTPUT_TOKENS_KEY))
        total_tokens_raw = bucket.get(TOTAL_TOKENS_KEY)
        total_tokens = (
            _coerce_token_count(total_tokens_raw)
            if total_tokens_raw is not None
            else input_tokens + output_tokens
        )
        rows.append(
            (
                node_name,
                total_delay_s,
                ai_delay_s,
                non_ai_delay_s,
                input_tokens,
                output_tokens,
                total_tokens,
            )
        )

    if not rows:
        return "no node delays or tokens recorded"

    rows.sort(key=lambda row: (-row[1], row[0]))
    return "\n".join(
        (
            f"{node_name}: total={total_delay_s:.3f}s ai={ai_delay_s:.3f}s "
            f"non_ai={non_ai_delay_s:.3f}s tokens={total_tokens} "
            f"in={input_tokens} out={output_tokens}"
        )
        for (
            node_name,
            total_delay_s,
            ai_delay_s,
            non_ai_delay_s,
            input_tokens,
            output_tokens,
            total_tokens,
        ) in rows
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
        f"non_ai={payload[NON_AI_DELAY_KEY]:.3f}s "
        f"tokens={payload[TOTAL_TOKENS_KEY]} "
        f"in={payload[INPUT_TOKENS_KEY]} "
        f"out={payload[OUTPUT_TOKENS_KEY]}"
    )
