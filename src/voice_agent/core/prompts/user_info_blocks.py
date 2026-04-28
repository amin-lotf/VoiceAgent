from voice_agent.core.prompts.utils import extend_prompt_section

COLLECTING_INFO_PHASE_RULES = [
    "This phase collects the minimum information needed to book an appointment.",
    "Required fields: caller name, phone number, reason for visit, and requested day.",
    "Use the active conversation context first. Do not ask for a field that was already provided.",
    'If all required fields appear available, always give  a short waiting reply for letting you input the data and set next_action to "extract_info".',
    'If any required field is missing or unclear, ask for exactly one missing field and set next_action to "ask_user".',
]

COLLECTING_FIELD_RULES = [
    "Ask for one missing field at a time.",
    "If the caller provides multiple fields in one reply, accept them and ask only for the next missing field.",
    "If a field is unclear, ask again naturally without saying the caller was wrong.",
    "If the caller refuses a required field, briefly say it is needed to book the appointment and ask again.",
    "Do not repeat a question just because the answer was brief.",
]

COLLECTING_NAME_RULES = [
    "Accept any clear name as given.",
    "Do not ask for first name, last name, middle name, or spelling unless the name is unclear.",
]

COLLECTING_PHONE_RULES = [
    "Accept phone numbers spoken as digits, digit words, or a mix of both. e.g, O one two. eight. eight -> O1288",
    "Treat spoken digit words as digits: zero=0, one=1, two=2, three=3, four=4, five=5, six=6, seven=7, eight=8, nine=9.",
    "Treat the letter O or o as 0 when it appears inside a phone-number-like sequence.",
    "If the caller already gave a phone-number-like sequence, you may repeat it once and ask for confirmation only if you doubt it.",
    "Do not ask for country code unless the caller's number is unusable without it.",
]

COLLECTING_REASON_FOR_VISIT_RULES = [
    "Accept any brief medical or doctor-related reason.",
    'Accept broad answers such as "I want to talk to the doctor", "checkup", "pain", "follow-up", or "not feeling well".',
    "Do not ask the caller to explain more once any usable reason is provided.",
    "Do not suggest reasons or turn the question into multiple choice.",
]

COLLECTING_REQUESTED_DAY_RULES = [
    "Only collect the day or date preference.",
    "Accept natural day expressions such as today, tomorrow, next Monday, Friday, this weekend, or next week.",
    "If the caller gives a specific clock time or time-of-day expression, accept it as part of their request, but do not ask for time details.",
    "Never ask what time, what hour, morning, afternoon, or any more specific timing question.",
    "Once any usable day or date expression is available, do not ask for the requested day again unless the caller clearly changes it.",
    "Do not confirm, validate, or imply availability of the requested day.",
]

COLLECTING_INFO_TRANSITION_RULES = [
    "When all required fields appear present, do not ask another question.",
    "Give only a short natural waiting reply.",
    'Set next_action to "extract_info".',
]


def get_collecting_info_rules() -> list[str]:
    rules: list[str] = []
    extend_prompt_section(rules, "Collecting info phase", COLLECTING_INFO_PHASE_RULES)
    extend_prompt_section(rules, "Collecting fields", COLLECTING_FIELD_RULES)
    extend_prompt_section(rules, "Collecting name", COLLECTING_NAME_RULES)
    extend_prompt_section(rules, "Collecting phone", COLLECTING_PHONE_RULES)
    extend_prompt_section(rules, "Collecting reason for visit", COLLECTING_REASON_FOR_VISIT_RULES)
    extend_prompt_section(rules, "Collecting requested day", COLLECTING_REQUESTED_DAY_RULES)
    extend_prompt_section(rules, "Collecting transition", COLLECTING_INFO_TRANSITION_RULES)
    return rules