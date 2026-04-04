from langchain_core.messages import SystemMessage, HumanMessage
from voice_agent.const import JSON_SENTINEL
from voice_agent.core.prompts.operator_blocks import *
from voice_agent.core.types import CallState


def _format_messages(messages: list[dict]) -> str:
    if not messages:
        return "none"

    lines: list[str] = []
    for m in messages:
        role = (m.get("role") or "unknown").strip()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")

    return "\n".join(lines) if lines else "none"


def _get_recent_messages(state: CallState, limit: int = 8) -> list[dict]:
    messages = state.get("messages") or []
    if not isinstance(messages, list):
        return []
    return messages[-limit:]


def build_operator_prompt(state):
    node_data = state.get("node_data") or {}

    directive_prompts = node_data.get("directive_prompt_builder", {}).get("rules", [])
    office_knowledge = node_data.get("office_info", {}).get("knowledge", {})

    appointment = state.get("appointment_draft") or {}
    user_text = state.get("user_text") or ""
    recent_messages = _get_recent_messages(state, limit=8)

    output_schema = {
        "clinic_intent": "continue",
        "end_call": False,
        "patch": {
            "name": NOT_SPECIFIED,
            "phone": NOT_SPECIFIED,
            "reason_for_visit": NOT_SPECIFIED,
            "notes": [],
        },
        "datetime_detected": False,
    }

    all_rules = [
        *GLOBAL_OPERATOR_RULES,
        *CLINIC_INTENT_RULES,
        *DATETIME_RULES,
        *OFFICE_INFO_RULES,
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
Recent message history:
{_format_messages(recent_messages)}

Caller Now: {user_text}

Current draft:
{appointment}
""".strip()

    return [
        SystemMessage(content=system),
        HumanMessage(content=human),
    ]