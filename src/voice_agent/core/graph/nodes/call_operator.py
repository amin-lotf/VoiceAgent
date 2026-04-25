from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from langgraph.config import get_stream_writer

from voice_agent.const import JSON_SENTINEL, NOT_SPECIFIED
from voice_agent.core.graph.nodes.utils import set_node_data, get_state_data, normalize_value, is_not_specified
from voice_agent.core.graph.utils import run_non_interruptible, commit_assistant_message, record_node_error, \
    mark_node_succeeded
from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.call_operator import build_operator_prompt
from voice_agent.core.types import (
    AppointmentField,
    CallState,
    AssistantIntent, ConfirmationIntent, UserIntent, NextAction, INTERNAL_ACTIONS, AppointmentDraft, AssistantPhase,
    ErrorType,
)
from voice_agent.core.utils import estimate_speech_seconds

logger = logging.getLogger(__name__)


def _apply_requested_time_patch(
        *,
        appointment_draft: AppointmentDraft,
        requested_time_text: str,
) -> AppointmentDraft:
    updated: AppointmentDraft = dict(appointment_draft or {})
    if not is_not_specified(requested_time_text):
        updated["requested_time_text"] = requested_time_text

    return updated


def _resolve_user_intent(
        previous_intent: UserIntent,
        extracted_intent_raw: str | None,
) -> UserIntent:
    if extracted_intent_raw and extracted_intent_raw != NOT_SPECIFIED:
        try:
            return UserIntent(extracted_intent_raw)
        except Exception:
            logger.warning("Invalid extracted_intent=%s", extracted_intent_raw)
            return UserIntent.UNDECIDED
    if previous_intent and previous_intent != NOT_SPECIFIED:
        return previous_intent
    return UserIntent.UNDECIDED


async def maybe_wait_for_transition_speech(next_action: NextAction, assistant_text: str) -> None:
    if next_action not in INTERNAL_ACTIONS:
        return

    await asyncio.sleep(estimate_speech_seconds(assistant_text))


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
        local_state = commit_assistant_message(state)

    operator_data = get_state_data(state, 'call_operator')
    last_assistant_started_at = operator_data.get("last_assistant_started_at", None)
    heard_seconds = None
    if last_assistant_started_at:
        heard_seconds = time.monotonic() - last_assistant_started_at
    prompt = build_operator_prompt(state, heard_seconds=heard_seconds, internal_call=internal_call)
    set_node_data(
        local_state,
        "call_operator",
        {
            "last_assistant_started_at": None,
        }
    )
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
                                    set_node_data(
                                        local_state,
                                        "call_operator",
                                        {
                                            "last_assistant_started_at": time.monotonic(),
                                        }
                                    )
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

    except Exception as exc:
        logger.warning("call_operator failed; using fallback", exc_info=True)
        local_state .update(
            record_node_error(
                state,
                node_name="call_operator",
                error_type=ErrorType.LLM_CALL,
                error_message=str(exc)
            )
        )
        local_state['next_action'] = NextAction.REPORT_ERROR
        return local_state
    end_time = time.perf_counter()
    if first_token_time:
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
    except Exception as exc:
        logger.warning("call_operator: invalid assistant_intent=%s", assistant_intent_raw)
        local_state.update(
            record_node_error(
                local_state,
                node_name="call_operator",
                error_type=ErrorType.PARSE_ERROR,
                error_message=str(exc)
            )
        )
        local_state['next_action'] = NextAction.REPORT_ERROR
        return local_state

    next_action_raw = data.get("next_action")
    try:
        next_action = NextAction(next_action_raw)
    except Exception as exc:
        logger.warning("call_operator: invalid next_action=%s", next_action_raw)
        local_state.update(
            record_node_error(
                local_state,
                node_name="call_operator",
                error_type=ErrorType.PARSE_ERROR,
                error_message=str(exc)
            )
        )
        local_state['next_action'] = NextAction.REPORT_ERROR
        return local_state
    assistant_phase = state.get("assistant_phase")
    if assistant_phase == AssistantPhase.COLLECTING_USER_INTENT:
        user_intent_raw = normalize_value(data.get("user_intent"))
        previous_intent = state.get("user_intent") or UserIntent.UNDECIDED
        user_intent = _resolve_user_intent(previous_intent, user_intent_raw)
        local_state["user_intent"] = user_intent

    if assistant_phase == AssistantPhase.CONFIRMING_SLOT:
        requested_time_text = normalize_value(data.get("requested_time_text"))
        appointment_draft: AppointmentDraft = state.get("appointment_draft") or {}
        updated_appointment_draft = _apply_requested_time_patch(
            appointment_draft=appointment_draft,
            requested_time_text=requested_time_text
        )
        local_state["appointment_draft"] = updated_appointment_draft

    local_state["assistant_text"] = assistant_text
    local_state["assistant_intent"] = assistant_intent
    local_state["next_action"] = next_action

    set_node_data(
        local_state,
        "call_operator",
        {
            "llm_failed": False,
            "ttft_seconds": None if first_token_time is None else first_token_time - start_time,
            "total_seconds": None if end_time is None else end_time - start_time,
        },
    )
    if assistant_text.strip():
        await maybe_wait_for_transition_speech(next_action, assistant_text)

    local_state = mark_node_succeeded(local_state, "call_operator")
    return local_state
