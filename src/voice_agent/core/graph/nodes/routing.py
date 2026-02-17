from __future__ import annotations

import asyncio
import json
import logging

from langgraph.config import get_stream_writer

from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.intent_router import build_intent_router_prompt
from voice_agent.core.types import CallEvent, CallPhase, ClinicIntent, CallState, APPOINTMENT_INTENTS, OfficeTopic
from .utils import ensure_spoken_on_user_turn

logger = logging.getLogger(__name__)
INTENT_ROUTER_TIMEOUT_S = 4.5
FALLBACK_ASSISTANT_TEXT = "Let me connect you with a staff member."


def _clean_jsonish(text: str) -> str:
    """
    Strip code fences / surrounding prose and return the best-effort JSON substring.
    """
    t = (text or "").strip()
    if not t:
        return ""
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    l = t.find("{")
    r = t.rfind("}")
    if l != -1 and r != -1 and r > l:
        t = t[l: r + 1]
    return t.strip()


def node_route_event(state: CallState) -> CallState:
    """
    Lightweight router based on the incoming webhook event.
    Keeps state mutations minimal; downstream conditional edges handle branching.
    """
    # Clear any previous response so downstream checks use fresh text.
    state["assistant_text"] = ""
    event = state.get("event")
    if event == CallEvent.CALL_STARTED:
        state["phase"] = CallPhase.GREETING
        state["pending_question"] = None
    elif event == CallEvent.CALL_ENDED:
        state["end_call"] = True
        state["phase"] = CallPhase.DONE
    else:
        state["phase"] = CallPhase.INTENT_ROUTING
    return state


async def node_detect_intent(state: CallState) -> CallState:
    """
    LLM-based intent router. Non-streaming call with JSON output.
    """
    prompt = build_intent_router_prompt(state)

    data = {}
    llm_failed = False
    try:
        resp = await asyncio.wait_for(LLM.ainvoke(prompt), timeout=INTENT_ROUTER_TIMEOUT_S)
        cleaned = _clean_jsonish(resp.content or "")
        data = json.loads(cleaned) if cleaned else {}
    except Exception:
        logger.warning("Intent router failed; using fallback", exc_info=True)
        llm_failed = True

    intent_raw = data.get("intent")
    confidence = data.get("confidence")
    try:
        intent = ClinicIntent(intent_raw)
    except Exception:
        intent = None

    if intent is None or llm_failed:
        intent = ClinicIntent.HUMAN_HANDOFF

    office_topics_raw = data.get("office_topics", [])
    office_topics: list[OfficeTopic] = []
    if isinstance(office_topics_raw, list):
        for t in office_topics_raw:
            try:
                office_topics.append(OfficeTopic(str(t)))
            except Exception:
                continue

    state["office_topics"] = office_topics
    if office_topics and intent in APPOINTMENT_INTENTS:
        state['pending_intent'] = intent
        intent = ClinicIntent.OFFICE_INFO
    state["intent"] = intent
    state["intent_confidence"] = confidence
    return state


def node_ask_clarify_intent(state: CallState) -> CallState:
    state["assistant_text"] = (
        "I can help with booking appointments or sharing our office hours and location. "
        "What would you like to do?"
    )
    state["phase"] = CallPhase.INTENT_ROUTING
    state["pending_question"] = None
    ensure_spoken_on_user_turn(state)
    return state


def node_finalize_response(state: CallState) -> CallState:
    """
    Ensures a spoken response exists before ending a USER_TURN.
    """
    ensure_spoken_on_user_turn(state)
    state['prev_user_text'] = state.get('user_text')
    state['prev_assistant_text'] = state.get('assistant_text')
    return state
