from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.types import AppointmentField,  ConfirmationTopic, ConfirmationIntent






INTERNAL_CALL_RULES = [
    "This is an internal follow-up turn with no new caller message.",
    "Continue directly from the previous exchange.",
    "Do not greet, say hi, thank the caller, or say goodbye unless a current closing rule explicitly requires it.",
    "Do not repeat the previous assistant sentence verbatim.",
    "If the current directives require a question, ask it directly now.",
    "Do not add filler such as 'One moment please.' before a required question.",
]

PRE_BOOKING_NO_QUESTION_RULES = [
    "If no question is authorized by the current rules, do not ask one.",
    "Instead, give one brief transition reply while the call flow continues.",
    "Keep it to a single short sentence.",
    "Examples: 'One moment please.' 'Let me check that for you.'",
    "Do not close the conversation in this case.",
]

POST_BOOKING_NO_QUESTION_RULES = [
    "If no question is authorized by the current rules, do not ask one.",
    "If the appointment has just been confirmed or booked in the immediately previous assistant turn, do not repeat the booking details unless a current rule explicitly tells you to restate them.",
    "Do not restate the date, time, or caller name if they were already stated in the recent assistant message.",
    "Do not announce the booking again with phrases like 'All set. Your appointment is booked...' if that was already said in the recent context.",
    "After booking, only say the minimum needed for the current step.",
    "If another directive still requires a question and Caller Now does not already answer it, ask only that question and nothing else.",
    "If no further action is needed, give a short closing reply instead of repeating the appointment summary.",
    "Examples:  'If there's nothing else, we look forward to seeing you then.' 'Take care, goodbye.'",
]

POST_BOOKING_CLOSING_RULES = [
    "Use this only when the appointment is complete, no required field is missing, no further directive requires a question, and the caller indicates there is nothing else to add.",
    "Give a brief, warm closing reply suitable for a phone call.",
    "Do not repeat the booking summary unless a current rule explicitly requires it.",
    "Do not ask another question.",
    "Prefer natural closings such as 'Alright, you're all set. We look forward to seeing you then. Goodbye.'",
    "Other acceptable styles: 'Okay, that's everything. Thanks for calling, goodbye.' or 'Perfect, you're all set. Take care, goodbye.'",
]


CONFIRMATION_INTENT_RULES = [
    f'Allowed confirmation_intent: "{ConfirmationIntent.ACCEPT}", "{ConfirmationIntent.REJECT}", "{ConfirmationIntent.UNCLEAR}", "{ConfirmationIntent.NOT_SPECIFIED}".',
    f'Set confirmation_intent to "{ConfirmationIntent.NOT_SPECIFIED}" when there is no active confirmation request in the current turn.',
    f'Set confirmation_intent to "{ConfirmationIntent.ACCEPT}" only when the caller clearly accepts, agrees, confirms, or says the offered option works.',
    f'Set confirmation_intent to "{ConfirmationIntent.REJECT}" only when the caller clearly rejects, declines, says it does not work, or asks for another option.',
    f'Set confirmation_intent to "{ConfirmationIntent.UNCLEAR}" when the caller responds to the confirmation request but the meaning is ambiguous, incomplete, or cannot be classified as accept or reject.',
    "Use only the latest caller message.",
    "Do not infer confirmation from silence or from unrelated polite phrases.",
    "If the caller rejects and also provides a replacement date or time, still set confirmation_intent to reject.",
]



DATETIME_RULES = [
    'Set "datetime_detected" to true only if the caller explicitly mentions a date or time expression for scheduling in Caller Now.',
    'Set "datetime_detected" to false otherwise.',
    'Set "datetime_detected" to false if the current assistant response is a question asking about the date or time.',
    'Use only the latest caller message.',
    'Count expressions like "today", "tomorrow", "next Monday", "April 12", "morning", "afternoon", "evening", "at 3", and "3 pm" as datetime mentions.',
    'Do not mark true for non-scheduling numbers such as phone numbers, addresses, or ages.',
    'Do not infer missing time information from context,  Recent message history,  or earlier turns.',
]



REQUESTING_FIELD_RULES: dict[AppointmentField, list[str]] = {
    AppointmentField.NAME: [
        "The caller's name is still missing.",
        "Ask for the caller's name naturally if the caller has not provided it yet in the current text.",
        "Do not ask for middle name or family name separately.",
        "Do not ask for spelling unless the name is unclear.",
        "Once the caller gives a name, extract it and stop asking for it.",
        "If caller denied to provide the name, politely remind them that it's required and ask to provide it.",
    ],
    AppointmentField.PHONE: [
        "The phone number is still missing.",
        "Ask for the phone number naturally if the caller has not provided it yet in the current text.",
        "Do not ask for country code unless needed.",
        "Once the caller gives a phone number, extract it and stop asking for it.",
        "If caller denied to provide the phone number, politely remind them that it's required and ask  to provide it.",
    ],
    AppointmentField.REASON_FOR_VISIT: [
        "The reason for visit is still missing.",
        "Ask for the reason for visit naturally if the caller has not provided it yet in the current text.",
        "Do not suggest reasons.",
        "Do not turn it into multiple-choice.",
        "Accept brief answers.",
        "if the caller denies to provide the reason set reason_for_visit='Personal reasons'."
    ],
    AppointmentField.NOTES: [
        "Ask whether the caller wants anything noted for the appointment.",
        "Ask naturally and briefly.",
        "Do not pressure the caller to add notes.",
        "Accept short answers.",
        "If the caller says there is nothing to add, acknowledge briefly and do not ask another question in the same turn.",
        "Do not end the call with a plain acknowledgment only.",
        "If the caller provides an answer to be noted without further instruction, ask for continuation, e.g., 'Anything else you'd like to note?'",
        "If Caller Now changes the appointment date or time instead of giving a note, stop note collection for this turn.",
        "In that case, do not ask any note question or note follow-up question; switch back to scheduling with a short neutral reply such as 'Let me check that for you.'",
    ],
    AppointmentField.REQUESTED_TIME_TEXT: [
        "The requested appointment time is still missing.",
        "Ask which day the caller wants only if the current text includes no day or time expression.",
        "Do not suggest specific times or ask for an exact clock time unless the caller already gives one.",
        "Accept natural time phrases like 'tomorrow', 'next Monday', 'this weekend', or 'morning'.",
        "If the caller provides any day or time expression, extract it and stop asking for requested time.",
        "Do not confirm, validate, or imply availability of the requested time.",
        "After the caller provides a time expression, respond neutrally, for example by saying you will check availability.",
    ]
}

EXISTING_FIELD_RULES: dict[AppointmentField, list[str]] = {
    AppointmentField.NAME: [
        "Caller name already exists.",
        "Do not ask for the caller's name again unless the user explicitly corrects or changes it.",
        "If the user corrects the name, extract the new value.",
        "If the caller changes this information, acknowledge briefly (e.g., 'One moment while I update that for you.') and do not ask any question in the same turn.",
    ],
    AppointmentField.PHONE: [
        "Caller phone number already exists.",
        "Do not ask for the phone number again unless the user explicitly corrects or changes it.",
        "If the user provides a replacement phone number, extract the new value.",
        "If the caller changes this information, acknowledge briefly.",
    ],
    AppointmentField.REASON_FOR_VISIT: [
        "Reason for visit already exists.",
        "Do not ask for it again unless the user explicitly changes or clarifies it.",
        "If the caller changes this information, acknowledge briefly.",
    ],
    AppointmentField.REQUESTED_TIME_TEXT: [
        "Requested appointment time already exists.",
        "Do not ask for the day or time again unless the caller explicitly changes it.",
        "If the caller provides a new date or time, extract and replace the existing value.",
        "If the caller changes this information, acknowledge briefly (e.g., 'One moment while I check availability.') and do not ask any question in the same turn.",
        "When the caller changes the appointment time, do not continue any earlier notes question or other post-booking follow-up in that same turn.",
    ],
}

CLARIFYING_FIELD_RULES: dict[AppointmentField, list[str]] = {
    AppointmentField.REQUESTED_TIME_TEXT: [
        "The caller mentioned a date or time, but it is still too unclear to use.",
        "Ask the caller to be a bit more specific about the requested day or time.",
        "Ask exactly one short clarifying question.",
        "Do not suggest a specific appointment slot.",
        "Do not offer availability.",
        "Do not confirm or imply that the requested time is available.",
        "Prefer asking for whichever part is missing or unclear, such as the day, part of day, or exact time.",
        "Accept natural clarifications like 'tomorrow morning', 'Friday afternoon', or 'around 3 PM'.",
        "If the caller provides a clearer day or time expression, extract it and stop asking follow-up questions in the same turn.",
        "After the caller provides a clearer time expression, respond neutrally, for example: 'One moment while I check that for you.'",
        "Do not say phrases like 'that works', 'perfect', 'okay', or anything that sounds like the time is confirmed.",
        "If the caller is still vague, ask for a narrower time naturally, such as 'morning or afternoon?' or 'which day works best?' depending on what is missing.",
    ],
}


CONFIRMATION_RULES: dict[ConfirmationTopic, list[str]] = {
    ConfirmationTopic.HOLD_CONFIRMATION: [
    "Ask whether the offered date and time works only if the caller has not confirmed, rejected, or requested a change in this turn.",
    "Do not ask open-ended scheduling questions unless the caller has rejected the offered slot.",
    "If the caller rejects or requests a change without giving a new date or time, ask what would work better and set datetime_detected to false.",
    "If the caller provides a replacement date or time, extract it and do not ask another question in the same turn.",
    "If a replacement date or time is provided, do not confirm, validate, or imply availability.",
    "Do not propose or suggest a new slot unless that exact slot has already been confirmed available by the system.",
    "If a replacement date is provided, respond with a neutral transition such as 'Got it. One moment while I check that for you.'",
    "Do not say phrases implying availability before it is verified.",
    "If the caller accepts the offered slot, do not restate availability.",
    "Do not mention that the slot is held or reserved.",
]
}

# INFORMATIVE_DIRECTIVE_RULES: dict[DirectiveKind, list[str]] = {
#     DirectiveKind.INFORM_SCHEDULED: [
#         "Tell the caller that the appointment is successfully booked.",
#         "If the caller's name is available, say it is booked under that name.",
#         "Keep the wording natural and suitable for a phone call.",
#         "Do not say the appointment is pending, being checked, or being finalized.",
#         "Do not reopen with availability language such as 'There's a slot available' once the caller has already accepted a slot.",
#         "If the latest caller turn was a simple acceptance of the offered slot, prefer a brief booking-progress acknowledgment such as 'Perfect, I'll book that for you now.'",
#         "Do not say lines like '<date and time> works.' after the caller accepts a slot.",
#         "If you mention the booked slot, phrase it as 'You're booked for ...' or 'I have you booked for ...'.",
#         "If another current directive requires one follow-up question, ask it only after the booking-progress line or brief booking update.",
#         "If another current directive requires one follow-up question, use exactly one short booking sentence before that question.",
#         "Do not repeat the same date and time twice in one turn unless a current rule explicitly requires it.",
#         "Do not ask for required booking fields again.",
#         "If another current directive requires one follow-up question, give the booking update first and then ask that single question in the same turn.",
#     ],
#     DirectiveKind.INFORM_HELD: [
#         "Do not say the slot is held, reserved, blocked, or temporarily booked.",
#         "Do not say the appointment is already booked.",
#         "Keep the wording short and natural.",
#     ],
# }






PATCH_FIELD_RULES = {
    AppointmentField.NAME: [
        f"patch.name: only update if explicitly provided in Caller Now, else {NOT_SPECIFIED}",
    ],
    AppointmentField.PHONE: [
        f"patch.phone: only update if explicitly provided in Caller Now, else {NOT_SPECIFIED}",
    ],
    AppointmentField.REASON_FOR_VISIT: [
        f"patch.reason_for_visit: only update if explicitly provided in Caller Now, else {NOT_SPECIFIED}",
    ],
    AppointmentField.NOTES: [
        "patch.notes must be a list of short strings.",
        "Use notes only for extra useful info.",
        "Do not duplicate existing fields.",
        "If nothing → empty list.",
    ]
}


