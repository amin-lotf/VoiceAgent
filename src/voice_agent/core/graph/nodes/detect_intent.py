from __future__ import annotations

import asyncio
import logging
import time


from voice_agent.core.graph.nodes.utils import safe_json_parse, set_node_data
from voice_agent.core.llm.huggingface_llm import agent_model
from voice_agent.core.prompts.intent_router import build_intent_router_prompt
from voice_agent.core.types import CallState, ClinicIntent, OfficeTopic, APPOINTMENT_INTENTS

logger = logging.getLogger(__name__)

async def node_detect_intent(state: CallState) -> dict:
    """
    LLM-based intent router. Non-streaming call with JSON output.
    """
    local_state: dict ={}
    prompt = build_intent_router_prompt(state)
    pending_intent = state.get("pending_intent")
    data = {}
    llm_failed = False
    try:

        t0= time.perf_counter()
        resp =  await asyncio.to_thread(agent_model.invoke, prompt)
        # resp = await LLM.ainvoke(prompt)
        t1= time.perf_counter()
        logger.warning(f'intent_router: LLM request took {t1-t0:0.2f}s')
        data = safe_json_parse(resp.content or "",logger=logger)
    except Exception:
        logger.warning("Intent router failed; using fallback", exc_info=True)
        llm_failed = True

    intent_raw = data.get("intent")
    logger.warning(f'intent_raw: intent={intent_raw}')
    try:
        intent = ClinicIntent(intent_raw)
    except Exception:
        logger.warning(f'intent_router: invalid intent={intent_raw}')
        intent = None

    if intent is None or llm_failed:
        intent = ClinicIntent.COMPLEX

    office_topics_raw = data.get("office_topics", [])
    logger.warning(f'office_topics_raw: {office_topics_raw}')
    if isinstance(office_topics_raw, list):
        office_topics: list[OfficeTopic] = []
        for t in office_topics_raw:
            try:
                office_topics.append(OfficeTopic(str(t)))
            except Exception:
                continue

        if office_topics:
            if not pending_intent and intent in APPOINTMENT_INTENTS:
                local_state["pending_intent"] = intent
            intent = ClinicIntent.OFFICE_INFO
            local_state['node_data'] = {"office_info": {"office_topics": office_topics}}
    logger.warning(f'intent_router: intent={intent}')
    local_state["intent"] = intent
    return local_state
