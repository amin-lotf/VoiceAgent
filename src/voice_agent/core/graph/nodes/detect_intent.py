from __future__ import annotations

import asyncio
import logging
import time

from voice_agent.core.graph.const import MAX_INFO_TIME_MENTIONS
from voice_agent.core.graph.nodes.utils import safe_json_parse, set_node_data
from voice_agent.core.prompts.intent_router import build_intent_router_prompt
from voice_agent.core.types import CallState, ClinicIntent, OfficeTopic

logger = logging.getLogger(__name__)




def _append_unique(items: list[dict], entry: dict, limit: int = MAX_INFO_TIME_MENTIONS) -> list[dict]:
    if not items:
        return [entry]

    last = items[-1]
    if last.get("turn_text") == entry.get("turn_text"):
        return items[-limit:]

    items.append(entry)
    return items[-limit:]


async def node_detect_intent(state: CallState) -> dict:
    """
    LLM-based intent router. Non-streaming call with JSON output.
    """
    local_state: dict = {}
    prompt = build_intent_router_prompt(state)
    user_text = (state.get("user_text") or "").strip()

    data = {}
    llm_failed = False

    try:
        t0 = time.perf_counter()
        # resp = await asyncio.to_thread(agent_model.invoke, prompt)
        resp = None
        t1 = time.perf_counter()
        logger.warning(f"intent_router: LLM request took {t1 - t0:0.2f}s")
        data = safe_json_parse(resp.content or "", logger=logger)
    except Exception:
        logger.warning("Intent router failed; using fallback", exc_info=True)
        llm_failed = True

    intent_raw = data.get("intent")
    logger.warning(f"intent_raw: intent={intent_raw}")
    try:
        intent = ClinicIntent(intent_raw)
    except Exception:
        logger.warning(f"intent_router: invalid intent={intent_raw}")
        intent = None

    if intent is None or llm_failed:
        intent = ClinicIntent.COMPLEX

    office_topics_raw = data.get("office_topics", [])
    office_topics: list[OfficeTopic] = []
    if isinstance(office_topics_raw, list):
        for t in office_topics_raw:
            try:
                office_topics.append(OfficeTopic(str(t)))
            except Exception:
                continue

    basic_info_detected = bool(data.get("basic_info_detected", False))
    datetime_detected = bool(data.get("datetime_detected", False))

    existing = (((state.get("node_data") or {}).get("detect_intent")) or {})
    basic_info_mentions = list(existing.get("basic_info_mentions") or [])
    datetime_mentions = list(existing.get("datetime_mentions") or [])
    prev_assistant_text = state.get("prev_assistant_text") or ''
    if user_text and basic_info_detected:
        basic_info_mentions = _append_unique(
            basic_info_mentions,
            {"turn_text": user_text,'prev_assistant_text':prev_assistant_text},
        )

    if user_text and datetime_detected:

        datetime_mentions = _append_unique(
            datetime_mentions,
            {"turn_text": user_text,'prev_assistant_text':prev_assistant_text},
        )

    set_node_data(
        local_state,
        "detect_intent",
        {
            "office_topics": office_topics,
            "basic_info_mentions": basic_info_mentions,
            "datetime_mentions": datetime_mentions,
        },
    )

    logger.warning(f"intent_router: intent={intent}")
    local_state["intent"] = intent
    return local_state