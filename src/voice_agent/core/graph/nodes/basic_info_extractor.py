from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.graph.nodes.utils import set_node_data, normalize_value
from voice_agent.core.graph.utils import record_node_error, mark_node_succeeded
from voice_agent.core.llm.openai_llm import LLM_Non_stream
from voice_agent.core.prompts.basic_info_extractor import build_basic_info_extractor_prompt
from voice_agent.core.types import (
    CallState,
    AppointmentPatch,
    OperationStatus,
    NextAction, ErrorType,
)

logger = logging.getLogger(__name__)


def _extract_json_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()

    return str(content).strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        return json.loads(candidate)

    raise ValueError("No valid JSON object found in info extractor response")





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


def _normalize_info_patch(raw: dict[str, Any]) -> AppointmentPatch:
    return {
        "name": normalize_value(raw.get("name")),
        "phone": normalize_value(raw.get("phone")),
        "reason_for_visit": normalize_value(raw.get("reason_for_visit")),
        "requested_time_text": normalize_value(raw.get("requested_time_text")),
        "notes": _normalize_notes(raw.get("notes")),
    }


async def node_basic_info_extractor(
    state: CallState,
) -> dict[str, Any]:
    local_state: dict[str, Any] = {}
    start_time = time.perf_counter()
    end_time: float | None = None

    try:
        messages = build_basic_info_extractor_prompt(state=state)

        llm_result: AIMessage = await LLM_Non_stream.ainvoke(messages)
        end_time = time.perf_counter()

        raw_text = _extract_json_text(llm_result.content)
        parsed = _parse_json_object(raw_text)
        appointment_patch = _normalize_info_patch(parsed)

        logger.info(
            "basic_info_extractor: total generation time = %.3fs, parsed appointment_patch=%s",
            end_time - start_time,
            appointment_patch,
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'basic_info_extractor',
            }
        )

        set_node_data(
            local_state,
            "basic_info_extractor",
            {
                "appointment_patch": appointment_patch,
            },
        )

        set_node_data(
            local_state,
            "basic_info_extractor",
            {
                "total_seconds": end_time - start_time,
                "node_status": OperationStatus.SUCCESS,
            },
        )
        local_state["next_action"] = NextAction.CHECK_INFO
        mark_node_succeeded(state, local_state, "basic_info_extractor")
        return local_state

    except Exception as exc:
        set_node_data(
            local_state,
            "basic_info_extractor",
            {
                "total_seconds": None if end_time is None else end_time - start_time,
                "node_status": OperationStatus.FAILURE,
            },
        )
        local_state.update(
            record_node_error(
                state,
                node_name="basic_info_extractor",
                error_type=ErrorType.LLM_CALL,
                error_message=str(exc)
            )
        )
        local_state['next_action'] = NextAction.REPORT_ERROR
        logger.exception(
            f'Failed to extract the caller info',
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'basic_info_extractor',
            }
        )
        return local_state