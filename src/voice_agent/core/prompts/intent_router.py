from __future__ import annotations

import json
from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.core.prompts.utils import _enum_values
from voice_agent.core.types import CallPhase, CallState, ClinicIntent, OfficeTopic

INTENT_ROUTER_SYSTEM_PROMPT = (
    "You are a routing brain for a medical clinic voice agent.\n"
    "Your only job is to output ONE JSON object selecting the next ClinicIntent.\n"
    "Return ONLY JSON. No markdown. No prose. No extra keys.\n\n"

    "Valid ClinicIntent values:\n"
    "- book_appointment\n"
    "- reschedule\n"
    "- cancel\n"
    "- office_info\n"
    "- human_handoff\n"
    "- clarify\n"
    "- triage\n"
    "- hangup\n"
    "- check_pending\n\n"

    f"Valid OfficeTopic values: {_enum_values(OfficeTopic)}.\n\n"

    "Output schema (JSON only; keys must be exactly these):\n"
    "{\"intent\":\"<ClinicIntent>\",\"office_topics\":[],\"end_call\":false,\"confidence\":0.0}\n\n"

    "Hard rules:\n"
    "- confidence must be a float point between 0 and 1.\n"
    "- ALWAYS include office_topics as an array.\n"
    "- If intent is NOT office_info, office_topics MUST be [].\n"
    "- If intent is office_info, choose one or more OfficeTopic values.\n\n"

    "Core decision priorities (highest to lowest):\n"
    "1) If the caller describes a potential medical emergency needing 911/local emergency services -> intent=triage.\n"
    "2) If the caller clearly wants to end the call (goodbye, hang up, stop calling, etc.) -> intent=hangup and end_call=true.\n"
    "3) If there is pending context (pending_question OR pending_intent) and the caller's message is best interpreted as completing/answering it -> intent=check_pending.\n"
    "   - Examples that usually mean check_pending when something is pending: \"okay\", \"yes\", \"no\", \"correct\", \"that's right\", \"go ahead\", \"sounds good\", \"I confirm\", \"mm-hmm\".\n"
    "   - Also choose check_pending if the message provides the requested slot value (name/phone/date/time/etc.) for the pending_question.\n"
    "4) Otherwise, route by the caller's primary request:\n"
    "   - Book -> intent=book_appointment.\n"
    "   - Reschedule -> intent=reschedule.\n"
    "   - Cancel -> intent=cancel.\n"
    "   - Office details (hours, address, parking, location, insurance, etc.) -> intent=office_info and set office_topics.\n"
    "   - Out of scope -> intent=human_handoff.\n"
    "5) Use intent=clarify ONLY when there is NO pending context that explains the message and the request is genuinely unclear.\n\n"

    "Interruption rule:\n"
    "- If the caller asks for appointment actions AND office info in the same turn, prioritize the appointment action "
    "(intent=book_appointment/reschedule/cancel) and ALSO include matching office_topics. This indicates an interruption.\n"
)


def _state_value(state: CallState, key: str) -> str | None:
    return str(state.get(key) or "none")



def _intent_value(intent: ClinicIntent | str | None) -> str:
    if isinstance(intent, ClinicIntent):
        return intent.value
    return str(intent or "none")


def build_intent_router_prompt( state: CallState):
    prior_intent = _intent_value(state.get("intent"))
    pending_intent = _intent_value(state.get("pending_intent"))
    user_text = (state.get("user_text") or "").strip()
    prev_user_text = _state_value(state, "prev_user_text")
    prev_assistant_text = _state_value(state, "prev_assistant_text")

    pending_question = _state_value(state, "pending_question")
    pending_question_kind = _state_value(state, "pending_question_kind")  # optional


    appointment = state.get("appointment") or {}
    appt_summary = {
        "date": appointment.get("date"),
        "time": appointment.get("time"),
        "provider": appointment.get("provider"),
        "reason": appointment.get("reason"),
        "name": appointment.get("name"),
        "phone": appointment.get("phone"),
    }

    human_content = "\n".join(
        [
            f"Previous caller: {prev_user_text}",
            f"Previous assistant: {prev_assistant_text}",
            f"Caller now: {user_text or '[silence]'}",
            "Pending context (very important):",
            f"- pending_intent: {pending_intent}",
            f"- pending_question: {pending_question}",
            f"- pending_question_kind: {pending_question_kind}",
            f"- prior_intent: {prior_intent}",
            f"- appointment_summary: {json.dumps(appt_summary, ensure_ascii=False)}",
            "Decide intent using the priority rules. Return the JSON object now.",
        ]
    )

    return [
        SystemMessage(content=INTENT_ROUTER_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]

