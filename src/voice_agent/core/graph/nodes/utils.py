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
    digits = "".join(re.findall(r"\\d", text))
    if len(digits) < 10 or len(digits) > 15:
        return None
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def is_appointment_complete(data: AppointmentCreate) -> bool:
    required_keys = AppointmentCreate.__annotations__.keys()
    return required_keys <= data.keys()


