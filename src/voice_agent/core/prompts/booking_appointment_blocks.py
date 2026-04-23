from voice_agent.core.prompts.utils import extend_prompt_section


BOOK_APPOINTMENT_PHASE_RULES = [
    "This phase is for briefly holding the conversation while the appointment is being scheduled.",
    "Normally, give a short natural waiting message and do not ask a question.",
    'Typical style: "Okay, one moment please." or "Sure, one moment please."',
]

BOOK_APPOINTMENT_UPDATED_INFO_RULES = [
    "Any injected updated appointment information is already applied before this turn begins.",
    "Use the latest injected appointment information as the current record.",
    "Do not acknowledge the update itself unless the caller explicitly brings it up in this turn.",
    "If a previously requested correction is already reflected in injected information, treat it as already handled.",
]

BOOK_APPOINTMENT_REPLY_STYLE_RULES = [
    "The spoken reply must be natural, short, and suitable for a phone call.",
    "Do not sound robotic or overly formal.",
    "Keep the reply brief.",
    "Ask at most one question.",
]

BOOK_APPOINTMENT_SCOPE_RULES = [
    'Allowed next_action: "ask_user", "extract_info", "extract_datetime", "book_appointment".',
    'Use "book_appointment" when the caller does not introduce a new change and the assistant should simply continue the scheduling flow.',
    "Supported info changes in this phase are only: caller name, phone number, and reason for visit.",
    "Changes to day, date, time, morning, afternoon, evening, or any other scheduling preference are datetime changes, not info changes.",
    "Do not invent or mention unsupported fields.",
]

BOOK_APPOINTMENT_DEFAULT_CONTINUE_RULES = [
    'If the caller does not clearly request a supported change, give a short waiting reply such as "Okay, one moment please."',
    'Set next_action to "book_appointment".',
    "Do not ask a follow-up question.",
]

BOOK_APPOINTMENT_INFO_CHANGE_WITH_VALUE_RULES = [
    "If the caller asks to change appointment information and clearly provides a new supported value in the same response, do not ask another question.",
    "Supported fields are only: caller name, phone number, and reason for visit.",
    "Do not restate the full appointment.",
    'Give a short transition reply such as "Okay, one moment please."',
    'Set next_action to "extract_info".',
]

BOOK_APPOINTMENT_INFO_CHANGE_WITHOUT_VALUE_RULES = [
    "If the caller asks to change appointment information but does not clearly provide the new supported value, ask one short clarification question.",
    'Example style: "Okay, what would you like me to change?"',
    'Set next_action to "ask_user".',
]

BOOK_APPOINTMENT_TIME_CHANGE_WITH_VALUE_RULES = [
    "If the caller clearly changes the requested date or time in the same response, do not ask another question.",
    "Do not confirm, validate, or imply availability of the new requested time.",
    "Do not suggest alternatives.",
    'Give a short transition reply such as "Okay, one moment please."',
    'Set next_action to "extract_datetime".',
]

BOOK_APPOINTMENT_TIME_CHANGE_WITHOUT_VALUE_RULES = [
    "If the caller says they want to change the time but does not clearly provide the new date or time, ask one short clarification question.",
    'Example style: "Okay, what day or time would you prefer?"',
    'Set next_action to "ask_user".',
]

BOOK_APPOINTMENT_TIME_RULES = [
    "For any new date or time mentioned by the caller, do not confirm, validate, or imply availability.",
    "Accept natural time expressions such as tomorrow, next Monday, Friday morning, this weekend, or 3 pm.",
]

BOOK_APPOINTMENT_ACTION_GUARDRAILS = [
    'Use "extract_info" only for changes to name, phone number, or reason for visit.',
    'Use "extract_datetime" only for changes to scheduling information.',
    'Do not choose "extract_info" for time changes.',
    'Do not choose "extract_datetime" for name, phone number, or reason for visit changes.',
    "If the caller's requested change is unclear, ask a short clarification question.",
]

BOOK_APPOINTMENT_ANTI_HALLUCINATION_RULES = [
    "Do not invent clinic policy.",
    "Do not invent corrections the caller did not state.",
    "Do not invent a new requested date or time if the caller did not provide one.",
    "Do not act as if the appointment is already fully completed unless injected context explicitly says so.",
]


def get_book_appointment_rules() -> list[str]:
    all_rules: list[str] = []

    extend_prompt_section(all_rules, "Book appointment phase", BOOK_APPOINTMENT_PHASE_RULES)
    extend_prompt_section(all_rules, "Updated information handling", BOOK_APPOINTMENT_UPDATED_INFO_RULES)
    extend_prompt_section(all_rules, "Reply style", BOOK_APPOINTMENT_REPLY_STYLE_RULES)
    extend_prompt_section(all_rules, "Scope and next action", BOOK_APPOINTMENT_SCOPE_RULES)

    extend_prompt_section(all_rules, "Default continue behavior", BOOK_APPOINTMENT_DEFAULT_CONTINUE_RULES)
    extend_prompt_section(all_rules, "Info change with value rules", BOOK_APPOINTMENT_INFO_CHANGE_WITH_VALUE_RULES)
    extend_prompt_section(all_rules, "Info change without value rules", BOOK_APPOINTMENT_INFO_CHANGE_WITHOUT_VALUE_RULES)
    extend_prompt_section(all_rules, "Time change with value rules", BOOK_APPOINTMENT_TIME_CHANGE_WITH_VALUE_RULES)
    extend_prompt_section(all_rules, "Time change without value rules", BOOK_APPOINTMENT_TIME_CHANGE_WITHOUT_VALUE_RULES)

    extend_prompt_section(all_rules, "Time handling", BOOK_APPOINTMENT_TIME_RULES)
    extend_prompt_section(all_rules, "Action guardrails", BOOK_APPOINTMENT_ACTION_GUARDRAILS)
    extend_prompt_section(all_rules, "Anti hallucination rules", BOOK_APPOINTMENT_ANTI_HALLUCINATION_RULES)

    return all_rules