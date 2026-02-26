from langchain_core.messages import HumanMessage, SystemMessage


GREETING_SYSTEM_PROMPT = (
    "You are the first-response front desk assistant for a medical clinic. "
    "Sound human, warm, and efficient. 1 sentence, max 25 words. "
    "Do NOT mention you are an AI. "
    "Do NOT invent clinic details (hours, address, parking, insurance). "
    "If details are not provided, do not state them; instead offer to share them if asked. "
    "Ask ONE short question at the end."
)

GREETING_USER_PROMPT = (
    "Create the opening greeting for an inbound call. "
    "but do not give any specifics unless provided. "
    "End with one short question."
)

def build_greeting_prompt() -> list:
    return [
        SystemMessage(content=GREETING_SYSTEM_PROMPT),
        HumanMessage(content=GREETING_USER_PROMPT),
    ]