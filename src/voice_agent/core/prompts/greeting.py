from langchain_core.messages import HumanMessage, SystemMessage

# System + human messages are kept in this module to keep prompt text organized.
GREETING_SYSTEM_PROMPT = (
    "You are the first-response, human-sounding front desk assistant for a medical clinic. "
    "Be concise (1-2 sentences), warm, and efficient, and do not mention that you are an AI."
)

GREETING_USER_PROMPT = (
    "Greet the caller right as the line connects. "
    "Offer help with booking, rescheduling, or canceling an appointment, and with quick office info such as hours, "
    "address, parking, or insurance. "
    "End with a short question that invites them to share what they need now."
)


def build_greeting_prompt() -> list:
    """Return the prompt messages for the opening greeting."""
    return [
        SystemMessage(content=GREETING_SYSTEM_PROMPT),
        HumanMessage(content=GREETING_USER_PROMPT),
    ]
