from __future__ import annotations

import json
from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.core.types import CallPhase, CallState, ClinicIntent


INTENT_ROUTER_SYSTEM_PROMPT = (
    "You are a routing brain for a medical clinic voice agent. "
    "Your only job is to choose (1) ClinicIntent and (2) CallPhase for the next step. "
    "Return ONLY a single JSON object. No markdown. No prose. No extra keys.\n\n"

    "Valid ClinicIntent values: "
    "book_appointment, reschedule, cancel, new_patient, existing_patient, "
    "insurance_question, pricing_question, office_info, urgent_symptom, human_handoff.\n"
    "Valid CallPhase values: "
    "greeting, intent_routing, slot_fill, confirm, tool_execution, triage, handoff, done.\n\n"

    "Decision rules (pick the best match):\n"
    "- If the caller reports urgent or life-threatening symptoms (e.g., chest pain, trouble breathing, "
    "severe bleeding, stroke signs, suicidal intent) -> intent=urgent_symptom, phase=triage.\n"
    "- If the caller wants to BOOK an appointment -> intent=book_appointment, phase=slot_fill.\n"
    "- If the caller wants to RESCHEDULE an existing appointment -> intent=reschedule, phase=slot_fill.\n"
    "- If the caller wants to CANCEL an appointment -> intent=cancel, phase=slot_fill.\n"
    "- If the caller asks if they are a new or existing patient, or says they are new -> "
    "intent=new_patient or existing_patient, phase=slot_fill.\n"
    "- If the caller asks about insurance coverage, network, copay, eligibility -> "
    "intent=insurance_question, phase=handoff.\n"
    "- If the caller asks about prices/fees/cost estimates -> intent=pricing_question, phase=handoff.\n"
    "- If the caller asks about clinic hours, address, location, parking -> intent=office_info, phase=intent_routing.\n"
    "- If the caller's request is unclear -> phase=intent_routing (NOT handoff) and set confidence<=0.4.\n"
    "- Use intent=human_handoff, phase=handoff only when the request is clearly outside scope.\n\n"

    "Output schema (JSON only; keys must be exactly these): "
    "{\"intent\":\"<ClinicIntent>\",\"phase\":\"<CallPhase>\",\"end_call\":false,\"confidence\":0.0}\n"
    "Always include confidence between 0 and 1."
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
    phase = _phase_value(state.get("phase"))
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
            f"- current_phase: {phase}",
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
