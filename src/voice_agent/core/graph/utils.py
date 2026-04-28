import asyncio
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Awaitable, Callable, TypeVar
import unicodedata
from zoneinfo import ZoneInfo
from copy import deepcopy
from typing import Any, Dict

from voice_agent.const import DEFAULT_TZ
from voice_agent.core.graph.nodes.utils import set_node_data
from voice_agent.core.types import NextAction

T = TypeVar("T")

_UNICODE_PUNCT_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u00a0": " ",
    }
)
_RANGE_DASH_RE = re.compile(r"(?<=\w)\u2013(?=\w)")
_EM_DASH_RE = re.compile(r"\s*[\u2014\u2015]+\s*")
_TIME_WITH_MERIDIEM_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?\s*[Mm]\.?\b"
)
_TRAILING_TIME_RE = re.compile(r"\b\d{1,2}(?::\d{2})?\s*$")
_LEADING_MERIDIEM_RE = re.compile(r"^[AaPp]\.?\s*[Mm]\.?\b")
_MISSING_SPACE_AFTER_PUNCT_RE = re.compile(r"([,.!?])(?=[A-Za-z0-9])")
_MULTISPACE_RE = re.compile(r"\s+")
_SENTENCE_START_LOWER_RE = re.compile(r"(^|[.?!]\s+)([a-z])")


@dataclass
class RunControl:
    """
    Runtime-only control object injected into state for the currently executing run.
    Must never be persisted.
    """

    set_interruptible: Callable[[bool], None]


async def run_non_interruptible(
        state: dict[str, Any],
        fn: Callable[[], Awaitable[T]],
) -> T:
    """
    Helper for critical sections inside LangGraph nodes.

    Usage:
        async def _commit():
            await confirm_appointment(...)

        await run_non_interruptible(state, _commit)

    This does two things:
    - marks the active run as non-interruptible from the engine's point of view
    - shields the actual critical awaitable from task cancellation
    """
    control = state.get("_run_control")
    if control is not None:
        control.set_interruptible(False)

    try:
        return await asyncio.shield(fn())
    finally:
        if control is not None:
            control.set_interruptible(True)


def mark_node_succeeded(
        state: dict[str, Any],
        local_state: dict[str, Any],
        node_name: str,
) -> dict[str, Any]:
    node_data = state.get("node_data", {})

    err = node_data.get("error_handling", {})
    counters = node_data.get("error_counters", {})

    by_node = counters.get("by_node", {})
    current_node_counter = by_node.get(node_name, {})

    new_by_node = {
        **by_node,
        node_name: {
            **current_node_counter,
            "consecutive": 0,
        },
    }
    set_node_data(local_state, "error_handling", {
            "error_counters": {
                **counters,
                "by_node": new_by_node,
            }
        })
    # local_state: dict[str, Any] = {
    #     "node_data": {
    #         "error_counters": {
    #             **counters,
    #             "by_node": new_by_node,
    #         }
    #     }
    # }

    if err.get("failed_node") == node_name:
        set_node_data(local_state, "error_handling", {
            "has_error": False,
            "failed_node": None,
            "error_type": None,
            "error_message": None,
            "retryable": None,
        })
        # local_state["node_data"]["error_handling"] = {
        #     "has_error": False,
        #     "failed_node": None,
        #     "error_type": None,
        #     "error_message": None,
        #     "retryable": None,
        # }


def record_node_error(
        state: dict[str, Any],
        node_name: str,
        error_type: str,
        error_message: str | None = None,
        retryable: bool = True,
) -> dict[str, Any]:
    node_data = state.get("node_data", {})
    counters = node_data.get("error_counters", {})

    global_error_count = counters.get("global_error_count", 0)

    by_node = counters.get("by_node", {})
    current_node_counter = by_node.get(node_name, {})

    new_by_node = {
        **by_node,
        node_name: {
            **current_node_counter,
            "consecutive": current_node_counter.get("consecutive", 0) + 1,
            "total": current_node_counter.get("total", 0) + 1,
        },
    }

    return {
        "node_data": {
            "error_handling": {
                "has_error": True,
                "failed_node": node_name,
                "error_type": error_type,
                "error_message": error_message,
                "retryable": retryable,
            },
            "error_counters": {
                **counters,
                "global_error_count": global_error_count + 1,
                "by_node": new_by_node,
            },
        }
    }


def _part_of_day_phrase(dt: datetime) -> str:
    return "in the morning" if dt.hour < 12 else "in the afternoon"


def _format_clock_time(dt: datetime) -> str:
    return dt.strftime("%-I:%M")


def _replace_meridiem(match: re.Match[str]) -> str:
    hour = int(match.group(1))
    minute = match.group(2)
    meridiem = match.group(3).lower()
    period = "in the morning" if meridiem == "a" else "in the afternoon"
    clock = f"{hour}:{minute}" if minute else str(hour)
    return f"{clock} {period}"


def sanitize_spoken_text(text: str) -> str:
    text = (text or "").replace("\r", " ").replace("\n", " ")
    if not text.strip():
        return ""

    text = text.translate(_UNICODE_PUNCT_TRANSLATION)
    text = _RANGE_DASH_RE.sub(" to ", text)
    text = _EM_DASH_RE.sub(". ", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = _TIME_WITH_MERIDIEM_RE.sub(_replace_meridiem, text)
    text = _MISSING_SPACE_AFTER_PUNCT_RE.sub(r"\1 ", text)
    text = _MULTISPACE_RE.sub(" ", text).strip()
    text = _SENTENCE_START_LOWER_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2).upper()}",
        text,
    )
    return text


def commit_assistant_message(state: dict, limit: int = 20) -> dict:
    local_state = {}
    text = state.get("assistant_text")
    text = sanitize_spoken_text((text or "").strip())
    if not text:
        return {}

    messages = list(state.get("messages") or [])
    messages.append({"role": "assistant", "content": text})
    local_state["messages"] = messages[-limit:]
    local_state["prev_assistant_text"] = text
    local_state["assistant_text"] = ""
    return local_state

def prep_internal_operator_call(state:dict, *,clear_messages:bool=False) -> dict:
    local_state = commit_assistant_message(state)
    if clear_messages:
        local_state["messages"] = []
    local_state["internal_call"] = True
    local_state['next_action'] = NextAction.CALL_OPERATOR
    return local_state



class SpokenTextStreamNormalizer:
    def __init__(self, *, tail_chars: int = 48) -> None:
        self._tail_chars = max(16, tail_chars)
        self._buffer = ""

    def push(self, text: str) -> str:
        if not text:
            return ""

        self._buffer += text
        if len(self._buffer) <= self._tail_chars:
            return ""

        safe_limit = len(self._buffer) - self._tail_chars
        split_at = self._buffer.rfind(" ", 0, safe_limit)
        while split_at >= 0:
            emitted = self._buffer[: split_at + 1]
            remaining = self._buffer[split_at + 1:]
            if not (
                    _TRAILING_TIME_RE.search(emitted)
                    and _LEADING_MERIDIEM_RE.match(remaining)
            ):
                break
            split_at = self._buffer.rfind(" ", 0, split_at)
        if split_at < 0:
            return ""

        chunk = self._buffer[: split_at + 1]
        self._buffer = self._buffer[split_at + 1:]

        sanitized = sanitize_spoken_text(chunk)
        if sanitized and chunk.endswith(" "):
            sanitized += " "
        return sanitized

    def flush(self) -> str:
        if not self._buffer:
            return ""

        sanitized = sanitize_spoken_text(self._buffer)
        self._buffer = ""
        return sanitized


def iso_to_human_readable(
        iso_str: str,
        *,
        tz: ZoneInfo = DEFAULT_TZ,
        include_weekday: bool = True,
        include_time: bool = True,
) -> str:
    dt = datetime.fromisoformat(iso_str)

    # Normalize timezone (important if DB stores mixed tz)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)

    parts = []

    if include_weekday:
        parts.append(dt.strftime("%A"))  # Monday

    parts.append(dt.strftime("%B %-d"))  # April 13 (Linux/macOS)
    # If on Windows use: "%B %d".lstrip("0")

    text = ", ".join(parts)
    if include_time:
        text = f"{text} at {_format_clock_time(dt)} {_part_of_day_phrase(dt)}"

    return text
