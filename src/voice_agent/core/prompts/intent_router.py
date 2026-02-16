from __future__ import annotations

import json
from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.core.prompts.utils import _enum_values
from voice_agent.core.types import CallPhase, CallState, ClinicIntent, OfficeTopic

INTENT_ROUTER_SYSTEM_PROMPT = (
    "You are a routing brain for a medical clinic voice agent. "
    "Your only job is to choose ClinicIntent the next step. "
    "Return ONLY a single JSON object. No markdown. No prose. No extra keys.\n\n"

    "Valid ClinicIntent values: "
    "book_appointment, reschedule, cancel, "
    "office_info,  human_handoff, clarify.\n\n"
    

    "Decision rules (pick the best match):\n"
    "- If the caller wants to BOOK an appointment -> intent=book_appointment.\n"
    "- If the caller wants to RESCHEDULE an existing appointment -> intent=reschedule.\n"
    "- If the caller wants to CANCEL an appointment -> intent=cancel.\n"
    "- If the caller asks about office topics, e.g., hours, address, location, and parking, -> intent=office_info.\n"
    "- if the caller's message describes a potential medical emergency that requires 911 or local emergency services -> intent=triage.\n"
    "- if the caller "
    "- If the caller's request is unclear -> intent=clarify and set confidence<=0.4.\n"
    "- Use intent=human_handoff,  when the request is clearly outside scope.\n\n"
    f"- Valid OfficeTopic values: {_enum_values(OfficeTopic)}.\n\n"
    "Output schema (JSON only; keys must be exactly these): "
    "{\"intent\":\"<ClinicIntent>\",\"office_topics\":[],\"end_call\":false,\"confidence\":0.0}\n"
    "Rules:\n"
    "- ALWAYS include office_topics as an array.\n"
    "- If intent is NOT office_info, office_topics MUST be [].\n"
    "- If intent is office_info, choose one or more topics from OfficeTopic that match the caller's request.\n"
    "- If the caller asks for multiple office details in one turn, include multiple topics.\n"
    "- If the caller asks for book/reschedule/cancel appointment actions AND office info in the same turn, "
    "prioritize the appointment action (intent=book_appointment/reschedule/cancel) and set office_topics.\n"
    "- confidence must be between 0 and 1.\n"
)



def _phase_value(phase: CallPhase | str | None) -> str:
    if isinstance(phase, CallPhase):
        return phase.value
    return str(phase or CallPhase.INTENT_ROUTING.value)


def _intent_value(intent: ClinicIntent | str | None) -> str:
    if isinstance(intent, ClinicIntent):
        return intent.value
    return str(intent or "none")


def build_intent_router_prompt(user_text: str, state: CallState):
    pending_question = state.get("pending_question") or "none"
    prior_intent = _intent_value(state.get("intent"))

    appointment = state.get("appointment") or {}
    appt_summary = {
        "date": appointment.get("date"),
        "time": appointment.get("time"),
        "provider": appointment.get("provider"),
        "reason": appointment.get("reason"),
    }

    human_content = "\n".join(
        [
            f"Caller said: {user_text or '[silence]'}",
            "Context:",

            f"- pending_question: {pending_question}",
            f"- prior_intent: {prior_intent}",
            f"- appointment_summary: {json.dumps(appt_summary, ensure_ascii=False)}",
            "Return the JSON object now.",
        ]
    )

    return [
        SystemMessage(content=INTENT_ROUTER_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]
