from voice_agent.core.prompts.utils import extend_prompt_section

USER_INTENT_RULES = [
    'Allowed user_intent: "book_appointment", "not_specified".',
    'Use "book_appointment" only when the caller clearly says they want to make, schedule, or book a new appointment.',
    'Use "not_specified" when the caller has not clearly stated that intent in the active conversation context.',
    "Do not guess.",
    "Do not infer a booking intent just because the conversation is ongoing.",
    "If the caller asks only about office information, answer it directly and keep user_intent as not_specified unless they also clearly ask to book.",
]

INTENT_PHASE_BOUNDARY_RULES = [
    "This phase only identifies the caller's intent.",
    "Do not ask for appointment details such as name, phone number, reason for visit, or preferred time in this phase.",
    "Once booking intent is clear, give a short transition reply and wait for the next phase.",
]


REQUESTING_USER_INTENT_RULES = [
    "The caller's appointment intent is still missing.",
    "If the caller has not clearly stated their intent in the active conversation context, ask one short and natural help question.",
    'Use a neutral prompt such as "How can I help you today?" or "How can I help?"',
    "Do not proactively list supported actions unless the caller explicitly asks what you can help with.",
    "Do not assume the caller wants a new appointment unless they clearly say so.",
    "If the caller clearly states they want to book a new appointment, extract that intent and do not ask another intent question in the same response.",
    'After extracting a clear booking intent, give a short natural transition reply such as "One moment please." or "Okay, one moment please."',
]


def get_user_intent_rules():
    all_user_intent_rules = []
    extend_prompt_section(all_user_intent_rules, "User intent", USER_INTENT_RULES)
    extend_prompt_section(all_user_intent_rules, "Requesting user intent", REQUESTING_USER_INTENT_RULES)
    extend_prompt_section(all_user_intent_rules, "Intent phase boundary rules", INTENT_PHASE_BOUNDARY_RULES)
    return all_user_intent_rules