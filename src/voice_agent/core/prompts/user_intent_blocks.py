from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.prompts.utils import extend_prompt_section
from voice_agent.core.types import UserIntent

INTENT_PHASE_BOUNDARY_RULES = [
    "This phase only identifies the caller's intent.",
    "Do not ask for appointment details such as name, phone number, reason for visit, or preferred time in this phase.",
    "Once booking intent is clear, give a short transition reply and set next_action to process_intent.",
]

REQUESTING_USER_INTENT_RULES = [
    "The caller's appointment intent is still missing.",
    "If the caller has not clearly stated their intent in the active conversation context, ask one short and natural help question.",
    'Use a neutral prompt such as "How can I help you today?" or "How can I help?"',
    "Do not proactively list supported actions unless the caller explicitly asks what you can help with.",
    "Do not assume the caller wants a new appointment unless they clearly say so.",
    "If the caller clearly states they want to book a new appointment, extract that intent and do not ask another intent question in the same response.",
    'After extracting a clear booking intent, give a short natural transition reply.',
]

NEXT_ACTION_RULES = [
    'Allowed next_action values: "ask_user", "process_intent".',
    'Use "ask_user" when the caller intent is still missing or unclear.',
    'Use "ask_user" when user_intent is "{not_specified}".',
    'Use "process_intent" only when user_intent is a clear supported intent such as booking an appointment.',
    'When next_action is "process_intent", do not ask another question.',
    'When next_action is "process_intent", the spoken reply should only be a short transition."',
]


def _build_next_action_rules() -> list[str]:
    return [
        'Allowed next_action values: "ask_user", "process_intent".',
        f'Use "ask_user" when user_intent is "{NOT_SPECIFIED}" or the caller intent is unclear.',
        f'Use "process_intent" only when user_intent is not "{NOT_SPECIFIED}".',
        'When next_action is "ask_user", ask one short natural intent question if needed.',
        'When next_action is "process_intent", do not ask another question.',
        'When next_action is "process_intent", the spoken reply should only be a short transition."',
        'If the transition replied given, and caller now is Short acknowledgements, e.g., sure, from the caller which do not require a response, then In that case, do not produce any spoken reply.',
        'In that case, set next_action to "process_intent".',
    ]


def _build_user_intent_rules() -> list[str]:
    allowed_values = ", ".join(f'"{i.value}"' for i in UserIntent)

    return [
        f'Allowed user_intent values: {allowed_values}.',
        f'Use "{UserIntent.BOOK_APPOINTMENT.value}" only when the caller clearly says they want to make, schedule, or book a new appointment.',
        f'Use "{NOT_SPECIFIED}" when the caller has not clearly stated that intent in the active conversation context.',
        "Do not guess.",
        "Do not infer a booking intent just because the conversation is ongoing.",
        f'If the caller asks only about office information, answer directly and keep user_intent as "{NOT_SPECIFIED}" unless they explicitly request booking.',
    ]


def get_user_intent_rules() -> list[str]:
    all_user_intent_rules: list[str] = []

    extend_prompt_section(
        all_user_intent_rules,
        "User intent",
        _build_user_intent_rules(),
    )

    extend_prompt_section(
        all_user_intent_rules,
        "Next action",
        _build_next_action_rules(),
    )

    extend_prompt_section(
        all_user_intent_rules,
        "Requesting user intent",
        REQUESTING_USER_INTENT_RULES,
    )

    extend_prompt_section(
        all_user_intent_rules,
        "Intent phase boundary rules",
        INTENT_PHASE_BOUNDARY_RULES,
    )

    return all_user_intent_rules
