from langchain_core.messages import SystemMessage, HumanMessage
from voice_agent.const import JSON_SENTINEL
from voice_agent.core.prompts.operator_blocks import *


def build_operator_prompt(state):
    node_data = state.get("node_data") or {}

    directive_prompts = node_data.get("directive_prompt_builder", {}).get("rules", [])
    office_knowledge = node_data.get("office_info", {}).get("knowledge", {})

    appointment = state.get("appointment_draft") or {}
    user_text = state.get("user_text") or ""

    output_schema = {
        "clinic_intent": "continue",
        "end_call": False,
        "patch": {
            "name": NOT_SPECIFIED,
            "phone": NOT_SPECIFIED,
            "reason_for_visit": NOT_SPECIFIED,
            "notes": [],
        },
    }

    all_rules = [
        *GLOBAL_OPERATOR_RULES,
        *CLINIC_INTENT_RULES,
        *OFFICE_INFO_RULES,
        *PATCH_NOTES_RULES,
        *directive_prompts,
        *JSON_RULES,
    ]

    for field_rules in PATCH_FIELD_RULES.values():
        all_rules.extend(field_rules)

    system = f"""
You are a clinic call assistant.

Rules:
{chr(10).join("- " + r for r in all_rules)}

Office knowledge:
{office_knowledge}

Output schema:
{output_schema}

Format:
Reply text first.
Then {JSON_SENTINEL}
Then JSON.
""".strip()

    human = f"""
Caller: {user_text}

Current draft:
{appointment}
""".strip()

    return [
        SystemMessage(content=system),
        HumanMessage(content=human),
    ]