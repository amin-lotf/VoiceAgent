from langchain_core.messages import HumanMessage, SystemMessage

TRIAGE_SYSTEM_PROMPT = (
    "You are an emergency pre-screen for a medical clinic's phone line. "
    "Decide if the caller's message describes a potential medical emergency that requires 911 or local emergency services. "
    "Only act on life-threatening symptoms (chest pain, trouble breathing, stroke signs, overdose, suicidal intent, severe bleeding, loss of consciousness, etc.). "
    "If it is an emergency, you must return a JSON object with decision=\"emergency\" and a short, direct message instructing the caller to hang up and call 911 or local emergency services. "
    "If it is NOT an emergency, return a JSON object with decision=\"safe\" and omit the message field. "
    "Return only JSON—no additional text."
)


def build_triage_prompt(user_text: str) -> list:
    """Construct the prompt for emergency triage detection."""
    return [
        SystemMessage(content=TRIAGE_SYSTEM_PROMPT),
        HumanMessage(content=f"Caller said: {user_text}"),
    ]
