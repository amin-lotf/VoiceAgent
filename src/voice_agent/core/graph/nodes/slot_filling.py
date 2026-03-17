from __future__ import annotations

import time
import logging

from langgraph.config import get_stream_writer

from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.slot_filling import build_openai_basic_info_guard_prompt
from voice_agent.core.types import CallState

logger = logging.getLogger(__name__)





async def node_fill_appointment_slot(state: CallState,) -> dict:
    return  {}
    prompt = build_openai_basic_info_guard_prompt(state=state)
    writer = get_stream_writer()
    assistant_text= ""
    local_state:dict={}
    try:
        if writer:
            async for chunk in LLM.astream(prompt):
                token = chunk.content or ""
                if token:
                    assistant_text += token
                    writer(("assistant_token", token))
            local_state["assistant_streamed"] = True
        else:
            resp = await LLM.ainvoke(prompt)
            assistant_text = (resp.content or "").strip()
    except Exception:
        # Keep the call flowing even if the LLM request fails.
        assistant_text = ""

    local_state['assistant_text'] = assistant_text.strip() or (
        "Hi, thanks for calling. How can I help you today? "
        "You can say things like book an appointment, reschedule, or ask about office hours."
    )
    return local_state

