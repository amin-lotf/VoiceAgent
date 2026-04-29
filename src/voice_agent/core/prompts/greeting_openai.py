from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.core.prompts.global_blocks import AGENT_IDENTITY
from voice_agent.core.prompts.utils import extend_prompt_section


GREETING_SYSTEM_PROMPT = [
    "You are the first-response, human-sounding front desk assistant. ",
    "Be concise (1 sentence only), warm, and efficient.",
    "Use normal sentence case and plain ASCII punctuation only.",
    "Do not use stylized punctuation or symbols.",
]

GREETING_USER_PROMPT = (
    "Greet the caller right as the line connects."
    "Use the clinic's name."
    "End with a short question that invites them to share what they need now."
)


def build_greeting_prompt() -> list:
    """Return the prompt messages for the opening greeting."""
    all_rules = []
    extend_prompt_section(all_rules, "Global operator", GREETING_SYSTEM_PROMPT)



    system = f"""
    You are a   call assistant.
    
    Clinic_information
    {AGENT_IDENTITY}

    Rules:
    {chr(10).join("- " + r for r in all_rules)}
    """




    return [
        SystemMessage(content=system),
        HumanMessage(content=GREETING_USER_PROMPT),
    ]
