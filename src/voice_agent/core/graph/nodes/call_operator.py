from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any

from langgraph.config import get_stream_writer

from voice_agent.const import DEFAULT_TZ
from voice_agent.core.graph.nodes.utils import set_node_data
from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.call_operator import (
    JSON_SENTINEL,
    build_call_operator_prompt,
)
from voice_agent.core.types import CallState, ClinicIntent, UserIntent

logger = logging.getLogger(__name__)

NOT_SPECIFIED = "not_specified"


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
    """
    Normalize model patch values so downstream merge logic can rely on one sentinel.
    """
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


async def node_call_operator(state: CallState) -> dict:
    """
    Single OpenAI operator node:
    - streams assistant text first
    - captures JSON tail after sentinel
    - returns clinic_intent + user_intent + appointment_patch + assistant_text
    """
    local_state: dict[str, Any] = {}

    prompt = build_call_operator_prompt(
        state=state,
        now=datetime.now(DEFAULT_TZ),
    )
    logger.warning("=====================\ncall_operator: prompt=%s\n=============================", prompt)
    writer = get_stream_writer()
    streamed_text_parts: list[str] = []
    full_output_parts: list[str] = []

    sentinel_seen = False
    tail_buffer = ""

    t0 = time.perf_counter()

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
                        # Keep a suffix buffer so we don't accidentally stream part of the sentinel.
                        safe_prefix_len = max(0, len(tail_buffer) - len(JSON_SENTINEL))
                        if safe_prefix_len > 0:
                            speakable = tail_buffer[:safe_prefix_len]
                            if speakable:
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
        fallback = "Sorry, could you repeat that?"
        local_state["assistant_text"] = fallback
        local_state["assistant_streamed"] = False
        local_state["clinic_intent"] = ClinicIntent.CONTINUE
        local_state["user_intent"] = state.get("user_intent") or UserIntent.UNDECIDED
        local_state["end_call"] = False
        local_state["appointment_patch"] = {
            "name": NOT_SPECIFIED,
            "phone": NOT_SPECIFIED,
            "reason_for_visit": NOT_SPECIFIED,
            "requested_time_text": NOT_SPECIFIED,
        }

        set_node_data(
            local_state,
            "call_operator",
            {
                "llm_failed": True,
                "raw_output": "",
                "parsed": {},
                "datetime_detected": False,
            },
        )
        return local_state

    t1 = time.perf_counter()
    logger.warning(f"call_operator: LLM request took {t1 - t0:0.2f}s")

    full_output = "".join(full_output_parts)
    logger.warning(f"+++++++++++++++\ncall_operator: full_output={full_output}\n++++++++++++++++++++")
    assistant_text, data = _parse_operator_output(full_output)

    if not assistant_text:
        assistant_text = "".join(streamed_text_parts).strip()

    clinic_intent_raw = data.get("clinic_intent")
    try:
        clinic_intent = ClinicIntent(clinic_intent_raw)
    except Exception:
        logger.warning(f"call_operator: invalid clinic_intent={clinic_intent_raw}")
        clinic_intent = ClinicIntent.CONTINUE

    user_intent_raw = data.get("user_intent")
    try:
        user_intent = UserIntent(user_intent_raw)
    except Exception:
        logger.warning(f"call_operator: invalid user_intent={user_intent_raw}")
        current_user_intent = state.get("user_intent")
        try:
            user_intent = UserIntent(current_user_intent)
        except Exception:
            user_intent = UserIntent.UNDECIDED

    end_call = _coerce_bool(data.get("end_call"), default=False)

    patch = data.get("patch") or {}
    if not isinstance(patch, dict):
        patch = {}

    normalized_patch = {
        "name": _normalize_patch_value(patch.get("name")),
        "phone": _normalize_patch_value(patch.get("phone")),
        "reason_for_visit": _normalize_patch_value(patch.get("reason_for_visit")),
        "requested_time_text": _normalize_patch_value(patch.get("requested_time_text")),
    }

    datetime_detected = _coerce_bool(data.get("datetime_detected"), default=False)

    local_state["assistant_text"] = assistant_text
    local_state["clinic_intent"] = clinic_intent
    local_state["user_intent"] = user_intent
    local_state["end_call"] = end_call
    local_state["appointment_patch"] = normalized_patch

    set_node_data(
        local_state,
        "call_operator",
        {
            "llm_failed": False,
            "raw_output": full_output,
            "parsed": data,
            "datetime_detected": datetime_detected,
        },
    )

    logger.warning(
        "call_operator: clinic_intent=%s user_intent=%s end_call=%s",
        clinic_intent,
        user_intent,
        end_call,
    )
    return local_state