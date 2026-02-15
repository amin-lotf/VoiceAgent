from __future__ import annotations

import asyncio
import json

from langgraph.config import get_stream_writer

from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.triage import build_triage_prompt
from voice_agent.core.types import CallEvent, CallPhase, CallState, ClinicIntent
from .utils import ensure_spoken_on_user_turn


TRIAGE_TIMEOUT_S = 4.0

def _clean_jsonish(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    # Remove fenced code blocks
    if t.startswith("```"):
        t = t.strip().strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    # Try to extract first {...} if model adds extra text
    l = t.find("{")
    r = t.rfind("}")
    if l != -1 and r != -1 and r > l:
        t = t[l:r+1]
    return t.strip()

async def node_triage_precheck(state: CallState) -> CallState:
    state["triage_triggered"] = False
    if state.get("event") != CallEvent.USER_TURN:
        return state

    user_text = (state.get("user_text") or "").strip()
    if not user_text:
        return state

    prompt = build_triage_prompt(user_text)
    decision = "safe"
    try:
        resp = await asyncio.wait_for(LLM.ainvoke(prompt), timeout=TRIAGE_TIMEOUT_S)
        cleaned = _clean_jsonish(resp.content or "")
        data = json.loads(cleaned) if cleaned else {}
        decision = str(data.get("decision", decision)).lower()
    except Exception:
        decision = "safe"

    if decision == "emergency":
        state["phase"] = CallPhase.TRIAGE
        state["pending_question"] = None
        state["triage_triggered"] = True
    return state


