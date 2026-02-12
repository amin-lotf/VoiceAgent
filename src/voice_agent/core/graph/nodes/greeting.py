from __future__ import annotations

from langgraph.config import get_stream_writer

from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.greeting import build_greeting_prompt
from voice_agent.core.types import CallPhase, CallState
from .utils import ensure_appointment


async def node_on_call_started(state: CallState) -> CallState:
    """Initial greeting when the call is first connected."""
    ensure_appointment(state)
    state["phase"] = CallPhase.INTENT_ROUTING
    state["pending_question"] = None
    state["intent"] = None
    prompt = build_greeting_prompt()
    writer = get_stream_writer()
    greeting_text = ""

    try:
        if writer:
            async for chunk in LLM.astream(prompt):
                token = chunk.content or ""
                if token:
                    greeting_text += token
                    writer(("assistant_token", token))
        else:
            resp = await LLM.ainvoke(prompt)
            greeting_text = (resp.content or "").strip()
    except Exception:
        # Keep the call flowing even if the LLM request fails.
        greeting_text = ""

    state["assistant_text"] = greeting_text.strip() or (
        "Hi, thanks for calling. How can I help you today? "
        "You can say things like book an appointment, reschedule, or ask about office hours."
    )
    return state
