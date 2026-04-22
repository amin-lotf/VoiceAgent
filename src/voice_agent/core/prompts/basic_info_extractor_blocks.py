from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.prompts.utils import extend_prompt_section

EXTRACTOR_GLOBAL_RULES = [
    "You are an information extractor for a clinic call assistant.",
    "Extract appointment information from the active conversation context.",
    "Return only one valid JSON object.",
    "Do not write any explanation or extra text.",
    "Do not invent information.",
    f'If a value is missing or unclear, use "{NOT_SPECIFIED}".',
    "Use the most recent clear value when the caller corrects or changes information.",
]

EXTRACTOR_FIELD_RULES = [
    "Extract these fields: name, phone, reason_for_visit, requested_time_text, notes.",
    "Use the caller's latest clear value for each field.",
    "Do not keep outdated replaced values in the final fields.",
]

EXTRACTOR_NAME_RULES = [
    "Extract the caller's name if clearly provided.",
    f'If not clearly provided, use "{NOT_SPECIFIED}".',
]

EXTRACTOR_PHONE_RULES = [
    "Extract the caller's phone number if clearly provided.",
    f'If not clearly provided, use "{NOT_SPECIFIED}".',
]

EXTRACTOR_REASON_RULES = [
    "Extract the reason for visit if clearly provided.",
    "Keep it short and faithful to the caller's wording.",
    f'If not clearly provided, use "{NOT_SPECIFIED}".',
]

EXTRACTOR_REQUESTED_TIME_RULES = [
    "Extract the requested appointment day or time if clearly provided.",
    "Accept natural expressions such as tomorrow, next Monday, Friday morning, this weekend, or 3 pm.",
    "Do not validate availability.",
    f'If not clearly provided, use "{NOT_SPECIFIED}".',
]

EXTRACTOR_NOTES_RULES = [
    "Notes must be a list of short strings.",
    "Include useful extra details such as medical details, urgency, special requests, or scheduling constraints.",
    "Do not include trivial filler.",
    "If there are no useful notes, return an empty list.",
]

EXTRACTOR_AMBIGUITY_RULES = [
    "If a field is mentioned ambiguously or partially, do not guess.",
    "Only extract a field when the value is reasonably clear from the conversation.",
    f'If unclear, use "{NOT_SPECIFIED}".',
]

EXTRACTOR_CORRECTION_RULES = [
    "If the caller later corrects or replaces a field, use the latest clear value.",
    "If the caller says 'actually', 'no', 'change it', or otherwise corrects earlier information, treat the later clear value as the final value.",
    "Do not keep outdated values in the final JSON fields.",
    "Do not add corrected-out old values into notes unless they remain operationally important.",
]



def get_extractor_rules() -> list[str]:
    all_extractor_rules: list[str] = []
    extend_prompt_section(all_extractor_rules, "Extractor global", EXTRACTOR_GLOBAL_RULES)
    extend_prompt_section(all_extractor_rules, "Extractor fields", EXTRACTOR_FIELD_RULES)
    extend_prompt_section(all_extractor_rules, "Extractor corrections", EXTRACTOR_CORRECTION_RULES)
    extend_prompt_section(all_extractor_rules, "Extractor name", EXTRACTOR_NAME_RULES)
    extend_prompt_section(all_extractor_rules, "Extractor phone", EXTRACTOR_PHONE_RULES)
    extend_prompt_section(all_extractor_rules, "Extractor reason", EXTRACTOR_REASON_RULES)
    extend_prompt_section(all_extractor_rules, "Extractor requested time", EXTRACTOR_REQUESTED_TIME_RULES)
    extend_prompt_section(all_extractor_rules, "Extractor notes", EXTRACTOR_NOTES_RULES)
    return all_extractor_rules