from __future__ import annotations

import logging
import time
from typing import Any

from langgraph.config import get_stream_writer

from voice_agent.core.graph.nodes.utils import set_node_data
from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.greeting_openai import build_greeting_prompt
from voice_agent.core.types import CallPhase, CallState

logger = logging.getLogger(__name__)


async def node_on_call_started(state: CallState) -> dict[str, Any]:
    """Initial greeting when the call is first connected."""
    local_state: dict[str, Any] = {
        "phase": CallPhase.INTENT_ROUTING,
        "pending_question": None,
        "intent": None,
    }

    prompt = build_greeting_prompt()
    writer = get_stream_writer()

    greeting_parts: list[str] = []
    is_first_token = True
    start_time = time.perf_counter()
    first_token_time: float | None = None
    end_time: float | None = None

    try:
        async for chunk in LLM.astream(prompt):
            token = chunk.content or ""
            if not token:
                continue

            if is_first_token:
                first_token_time = time.perf_counter()
                is_first_token = False
                logger.warning(
                    "greeting: time to first token = %.3fs",
                    first_token_time - start_time,
                )

            greeting_parts.append(token)

            if writer:
                writer(("assistant_token", token))

        end_time = time.perf_counter()
        greeting_text = "".join(greeting_parts).strip()

        logger.warning(
            "greeting: total generation time = %.3fs, text=%s",
            end_time - start_time,
            greeting_text,
        )

    except Exception:
        logger.warning("Greeting OpenAI streaming request failed", exc_info=True)
        greeting_text = ""

    greeting_text = greeting_text or "Hi, thanks for calling. How can I help you today?"

    local_state.update(
        {
            "assistant_text": greeting_text,
            "assistant_streamed": True,
        }
    )

    set_node_data(
        local_state,
        "on_call_started",
        {
            "ttft_seconds": None if first_token_time is None else first_token_time - start_time,
            "total_seconds": None if end_time is None else end_time - start_time,
            "used_fallback": not bool(greeting_parts),
        },
    )

    return local_state