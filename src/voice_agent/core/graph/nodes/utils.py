from __future__ import annotations

import re

from langgraph.config import get_stream_writer
from voice_agent.core.types import CallEvent, CallState, AppointmentCreate


def ensure_spoken_on_user_turn(state: CallState) -> CallState:
    """
    Guarantee that a USER_TURN ends with a spoken response unless the call is ending.
    """
    if state.get("event") == CallEvent.USER_TURN:
        if not state.get('assistant_streamed', False):
            text = "Sorry, I didn't catch that. Could you say that again?"
            state["assistant_text"] = text
            writer = get_stream_writer()
            if writer:
                for word in text.split():
                    writer(("assistant_token", word + " "))
                state["assistant_streamed"] = True
            state['end_call'] = False
    return state


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


def is_appointment_complete(data: AppointmentCreate) -> bool:
    required_keys = AppointmentCreate.__annotations__.keys()
    return required_keys <= data.keys()


def safe_json_parse(text: str) -> str:
    """
    Strip code fences / surrounding prose and return the best-effort JSON substring.
    """
    t = (text or "").strip()
    if not t:
        return ""
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    l = t.find("{")
    r = t.rfind("}")
    if l != -1 and r != -1 and r > l:
        t = t[l: r + 1]
    return t.strip()
