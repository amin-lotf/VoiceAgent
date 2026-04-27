from voice_agent.core.prompts.utils import extend_prompt_section

COLLECTING_INFO_PHASE_RULES = [
    "This phase is for collecting the information needed to book an appointment.",
    "The required information is: caller name, phone number, reason for visit, and requested day or time.",
    "Use the active conversation context to decide what is already available and what is still missing.",
    "Ask for only one missing item at a time.",
    "Do not ask for information that is already available in the active conversation context.",
    'If all required information appears to be available in the active conversation context, do not ask another question and set next_action to "extract_info".',
    'If any required information is still missing, set next_action to "ask_user".',
]

COLLECTING_FIELD_BASE_RULES = [
    "Collect required fields: name, phone, reason, requested time.",
    "Ask for one missing field at a time.",
    "Do not ask for a field already provided in the active conversation unless it is unclear or corrected.",
    "If a field is unclear, ask again naturally without pointing out errors.",
    "If the caller refuses to provide a field, politely explain that it is required and ask again.",
]

COLLECTING_NAME_RULES = [
    "The caller's name is required.",
    "Do not ask for middle name or family name separately.",
]

COLLECTING_PHONE_RULES = [
    "The caller's phone number is required.",
    "The provided phone number may contain letters. e.g, 'Zero one one two three O' which refers to 011230 as the phone number.",
    "consider common spoken digit words to digits (e.g., one→1, two→2, three→3, four→4, five→5, six→6, seven→7, eight→8, nine→9, zero→0).",
    "If the letter 'O' or 'o' appears in a phone-number-like sequence, treat it as '0'.",
    "Do not ask for country code unless needed.",
]

COLLECTING_REASON_FOR_VISIT_RULES = [
    "The reason for visit is required.",
    "Do not suggest reasons.",
    "Do not turn it into multiple choice.",
    "Accept brief answers.",
]

COLLECTING_REQUESTED_TIME_RULES = [
    "The requested appointment day is required.",
    "Do not suggest specific appointment times.",
    "Do not ask for an exact clock time unless the caller already starts giving one.",
    "Accept natural time phrases like tomorrow, next Monday, this weekend, morning, or afternoon.",
    "Once any usable day or time expression is available in the active conversation context, do not ask for requested time again unless the caller clearly changes it.",
    "Once any usable day or time expression is available in the active conversation context, do not ask for more specific time again unless the caller clearly changes it.",
    "Do not confirm, validate, or imply availability of the requested time.",
    "After the caller provides a time expression, respond neutrally and continue the flow.",
]

COLLECTING_INFO_ANTI_REPEAT_RULES = [
    "Do not repeat questions unless the information is missing or unclear.",
    "If the caller provides multiple details in one reply, acknowledge briefly and ask only for the next still-missing or unclear item.",
]
COLLECTING_INFO_TRANSITION_RULES = [
    'When all required information appears to be present in the active conversation context, do not ask another question',
    'Only Give a short natural transition reply',
    'If the transition replied given, and caller now is Short acknowledgements, e.g., sure, from the caller which do not require a response, then In that case, do not produce any spoken reply.',
    'In that case, set next_action to "extract_info".',
]


def get_collecting_info_rules() -> list[str]:
    all_collecting_info_rules: list[str] = []
    extend_prompt_section(all_collecting_info_rules, "Collecting info phase", COLLECTING_INFO_PHASE_RULES)
    extend_prompt_section(all_collecting_info_rules, "Collecting field base", COLLECTING_FIELD_BASE_RULES)
    extend_prompt_section(all_collecting_info_rules, "Collecting name", COLLECTING_NAME_RULES)
    extend_prompt_section(all_collecting_info_rules, "Collecting phone", COLLECTING_PHONE_RULES)
    extend_prompt_section(all_collecting_info_rules, "Collecting reason for visit", COLLECTING_REASON_FOR_VISIT_RULES)
    extend_prompt_section(all_collecting_info_rules, "Collecting requested time", COLLECTING_REQUESTED_TIME_RULES)
    extend_prompt_section(all_collecting_info_rules, "Collecting info anti repeat", COLLECTING_INFO_ANTI_REPEAT_RULES)
    extend_prompt_section(all_collecting_info_rules, "Collecting info transition", COLLECTING_INFO_TRANSITION_RULES)
    return all_collecting_info_rules
