from __future__ import annotations

import asyncio
import contextlib
import json
import re
from copy import deepcopy
from datetime import datetime
from logging import Logger
from typing import Any
from zoneinfo import ZoneInfo

from langgraph.config import get_stream_writer

from voice_agent.const import DEFAULT_TZ
from voice_agent.core.types import CallEvent, CallState, AppointmentCreate






def stream_text_response( text: str) -> dict:
    local_state:dict= {"assistant_text": text}
    writer = get_stream_writer()
    if writer:
        for word in text.split():
            writer(("assistant_token", word + " "))
        local_state["assistant_streamed"] = True
    return local_state




def get_state_data(state: CallState, node: str) -> dict:
    return state.get("node_data").get(node, {})

def set_node_data(state: dict, node: str,n_data:dict[str,Any]) -> None:
    state.setdefault('node_data', {})
    state['node_data'].setdefault(node, {})
    state['node_data'][node].update(n_data)

def reset_node_data(state: dict, node: str) -> None:
    state.setdefault('node_data', {})
    state['node_data'][node]={}

def delete_node_value(state: dict, node: str, key: str) -> None:
    node_data = state.get("node_data")
    bucket = node_data.get(node)
    if not isinstance(bucket, dict):
        return
    bucket.pop(key, None)
    # optional cleanup if the node bucket becomes empty
    if not bucket:
        node_data.pop(node, None)


async def _delayed_filler(writer, filler_text:str, delay_s: float = 0.45) -> None:
    await asyncio.sleep(delay_s)
    if writer:
        writer(("assistant_token", filler_text))

async def call_llm_with_slow_filler(*, writer, coro, filler_text:str, delay_s: float = 0.45):
    """
    Run `coro` (awaitable). If it doesn't finish within delay_s, emit one filler line.
    """
    filler_task = None
    try:
        filler_task = asyncio.create_task(_delayed_filler(writer,filler_text, delay_s))
        result = await coro
        return result
    finally:
        if filler_task and not filler_task.done():
            filler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await filler_task


def parse_date(value: Any,tz_info:ZoneInfo=DEFAULT_TZ,logger:Logger|None=None) -> datetime | None:

    if not value:
        return None

    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        else:
            return None

        # Normalize timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz_info)

        return dt.astimezone(tz_info)

    except Exception as e:
        if logger is not None:
            logger.warning("Failed to parse datetime: %s (%s)", value, e)
        return None

def format_date(dt: datetime,tz_info:ZoneInfo=DEFAULT_TZ) -> str:
    if not isinstance(dt, datetime):
        return ""
    local_dt = dt.astimezone(tz_info)
    try:
        return local_dt.strftime("%A, %b %-d at %-I:%M %p")
    except Exception:
        # Windows-compatible (no %-d)
        return local_dt.strftime("%A, %b %d at %I:%M %p").lstrip("0").replace(" 0", " ")


def ensure_spoken_on_user_turn(state: CallState) -> dict:
    """
    Guarantee that a USER_TURN ends with a spoken response unless the call is ending.
    """
    local_state:dict={}
    if state.get("event") == CallEvent.USER_TURN:
        if not state.get('assistant_streamed', False):
            text = "Sorry, I didn't catch that. Could you say that again?"
            local_state=stream_text_response(text)
            local_state['end_call'] = False
    return local_state


def normalize_phone(text: str | None) -> str | None:
    if not text:
        return None
    digits = "".join(re.findall(r"\d", text))
    # Accept local numbers down to 7 digits; cap at 15 for international formats.
    if len(digits) < 7 or len(digits) > 15:
        return None
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def is_appointment_complete(d: dict) -> bool:
    required = ("name", "phone", "reason_for_visit", "start_at", "end_at", "notes")
    if not all(k in d for k in required):
        return False
    if not d["name"] or not d["phone"] or not d["reason_for_visit"]:
        return False
    if d["start_at"] is None or d["end_at"] is None:
        return False
    if not isinstance(d.get("notes"), list):
        return False
    return True


def safe_json_parse(text: str,logger:Logger|None=None) -> dict:
    """
    Strip code fences / surrounding prose and return parsed JSON dict.
    """
    t = (text or "").strip()
    if not t:
        return {}

    # remove code fences
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()

    # extract first {...} block
    l = t.find("{")
    r = t.rfind("}")
    if l != -1 and r != -1 and r > l:
        t = t[l: r + 1]

    try:
        data = json.loads(t)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        logger.warning("safe_json_parse failed to decode JSON")
        return {}
