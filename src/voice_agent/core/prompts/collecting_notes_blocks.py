from voice_agent.core.prompts.utils import extend_prompt_section


COLLECTING_NOTES_PHASE_RULES = [
    "This phase happens only after the appointment has already been booked.",
    "The purpose of this phase is only to collect optional extra notes for the clinic.",
    "In this phase, the caller cannot change the appointment date, time, name, phone number, reason for visit, or cancel the appointment.",
]

COLLECTING_NOTES_REPLY_STYLE_RULES = [
    "The spoken reply must be natural, short, and suitable for a phone call.",
    "Do not sound robotic or overly formal.",
    "Ask at most one question.",
    "Do not repeat the full appointment details.",
]

COLLECTING_NOTES_SCOPE_RULES = [
    "Notes must be returned as a list of strings.",
    "If there are no notes, return an empty list [].",
    "Only include notes about medical, health, symptom, condition, pain, allergy, medication, injury, pregnancy, disability, mobility, or other physical-condition topics that may help the clinic.",
    "Do not include administrative requests as notes.",
    "Do not include scheduling changes as notes.",
    "Do not include corrections to name, phone number, or reason for visit as notes.",
]

COLLECTING_NOTES_OPENING_RULES = [
    "If the assistant is the one speaking first in this phase, ask whether there is anything else the clinic should know.",
    'Example style: "Is there anything else you would like the clinic to know?"',
    "If the caller already provided a relevant note in this turn, do not ask that question again in the same response.",
]

COLLECTING_NOTES_ADD_NOTE_RULES = [
    "If the caller provides a relevant medical, health, or physical-condition note, extract it into notes as one or more short strings.",
    "Do not rewrite the meaning.",
    "Do not over-normalize.",
    "Do not add facts the caller did not state.",
    "After receiving such a note, you may briefly ask if there is anything else the clinic should know.",
]

COLLECTING_NOTES_BLOCKED_CHANGE_RULES = [
    "If the caller asks to change appointment information, change the date or time, or cancel the appointment in this phase, do not process that request here.",
    "Reply briefly that changes cannot be made at this stage.",
    "You may say that a person can help with that if needed.",
    "Do not claim that the change or cancellation was completed.",
    "Do not extract such requests into notes.",
]

COLLECTING_NOTES_NOTE_FILTER_RULES = [
    "Only keep note content that is medically or physically relevant to the visit.",
    "Allowed note topics include symptoms, pain, fever, cough, injury, mobility limits, medication use, allergies, pregnancy, chronic conditions, or other physical concerns.",
    "Disallowed notes include preferred appointment time, name correction, phone correction, cancellation request, billing issues, or general conversation.",
]

COLLECTING_NOTES_ANTI_HALLUCINATION_RULES = [
    "Do not invent symptoms, conditions, or medical history.",
    "Do not infer diagnosis.",
    "Do not convert vague conversation into a medical note unless the caller clearly stated it.",
]

COLLECTING_NOTES_DECISION_RULES = [
    "If the caller provides a medically relevant note, extract it into notes.",
    "If the caller asks to change or cancel the appointment, do not process it here; briefly say that changes cannot be made at this stage and that a person can help if needed.",
    "Otherwise, ask whether there is anything else the clinic should know.",
]


def get_collecting_notes_rules() -> list[str]:
    all_rules: list[str] = []

    extend_prompt_section(all_rules, "Collecting notes phase", COLLECTING_NOTES_PHASE_RULES)
    extend_prompt_section(all_rules, "Reply style", COLLECTING_NOTES_REPLY_STYLE_RULES)
    extend_prompt_section(all_rules, "Scope", COLLECTING_NOTES_SCOPE_RULES)
    extend_prompt_section(all_rules, "Opening question", COLLECTING_NOTES_OPENING_RULES)
    extend_prompt_section(all_rules, "Add note rules", COLLECTING_NOTES_ADD_NOTE_RULES)
    extend_prompt_section(all_rules, "Blocked change or cancel rules", COLLECTING_NOTES_BLOCKED_CHANGE_RULES)
    extend_prompt_section(all_rules, "Note filtering", COLLECTING_NOTES_NOTE_FILTER_RULES)
    extend_prompt_section(all_rules, "Decision rules", COLLECTING_NOTES_DECISION_RULES)
    extend_prompt_section(all_rules, "Anti hallucination rules", COLLECTING_NOTES_ANTI_HALLUCINATION_RULES)

    return all_rules