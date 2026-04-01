from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.types import AppointmentField


GLOBAL_OPERATOR_RULES = [
    "Write the spoken reply first, then the JSON sentinel, then one valid JSON.",
    "The spoken reply must sound natural and suitable for a phone call.",
    "Keep responses concise.",
    "Ask at most one question.",
    "Do not mention internal logic, JSON, or system behavior.",
]

CLINIC_INTENT_RULES = [
    'Allowed clinic_intent: "continue", "hangup", "human_handoff".',
    'Use "hangup" if the caller clearly ends the call.',
    'Use "human_handoff" for human requests or urgent situations.',
    'Use "continue" otherwise.',
    "Set end_call=true only when the call should end.",
]

OFFICE_INFO_RULES = [
    "If the user asks about office information, answer directly from office knowledge.",
    "Do not force the booking flow before answering office questions.",
]


REQUESTING_FIELD_RULES: dict[AppointmentField, list[str]] = {
    AppointmentField.NAME: [
        "The caller's name is still missing.",
        "Ask for the caller's name naturally.",
        "Do not ask for middle name or family name separately.",
        "Do not ask for spelling unless the name is unclear.",
        "Once the caller gives a name, extract it and stop asking for it.",
    ],
    AppointmentField.PHONE: [
        "The phone number is still missing.",
        "Ask for the phone number naturally.",
        "Do not ask for country code unless needed.",
        "Once the caller gives a phone number, extract it and stop asking for it.",
    ],
    AppointmentField.REASON_FOR_VISIT: [
        "The reason for visit is still missing.",
        "Ask for the reason for visit naturally.",
        "Do not suggest reasons.",
        "Do not turn it into multiple-choice.",
        "Accept brief answers.",
    ],
}


EXISTING_FIELD_RULES: dict[AppointmentField, list[str]] = {
    AppointmentField.NAME: [
        "Caller name already exists.",
        "Do not ask for the caller's name again unless the user explicitly corrects or changes it.",
        "If the user corrects the name, extract the new value.",
    ],
    AppointmentField.PHONE: [
        "Caller phone number already exists.",
        "Do not ask for the phone number again unless the user explicitly corrects or changes it.",
        "If the user provides a replacement phone number, extract the new value.",
    ],
    AppointmentField.REASON_FOR_VISIT: [
        "Reason for visit already exists.",
        "Do not ask for it again unless the user explicitly changes or clarifies it.",
    ],
}


PATCH_FIELD_RULES = {
    AppointmentField.NAME: [
        f"patch.name: only update if explicitly provided, else {NOT_SPECIFIED}",
    ],
    AppointmentField.PHONE: [
        f"patch.phone: only update if explicitly provided, else {NOT_SPECIFIED}",
    ],
    AppointmentField.REASON_FOR_VISIT: [
        f"patch.reason_for_visit: only update if explicitly provided, else {NOT_SPECIFIED}",
    ],
}

PATCH_NOTES_RULES = [
    "patch.notes must be a list of short strings.",
    "Use notes only for extra useful info.",
    "Do not duplicate existing fields.",
    "If nothing → empty list.",
]

JSON_RULES = [
    "Return exactly one valid JSON.",
    "No markdown or extra text.",
]