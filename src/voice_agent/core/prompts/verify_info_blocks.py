from voice_agent.core.prompts.utils import extend_prompt_section

VERIFICATION_PHASE_RULES = [
    "This phase is for verifying the appointment information with the caller.",
    "The information to verify is: caller name, phone number, reason for visit, and requested day or time.",
    "Use the latest injected appointment information as the current record to verify.",
    "Briefly restate the appointment information in a natural confirmation question.",
    "Ask whether the information is correct.",
]

VERIFICATION_UPDATED_INFO_RULES = [
    "Updated information is internal context only.",
    "Treat any injected updated information as already applied to the appointment record before this turn begins.",
    "Use the latest injected appointment information as the current record to verify.",
    "Do not acknowledge the update itself.",
    "Do not act as if the injected update was newly said by the caller in this turn.",
    "If the caller previously requested a correction and that correction is already reflected in the updated information, treat that request as already handled.",
    'When a requested correction is already reflected in the updated information, do not choose "extract_info" again only because the caller had rejected the earlier version.',
    "In that case, simply continue by verifying the latest current record.",
]

VERIFICATION_NEXT_ACTION_RULES = [
    'Allowed next_action: "ask_user", "extract_info", "mark_verified".',
    'Use "mark_verified" only when the caller clearly confirms the information is correct.',
    'Use "extract_info" only when the caller rejects the information and also provides a correction in the same response.',
    'Use "ask_user" when the caller rejects the information but does not clearly say what should be changed, or when a clarification question is still needed.',
]

VERIFICATION_NEXT_ACTION_INTERNAL_RULES = [
    'Allowed next_action: "ask_user".',
]


VERIFICATION_CONFIRM_RULES = [
    "If the caller clearly confirms that the information is correct, do not ask another question in the same response.",
    'Give a short natural waiting reply to inform the user to wait a moment.',
    'Set next_action to "mark_verified".',
]

VERIFICATION_REJECT_WITH_CORRECTION_RULES = [
    "If the caller rejects the information and also clearly provides the correction in the same response, do not ask another question in the same response.",
    "Do not try to rewrite or normalize the corrected value in this phase.",
    "Do not argue, explain, or restate the full record again.",
    'Give a short waiting reply to inform user to wait for you to make the changes',
    'Set next_action to "extract_info".',
]

VERIFICATION_REJECT_WITHOUT_CORRECTION_RULES = [
    "If the caller rejects the information but does not clearly say what should be changed, ask one short natural   question asking what should be corrected, without repeating the user information.",
    'In that case, set next_action to "ask_user".',
]

VERIFICATION_SCOPE_RULES = [
    "Only verify these fields: caller name, phone number, reason for visit, and requested day or time.",
    "Do not invent or mention other fields that are not part of the verification.",
    "If the caller mentions changing some other information that is not part of these fields, do not hallucinate or explain unsupported field rules.",
    "Instead, respond briefly and naturally by asking what should be corrected in the appointment information, or by acknowledging and moving to extraction if the caller also provided a relevant correction.",
]

VERIFICATION_TIME_RULES = [
    "Do not confirm, validate, or imply availability of the requested time.",
    "In this phase, you are only verifying what the caller requested.",
    "Do not suggest alternative dates or times.",
]

VERIFICATION_ANTI_HALLUCINATION_RULES = [
    "Do not say that some field is not needed unless that instruction is explicitly given elsewhere.",
    "Do not invent clinic policy.",
    "Do not invent corrections that the caller did not state.",
    "If the caller's correction is unclear, ask what should be corrected.",
]


def get_verification_rules(is_internal_call: bool=False) -> list[str]:
    all_verification_rules: list[str] = []
    extend_prompt_section(all_verification_rules, "Verification phase", VERIFICATION_PHASE_RULES)
    extend_prompt_section(all_verification_rules, "Verification updated info", VERIFICATION_UPDATED_INFO_RULES)
    if is_internal_call:
        extend_prompt_section(all_verification_rules, "Verification next action internal", VERIFICATION_NEXT_ACTION_INTERNAL_RULES)
    else:
        extend_prompt_section(all_verification_rules, "Verification next action", VERIFICATION_NEXT_ACTION_RULES)
    # extend_prompt_section(all_verification_rules, "Verification reply style", VERIFICATION_REPLY_STYLE_RULES)
    extend_prompt_section(all_verification_rules, "Verification confirm", VERIFICATION_CONFIRM_RULES)
    if not is_internal_call:
        extend_prompt_section(all_verification_rules, "Verification reject with correction", VERIFICATION_REJECT_WITH_CORRECTION_RULES)
        extend_prompt_section(all_verification_rules, "Verification reject without correction", VERIFICATION_REJECT_WITHOUT_CORRECTION_RULES)
    extend_prompt_section(all_verification_rules, "Verification scope", VERIFICATION_SCOPE_RULES)
    extend_prompt_section(all_verification_rules, "Verification time", VERIFICATION_TIME_RULES)
    extend_prompt_section(all_verification_rules, "Verification anti hallucination", VERIFICATION_ANTI_HALLUCINATION_RULES)
    return all_verification_rules