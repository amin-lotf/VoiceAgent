from voice_agent.core.graph.nodes.utils import ensure_spoken_on_user_turn
from voice_agent.core.types import CallState


def _append_message(messages: list[dict], role: str, content: str, limit: int = 10) -> list[dict]:
    if not content:
        return messages

    messages = messages or []
    messages.append({
        "role": role,
        "content": content.strip()
    })

    # keep last N messages only
    return messages[-limit:]


def node_finalize_response(state: CallState) -> dict:
    """
    Finalizes turn:
    - ensures assistant_text exists
    - appends user + assistant messages
    - updates prev_* fields
    """
    local_state: dict = {'assistant_text': state.get('assistant_text') or ''}
    local_state.update(ensure_spoken_on_user_turn(state))

    user_text = (state.get("user_text") or "").strip()
    assistant_text = (local_state.get("assistant_text") or "").strip()

    messages = state.get("messages") or []

    # append user message
    if user_text:
        messages = _append_message(messages, "user", user_text)

    # append assistant message
    if assistant_text:
        messages = _append_message(messages, "assistant", assistant_text)

    local_state["messages"] = messages

    # update prev fields (used in prompt)
    local_state["prev_user_text"] = user_text
    local_state["prev_assistant_text"] = assistant_text

    return local_state