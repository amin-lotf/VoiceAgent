from __future__ import annotations

from voice_agent.core.types import  CallState



def node_fill_appointment_slot(state: CallState) -> CallState:
    appointment = state.get("appointment") or {}

    return state
