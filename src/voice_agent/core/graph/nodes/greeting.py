from __future__ import annotations

import logging
import time

from langgraph.config import get_stream_writer

from voice_agent.core.graph.nodes.utils import stream_text_response
from voice_agent.core.llm.huggingface_llm import agent_model, gen_pipe, model, llm
from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.greeting_huggingface import build_greeting_prompt
from voice_agent.core.types import CallPhase, CallState

logger = logging.getLogger(__name__)

async def node_on_call_started(state: CallState) -> dict:
    """Initial greeting when the call is first connected."""

    local_state:dict= {
        "phase": CallPhase.INTENT_ROUTING,
        "pending_question": None,
        "intent": None
    }

    prompt = build_greeting_prompt()
    greeting_text = ""

    import asyncio

    try:
        start_time = time.perf_counter()
        resp = await asyncio.to_thread(agent_model.invoke, prompt)
        end_time = time.perf_counter()
        greeting_text = (resp.content or "").strip()
        logger.warning(f"time = {end_time - start_time:0.2f}: greeting LLM raw=%s", greeting_text)

    except Exception:
        logger.warning("Greeting LLM request failed", exc_info=True)
        greeting_text = ""

    greeting_text= greeting_text.strip() or (
        "Hi, thanks for calling. How can I help you today? "
    )
    resp = stream_text_response(greeting_text)
    local_state.update(resp)
    return local_state
