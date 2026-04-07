from __future__ import annotations

import json
import logging
import time
from typing import Any

from langgraph.config import get_stream_writer

from voice_agent.const import  JSON_SENTINEL, NOT_SPECIFIED
from voice_agent.core.graph.nodes.utils import set_node_data
from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.call_operator import build_operator_prompt
from voice_agent.core.types import (
    AppointmentField,
    CallState,
    ClinicIntent, ConfirmationIntent,
)

logger = logging.getLogger(__name__)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes"}:
            return True
        if v in {"false", "0", "no"}:
            return False
    return default


def _normalize_patch_value(value: Any) -> str:
    if value is None:
        return NOT_SPECIFIED

    if not isinstance(value, str):
        value = str(value)

    value = value.strip()
    if not value:
        return NOT_SPECIFIED

    if value.lower() in {"none", "null", "not specified", "not_specified"}:
        return NOT_SPECIFIED

    return value


def _normalize_notes(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []

    if not isinstance(value, list):
        return []

    notes: list[str] = []
    seen: set[str] = set()

    for item in value:
        text = str(item).strip()
        if not text:
            continue
        if text in seen:
            continue
        notes.append(text)
        seen.add(text)

    return notes


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


def _normalize_patch(data: dict[str, Any]) -> dict[str, Any]:
    patch = data.get("patch") or {}
    if not isinstance(patch, dict):
        patch = {}

    return {
        AppointmentField.NAME.value: _normalize_patch_value(
            patch.get(AppointmentField.NAME.value)
        ),
        AppointmentField.PHONE.value: _normalize_patch_value(
            patch.get(AppointmentField.PHONE.value)
        ),
        AppointmentField.REASON_FOR_VISIT.value: _normalize_patch_value(
            patch.get(AppointmentField.REASON_FOR_VISIT.value)
        ),
        AppointmentField.NOTES.value: _normalize_notes(
            patch.get(AppointmentField.NOTES.value)
        ),
    }


def _fallback_state(state: CallState) -> dict[str, Any]:
    fallback = "Sorry, could you repeat that?"

    local_state: dict[str, Any] = {
        "assistant_text": fallback,
        "assistant_streamed": False,
        "clinic_intent": ClinicIntent.CONTINUE,
        "end_call": False,
        "appointment_patch": {
            AppointmentField.NAME.value: NOT_SPECIFIED,
            AppointmentField.PHONE.value: NOT_SPECIFIED,
            AppointmentField.REASON_FOR_VISIT.value: NOT_SPECIFIED,
            AppointmentField.NOTES.value: [],
        },
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
    - returns clinic_intent, end_call, appointment_patch, assistant_text
    - keeps raw/parsed LLM output in node_data
    """
    local_state: dict[str, Any] = {}

    prompt = build_operator_prompt(state)
    logger.warning(
        "=====================\ncall_operator: prompt=%s\n=====================",
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
    logger.warning("call_operator: LLM request to first token took %.2fs, total time %.2fs", first_token_time - start_time, end_time - start_time)

    full_output = "".join(full_output_parts)
    logger.warning(
        "+++++++++++++++\ncall_operator: full_output=%s\n+++++++++++++++",
        full_output,
    )

    assistant_text, data = _parse_operator_output(full_output)

    if not assistant_text:
        assistant_text = "".join(streamed_text_parts).strip()

    clinic_intent_raw = data.get("clinic_intent")
    try:
        clinic_intent = ClinicIntent(clinic_intent_raw)
    except Exception:
        logger.warning("call_operator: invalid clinic_intent=%s", clinic_intent_raw)
        clinic_intent = ClinicIntent.CONTINUE

    end_call = _coerce_bool(data.get("end_call"), default=False)
    datetime_detected = _coerce_bool(data.get("datetime_detected"), default=False)
    normalized_patch = _normalize_patch(data)
    user_text = (state.get("user_text") or "").strip()
    confirmation_intent_raw = _normalize_patch_value(data.get("confirmation_intent"))
    try:
        confirmation_intent = ConfirmationIntent(confirmation_intent_raw)
    except Exception:
        logger.warning("call_operator: invalidconfirmation_intent=%s", confirmation_intent_raw)
        confirmation_intent = ConfirmationIntent.UNCLEAR
    if datetime_detected and user_text:
        normalized_patch["requested_time_text"] = user_text

    normalized_patch["confirmation_intent"] = confirmation_intent

    local_state["assistant_text"] = assistant_text
    local_state["clinic_intent"] = clinic_intent
    local_state["end_call"] = end_call
    local_state["appointment_patch"] = normalized_patch

    set_node_data(
        local_state,
        "call_operator",
        {
            "llm_failed": False,
            "raw_output": full_output,
            "parsed": data,
            "ttft_seconds": None if first_token_time is None else first_token_time - start_time,
            "total_seconds": None if end_time is None else end_time - start_time,
        },
    )

    logger.warning(
        "call_operator: clinic_intent=%s end_call=%s appointment_patch=%s",
        clinic_intent,
        end_call,
        normalized_patch,
    )
    return local_state