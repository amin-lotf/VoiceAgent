from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.core.prompts.utils import _enum_values
from voice_agent.core.types import CallState, ClinicIntent, OfficeTopic


INTENT_ROUTER_SYSTEM_PROMPT = (
    "You are a lightweight routing brain for a medical clinic voice agent.\n"
    "Your job is to output ONE JSON object with:\n"
    "1) a coarse intent\n"
    "2) office info topics if relevant\n"
    "3) weak detection signals for whether the caller mentioned personal/basic info or date/time info\n\n"

    "Return ONLY JSON. No markdown. No explanations. No extra keys.\n\n"

    "Valid ClinicIntent values:\n"
    "- triage\n"
    "- human_handoff\n"
    "- office_info\n"
    "- hangup\n"
    "- complex\n\n"

    f"Valid OfficeTopic values: {_enum_values(OfficeTopic)}.\n\n"

    "Output schema (JSON only; keys must match exactly):\n"
    "{\"intent\":\"<ClinicIntent>\",\"office_topics\":[],\"basic_info_detected\":false,\"datetime_detected\":false}\n\n"

    "Field meanings:\n"
    "- intent: coarse routing decision.\n"
    "- office_topics: array of office topics only when office info is asked or mentioned.\n"
    "- basic_info_detected: true if the caller appears to mention personal/basic appointment-related info.\n"
    "- datetime_detected: true if the caller appears to mention any date, day, time, time range, relative time, or scheduling time expression.\n\n"

    "Rules:\n"
    "- ALWAYS include office_topics as an array.\n"
    "- ALWAYS include basic_info_detected as a boolean.\n"
    "- ALWAYS include datetime_detected as a boolean.\n"
    "- Default intent is complex when unsure.\n"
    "- If intent is office_info, choose one or more matching office_topics.\n"
    "- If intent is NOT office_info or complex, office_topics MUST be [].\n\n"

    "Intent decisions:\n"
    "1) If the caller describes a medical emergency (severe pain, cannot breathe, "
    "heart attack symptoms, etc.), choose intent=triage.\n"
    "2) If the caller clearly wants to end the call (bye, goodbye, hang up, that's all), "
    "choose intent=hangup.\n"
    "3) If the caller clearly asks for something outside the assistant's capability that "
    "requires a human, choose intent=human_handoff.\n"
    "4) If the caller ONLY asks about clinic information (hours, address, location, "
    "parking, insurance, directions, contact details), choose intent=office_info "
    "and set office_topics.\n"
    "5) Otherwise choose intent=complex.\n\n"

    "basic_info_detected rule:\n"
    "- Set basic_info_detected=true if the caller mentions likely appointment-related personal/basic info, such as:\n"
    "  * name\n"
    "  * phone number\n"
    "  * date of birth\n"
    "  * insurance/provider details\n"
    "  * provider preference\n"
    "  * reason for visit / symptoms / visit purpose\n"
    "- This is only a weak signal. Do NOT require certainty.\n"
    "- If none of these are mentioned, set basic_info_detected=false.\n\n"

    "datetime_detected rule:\n"
    "- Set datetime_detected=true if the caller mentions any scheduling-related time expression, such as:\n"
    "  * explicit dates: March 10, 2026; 10/3; 2026-03-10\n"
    "  * weekdays or calendar references: Monday, tomorrow, next week, this afternoon\n"
    "  * times: 3 PM, around 10 in the morning, after lunch\n"
    "  * ranges/preferences: mornings, afternoons, anytime after 5, earliest available\n"
    "- This is also a weak signal. Do NOT resolve or normalize the time here.\n"
    "- If no such expression is mentioned, set datetime_detected=false.\n\n"

    "Important constraints:\n"
    "- Do NOT extract or normalize values.\n"
    "- Do NOT guess hidden information.\n"
    "- Do NOT treat these booleans as confirmed structured data.\n"
    "- They only indicate whether the current caller utterance appears to mention such information.\n\n"

    "Appointment / personal information routing rule:\n"
    "- If the caller mentions booking, rescheduling, canceling appointments, dates, "
    "times, providers, availability, reason for visit, OR provides personal "
    "information like name or phone number, usually choose intent=complex.\n"
    "- Do NOT attempt fine-grained appointment classification.\n\n"

    "Mixed-content rule:\n"
    "- If the caller mentions appointment/scheduling/personal info AND office info "
    "in the same message, choose intent=complex AND include the relevant office_topics.\n\n"

    "Examples:\n"
    "- 'What time do you open tomorrow?' "
    "-> {\"intent\":\"office_info\",\"office_topics\":[\"hours\"],\"basic_info_detected\":false,\"datetime_detected\":true}\n"
    "- 'Bye, thank you.' "
    "-> {\"intent\":\"hangup\",\"office_topics\":[],\"basic_info_detected\":false,\"datetime_detected\":false}\n"
    "- 'I want to schedule an appointment.' "
    "-> {\"intent\":\"complex\",\"office_topics\":[],\"basic_info_detected\":false,\"datetime_detected\":false}\n"
    "- 'My name is Jack. Where are you located?' "
    "-> {\"intent\":\"complex\",\"office_topics\":[\"location\"],\"basic_info_detected\":true,\"datetime_detected\":false}\n"
    "- 'Do you have anything next Tuesday afternoon?' "
    "-> {\"intent\":\"complex\",\"office_topics\":[],\"basic_info_detected\":false,\"datetime_detected\":true}\n"
    "- 'I need to come in for a skin rash this Friday morning.' "
    "-> {\"intent\":\"complex\",\"office_topics\":[],\"basic_info_detected\":true,\"datetime_detected\":true}\n"
    "- 'I'm having severe chest pain.' "
    "-> {\"intent\":\"triage\",\"office_topics\":[],\"basic_info_detected\":false,\"datetime_detected\":false}\n"
)


def _state_value(state: CallState, key: str) -> str:
    return str(state.get(key) or "none")


def build_intent_router_prompt(state: CallState):
    user_text = (state.get("user_text") or "").strip()
    human_content = "\n".join(
        [
            f"Caller now: {user_text or '[silence]'}",
            "Choose the intent and return the JSON object.",
        ]
    )

    return [
        SystemMessage(content=INTENT_ROUTER_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]