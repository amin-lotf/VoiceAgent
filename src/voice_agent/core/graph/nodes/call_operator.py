from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from langgraph.config import get_stream_writer

from voice_agent.const import JSON_SENTINEL, NOT_SPECIFIED
from voice_agent.core.graph.nodes.utils import set_node_data
from voice_agent.core.graph.utils import run_non_interruptible, commit_assistant_message
from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.call_operator import build_operator_prompt
from voice_agent.core.types import (
    AppointmentField,
    CallState,
    AssistantIntent, ConfirmationIntent, UserIntent, NextAction,
)

logger = logging.getLogger(__name__)






def _parse_operator_output(full_text: str) -> tuple[str, dict[str, Any]]:
    """
    Expected format:
      <assistant text>
      <<JSON>>
      {...}
    """
    full_text = (full_text or "").strip()
    if not full_text:
        return "", {}

    if JSON_SENTINEL not in full_text:
        return full_text.strip(), {}

    spoken_part, json_part = full_text.split(JSON_SENTINEL, 1)
    assistant_text = spoken_part.strip()
    json_text = json_part.strip()

    if not json_text:
        return assistant_text, {}

    try:
        data = json.loads(json_text)
        if isinstance(data, dict):
            return assistant_text, data
    except Exception:
        logger.warning("Failed to parse operator JSON tail", exc_info=True)

    return assistant_text, {}

def _fallback_state(state: CallState) -> dict[str, Any]:
    fallback = "Sorry, there was an error. Please Wait for the operator to connect you."

    local_state: dict[str, Any] = {
        "assistant_text": fallback,
        "assistant_streamed": False,
        "assistant_intent": AssistantIntent.HUMAN_HANDOFF,

    }
    set_node_data(
        local_state,
        "call_operator",
        {
            "llm_failed": True,
            "raw_output": "",
            "parsed": {},
        },
    )
    return local_state




async def node_call_operator(state: CallState) -> dict[str, Any]:
    """
    Simplified operator node:
    - streams spoken assistant text first
    - parses JSON after sentinel
    - returns assistant_intent, end_call, appointment_patch, assistant_text
    - keeps raw/parsed LLM output in node_data
    """
    local_state: dict[str, Any] = {}
    internal_call = state.get("internal_call") or False
    if internal_call:
        local_state= commit_assistant_message(state)
    prompt = build_operator_prompt(state, internal_call=internal_call)
    logger.warning(
        f"=====================\ncall_operator for internal_call={internal_call}: prompt=%s\n=====================",
        prompt,
    )

    writer = get_stream_writer()
    streamed_text_parts: list[str] = []
    full_output_parts: list[str] = []

    sentinel_seen = False
    tail_buffer = ""

    is_first_token = True
    start_time = time.perf_counter()
    first_token_time: float | None = None
    end_time: float | None = None
    try:
        # await run_non_interruptible(state, lambda: asyncio.sleep(10))
        if writer:
            async for chunk in LLM.astream(prompt):
                token = chunk.content or ""
                if not token:
                    continue

                full_output_parts.append(token)
                tail_buffer += token

                if not sentinel_seen:
                    idx = tail_buffer.find(JSON_SENTINEL)
                    if idx == -1:
                        safe_prefix_len = max(0, len(tail_buffer) - len(JSON_SENTINEL))
                        if safe_prefix_len > 0:
                            speakable = tail_buffer[:safe_prefix_len]
                            if speakable:
                                if is_first_token:
                                    first_token_time = time.perf_counter()
                                    is_first_token = False

                                streamed_text_parts.append(speakable)
                                writer(("assistant_token", speakable))
                            tail_buffer = tail_buffer[safe_prefix_len:]
                    else:
                        before = tail_buffer[:idx]
                        if before:
                            streamed_text_parts.append(before)
                            writer(("assistant_token", before))
                        tail_buffer = tail_buffer[idx:]
                        sentinel_seen = True

            local_state["assistant_streamed"] = True

        else:
            resp = await LLM.ainvoke(prompt)
            content = resp.content or ""
            full_output_parts.append(content)
            local_state["assistant_streamed"] = False

    except Exception:
        logger.warning("call_operator failed; using fallback", exc_info=True)
        return _fallback_state(state)
    end_time = time.perf_counter()
    logger.warning("call_operator: LLM request to first token took %.2fs, total time %.2fs",
                   first_token_time - start_time, end_time - start_time)

    full_output = "".join(full_output_parts)
    logger.warning(
        "+++++++++++++++\ncall_operator: full_output=%s\n+++++++++++++++",
        full_output,
    )

    assistant_text, data = _parse_operator_output(full_output)

    if not assistant_text:
        assistant_text = "".join(streamed_text_parts).strip()

    assistant_intent_raw = data.get("assistant_intent")
    try:
        assistant_intent = AssistantIntent(assistant_intent_raw)
    except Exception:
        logger.warning("call_operator: invalid assistant_intent=%s", assistant_intent_raw)
        assistant_intent = AssistantIntent.CONTINUE

    next_action_raw = data.get("next_action")
    try:
        next_action = NextAction(next_action_raw)
    except Exception:
        logger.warning("call_operator: invalid next_action=%s", next_action_raw)
        next_action = NextAction.REPORT_ERROR




    local_state["assistant_text"] = assistant_text
    local_state["assistant_intent"] = assistant_intent
    local_state["next_action"] = next_action

    set_node_data(
        local_state,
        "call_operator",
        {
            "llm_failed": False,
            "raw_output": full_output,
            "operator_output": data,
            "ttft_seconds": None if first_token_time is None else first_token_time - start_time,
            "total_seconds": None if end_time is None else end_time - start_time,
        },
    )

    logger.warning(
        f"call_operator: output={data}",
    )
    return local_state
