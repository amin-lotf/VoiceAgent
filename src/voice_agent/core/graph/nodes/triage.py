from __future__ import annotations

import json

from langgraph.config import get_stream_writer

from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.triage import build_triage_prompt
from voice_agent.core.types import CallEvent, CallPhase, CallState, ClinicIntent
from .utils import ensure_spoken_on_user_turn


EMERGENCY_FALLBACK_MESSAGE = (
    "I'm not able to help with medical emergencies. "
    "Please hang up and call 911 or your local emergency services right away."
)


async def node_triage_precheck(state: CallState) -> CallState:
    """Lightweight emergency detection before normal routing."""
    state["triage_triggered"] = False
    if state.get("event") != CallEvent.USER_TURN:
        return state

    user_text = (state.get("user_text") or "").strip()
    if not user_text:
        return state

    prompt = build_triage_prompt(user_text)
    writer = get_stream_writer()
    decision = "safe"
    emergency_message = ""
    raw_response = ""

    try:
        async for chunk in LLM.astream(prompt):
            raw_response += chunk.content or ""

        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()

        data = json.loads(cleaned) if cleaned else {}
        decision = str(data.get("decision", decision)).lower()
        emergency_message = (data.get("message") or "").strip()
    except Exception:
        decision = "safe"

    if decision == "emergency":
        emergency_message = emergency_message or EMERGENCY_FALLBACK_MESSAGE
        if writer and emergency_message:
            for token in emergency_message.split():
                writer(("assistant_token", token + " "))

        state["intent"] = ClinicIntent.URGENT_SYMPTOM
        state["phase"] = CallPhase.TRIAGE
        state["pending_question"] = None
        state["triage_triggered"] = True
        state["assistant_text"] = emergency_message

    return state


def node_triage_respond(state: CallState) -> CallState:
    """Escalate to emergency guidance."""
    if not (state.get("assistant_text") or "").strip():
        state["assistant_text"] = EMERGENCY_FALLBACK_MESSAGE
    state["end_call"] = True
    state["phase"] = CallPhase.DONE
    state["pending_question"] = None
    ensure_spoken_on_user_turn(state)
    return state
