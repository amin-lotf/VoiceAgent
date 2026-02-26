from __future__ import annotations

import logging
import time

from langgraph.config import get_stream_writer

from voice_agent.core.llm.huggingface_llm import chat_model
from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.greeting_huggingface import build_greeting_prompt
from voice_agent.core.types import CallPhase, CallState

logger = logging.getLogger(__name__)

async def node_on_call_started(state: CallState) -> CallState:
    """Initial greeting when the call is first connected."""
    state["phase"] = CallPhase.INTENT_ROUTING
    state["pending_question"] = None
    state["intent"] = None
    prompt = build_greeting_prompt()
    writer = get_stream_writer()
    greeting_text = ""

    import asyncio

    try:
        if writer:
            # Run blocking HF generation off the event loop
            start_time = time.perf_counter()
            resp = await asyncio.to_thread(chat_model.invoke, prompt)
            end_time = time.perf_counter()
            greeting_text = (resp.content or "").strip()
            logger.warning(f"time = {end_time - start_time:0.2f}: greeting LLM raw=%s", greeting_text)
            # "Fake stream" it to your UI so it doesn't feel dead
            for token in greeting_text.split(" "):
                t = token + " "
                writer(("assistant_token", t))
            state["assistant_streamed"] = True
        else:
            resp = await asyncio.to_thread(chat_model.invoke, prompt)
            greeting_text = (resp.content or "").strip()
    except Exception:
        logger.warning("Greeting LLM request failed", exc_info=True)
        greeting_text = ""

    state["assistant_text"] = greeting_text.strip() or (
        "Hi, thanks for calling. How can I help you today? "
    )
    return state
