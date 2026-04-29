from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage
from zoneinfo import ZoneInfo

from voice_agent.const import DEFAULT_TZ, NOT_SPECIFIED
from voice_agent.core.graph.nodes.utils import set_node_data, get_state_data, normalize_value
from voice_agent.core.graph.utils import record_node_error
from voice_agent.core.llm.openai_llm import LLM, LLM_Non_stream
from voice_agent.core.prompts.datetime_extractor import build_time_resolution_prompt
from voice_agent.core.types import CallState, AppointmentDraft, OperationStatus, NextAction, AssistantPhase, ErrorType

logger = logging.getLogger(__name__)


def _is_not_specified(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in {
        "",
        "not_specified",
        str(NOT_SPECIFIED).lower(),
    }:
        return True
    return False


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


def _parse_json_object(state,text: str) -> dict[str, Any]:
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start: end + 1]
        return json.loads(candidate)
    raise ValueError("No valid JSON object found in datetime extractor response")


def _normalize_schedule_patch(raw: dict[str, Any]) -> dict[str, str]:
    patch = raw.get("schedule_patch") or {}

    def _get_str(key: str) -> str:
        value = patch.get(key, NOT_SPECIFIED)
        if value is None:
            return str(NOT_SPECIFIED)
        return str(value).strip() or str(NOT_SPECIFIED)

    return {
        "date_mode": _get_str("date_mode"),
        "date_key": _get_str("date_key"),
        "time_pref": _get_str("time_pref"),
        "exact_time_text": _get_str("exact_time_text"),
        "relative_to_offered": _get_str("relative_to_offered"),
    }


async def node_datetime_extractor(
        state: CallState,
) -> dict[str, Any]:
    next_action = state.get('next_action')
    local_state = {}
    if next_action not in (NextAction.EXTRACT_DATETIME,NextAction.RETRY_ACTION):
        if next_action==NextAction.BOOK_APPOINTMENT:
            local_state = {
                'assistant_phase': AssistantPhase.BOOKING_APPOINTMENT,
                'messages': []
            }
        logger.info(
            f"Offered time is approved by the caller",
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'datetime_extractor',

            }
        )
        return local_state

    appointment: AppointmentDraft = dict(state.get("appointment_draft") or {})
    requested_time_text = (appointment.get("requested_time_text") or "").strip()
    tz_info: ZoneInfo = DEFAULT_TZ
    now = datetime.now(tz_info)

    messages = build_time_resolution_prompt(
        state=state,
        now=now,
        tz_info=tz_info,
    )
    logger.info(
        f"Processing requested time: {requested_time_text}",
        extra={
            'call_id': state.get('call_id'),
            'phase': state.get('assistant_phase'),
            'node': 'datetime_extractor',

        }
    )
    start_time = time.perf_counter()
    end_time: float | None = None
    local_state = {}
    try:
        # Preferred: model configured for JSON object output
        llm_result: AIMessage = await LLM_Non_stream.ainvoke(messages)
        end_time = time.perf_counter()
        raw_text = _extract_json_text(llm_result.content)
        parsed = _parse_json_object(state,raw_text)
        schedule_patch = _normalize_schedule_patch(parsed)

        logger.debug(
            f"Total generation time: {end_time - start_time}",
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'datetime_extractor',

            }
        )

        set_node_data(
            local_state,
            'datetime_extractor',
            {
                "schedule_patch": schedule_patch
            }
        )

        set_node_data(
            local_state,
            "datetime_extractor",
            {
                "total_seconds": None if end_time is None else end_time - start_time,
                "node_status": OperationStatus.SUCCESS
            },
        )
        local_state['next_action'] = NextAction.HOLD_APPOINTMENT
        logger.info(
            f"Parsed schedule_patch: {schedule_patch}",
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'datetime_extractor',

            }
        )
        return local_state

    except Exception as exc:
        set_node_data(
            local_state,
            'datetime_extractor',
            {
                "total_seconds": None if end_time is None else end_time - start_time,
                "node_status": OperationStatus.FAILURE
            }
        )
        local_state.update(
            record_node_error(
                state,
                node_name="datetime_extractor",
                error_type=ErrorType.LLM_CALL,
                error_message=str(exc)
            )
        )
        local_state['next_action'] = NextAction.REPORT_ERROR
        logger.exception(
            f"Failed to parse operator JSON {str(exc)[:100]}",
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'datetime_extractor',

            }
        )
        return local_state