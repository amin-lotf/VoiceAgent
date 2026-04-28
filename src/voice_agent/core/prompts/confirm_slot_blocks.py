from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.prompts.utils import extend_prompt_section

SLOT_CONFIRMATION_PHASE_RULES = [
    "This phase is only for confirming the offered appointment slot or handling a caller-requested change.",
    "The offered slot is provided in injected context.",
    "You may say this offered slot is available because it was already selected by the system.",
    "Use the offered slot as the current slot being discussed.",
]

SLOT_CONFIRMATION_REQUESTED_TIME_TEXT_RULES = [
    "Output requested_time_text only when next_action is \"extract_datetime\".",
    "requested_time_text must be the caller's final requested scheduling preference.",
    f"If the caller's final requested scheduling preference is already shown  in the appointment information and is not being changed, set requested_time_text  = {NOT_SPECIFIED}.",
    "Use the active conversation context to combine partial time answers when needed.",
    "Example: if the caller first says \"morning\" and later says \"tomorrow\", output \"tomorrow morning\".",
    "Accept natural expressions such as tomorrow, next Monday, Friday morning, this weekend, or 3 pm.",
    "Do not validate availability.",
    "Do not invent a date or time the caller did not provide.",
    f'If next_action is not "extract_datetime", use "{NOT_SPECIFIED}".',
    f'If the requested time is not clearly provided, use "{NOT_SPECIFIED}".',
]

SLOT_CONFIRMATION_UPDATED_INFO_RULES = [
    "Any injected updated appointment information is already applied before this turn begins.",
    "Use the latest injected appointment information as the current record.",
    "Do not acknowledge the update itself.",
    "If a previously requested correction is already reflected in the injected information, treat it as already handled.",
]



SLOT_CONFIRMATION_SCOPE_RULES = [
    'Allowed next_action: "ask_user", "extract_info", "extract_datetime", "book_appointment".',
    "Supported info changes in this phase are only: caller name, phone number, and reason for visit.",
    "Changes to day, date, time, morning, afternoon, evening, or any other scheduling preference are datetime changes, not info changes.",
    "Do not invent or mention unsupported fields.",
]

SLOT_CONFIRMATION_SCOPE_INTERNAL_RULES = [
    'You must say this offered slot is available',
    'Allowed next_action: "ask_user"',
    f'Allow requested_time_text:  "{NOT_SPECIFIED}".',
]

SLOT_CONFIRMATION_TIME_RULES = [
    "For any new date or time mentioned by the caller, do not confirm, validate, or imply availability.",
    "Do not suggest alternative dates or times unless the caller rejected the offered slot without giving a new time and you are asking what works better.",
    "Accept natural time expressions such as tomorrow, next Monday, Friday morning, this weekend, or 3 pm.",
]

SLOT_CONFIRMATION_DECISION_RULES = [
    'If you clearly offered the slot in the active conversation and the caller clearly accepts the offered slot, give a short waiting reply to let user wait for finalizing the appointment and set next_action to "book_appointment". Do not ask another question.',
    'If the caller rejects the offered slot and clearly provides a new requested date or time in the same response, give a short transition reply such as "Okay, one moment please." and set next_action to "extract_datetime". Do not ask another question.',
    'If the caller gives a short acknowledgement such as "sure" after a transition reply, continue the same internal action only if Caller Now contains that acknowledgement. Do not apply this rule when Caller Now is "none".',
    'In that case, set next_action to "extract_datetime".',
     "If the caller's final requested   date or time is already shown  in the appointment information and is not being changed, do not output set next_action to 'extract_datetime'.",
    'If the caller rejects the offered slot but does not clearly provide a new requested date or time, ask one short follow-up question about what day or time works better and set next_action to "ask_user".',
    'If the caller asks to change appointment information and clearly provides a new supported value in the same response, give a short transition reply such as "Okay, one moment please." and set next_action to "extract_info". Do not ask another question.',
    'If the transition replied given, and caller now is Short acknowledgements, e.g., sure, from the caller which do not require a response, then In that case, do not produce any spoken reply.',
    'In that case, set next_action to "extract_info".',
    'If the caller asks to change appointment information but does not clearly provide the new value, ask one short follow-up question and set next_action to "ask_user".',
]
SLOT_CONFIRMATION_INTERNAL_CALL_RULES = [
    'If Caller Now is "none", this is an internal continuation, not a caller acceptance.',
    'Do not treat Caller Now "none" as yes, sure, okay, or any other confirmation.',
    'If there is a held appointment that has not been clearly accepted by the caller, offer the held appointment and ask whether it works.',
    'When asking the caller to confirm the held appointment, set next_action to "ask_user".',
    'Use "book_appointment" only when you clearly asked whether the offered slots works and  then caller explicitly accepts it in the active conversation.',
]

SLOT_CONFIRMATION_ACTION_GUARDRAILS = [
    'Use "extract_info" only for changes to name, phone number, or reason for visit.',
    'Use "extract_datetime" only for changes to scheduling information.',
    'Do not choose "extract_info" for time changes.',
    'Do not choose "extract_datetime" for name, phone number, or reason for visit changes.',
    "If the caller's requested change is unclear, ask a short clarification question.",
]

SLOT_CONFIRMATION_ANTI_HALLUCINATION_RULES = [
    "Do not invent clinic policy.",
    "Do not invent corrections the caller did not state.",
    "Do not invent a new requested date or time if the caller did not provide one.",
]

SLOT_CONFIRMATION_OPENING_RULES = [
    "When first offering the slot  or the slot has updated and changed, inform the caller   that this slot is available and ask whether it works for them.",
]


def get_slot_confirmation_rules(is_internal_call: bool=False) -> list[str]:
    all_rules: list[str] = []

    extend_prompt_section(all_rules, "Slot confirmation phase", SLOT_CONFIRMATION_PHASE_RULES)
    extend_prompt_section(all_rules, "Updated information handling", SLOT_CONFIRMATION_UPDATED_INFO_RULES)
    extend_prompt_section(all_rules, "Opening the slot confirmation", SLOT_CONFIRMATION_OPENING_RULES)

    extend_prompt_section(all_rules, "Anti hallucination rules", SLOT_CONFIRMATION_ANTI_HALLUCINATION_RULES)
    if is_internal_call:
        extend_prompt_section(all_rules, "Scope and next action", SLOT_CONFIRMATION_SCOPE_INTERNAL_RULES)
    if not is_internal_call:
        extend_prompt_section(all_rules, "Scope and next action", SLOT_CONFIRMATION_SCOPE_RULES)
        extend_prompt_section(all_rules, "Time handling", SLOT_CONFIRMATION_TIME_RULES)
        extend_prompt_section(all_rules, "Decision rules", SLOT_CONFIRMATION_DECISION_RULES)
        extend_prompt_section(all_rules,"Requested time text",SLOT_CONFIRMATION_REQUESTED_TIME_TEXT_RULES,)
        extend_prompt_section(all_rules, "Action guardrails", SLOT_CONFIRMATION_ACTION_GUARDRAILS)
    extend_prompt_section(all_rules,"Internal call rules",SLOT_CONFIRMATION_INTERNAL_CALL_RULES,)
    return all_rules
