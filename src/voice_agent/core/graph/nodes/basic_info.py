import asyncio
import time

from voice_agent.core.graph.nodes.utils import safe_json_parse, set_node_data
from voice_agent.core.llm.huggingface_llm import agent_model
from voice_agent.core.prompts.basic_info import build_local_basic_info_extract_prompt
from voice_agent.core.types import CallState, AppointmentDraft, AppointmentPatch
import logging

logger = logging.getLogger(__name__)

async def node_basic_info(state: CallState) -> dict:
    local_state: dict ={}
    user_text = (state.get("user_text") or "").strip()
    appointment_draft: AppointmentDraft = state.setdefault("appointment_draft", {})
    local_patch: AppointmentPatch = {}
    if user_text:
        local_prompt = build_local_basic_info_extract_prompt(
            user_text=user_text,
            appointment=appointment_draft
        )
        try:
            t0 = time.perf_counter()
            resp = await asyncio.to_thread(agent_model.invoke, local_prompt)
            # resp = await LLM.ainvoke(local_prompt)
            t1 = time.perf_counter()
            raw = getattr(resp, "content", "") or ""
            parsed = safe_json_parse(raw)
            logger.warning(
                "----------\nlocal_extract time=%0.2fs raw=%s parsed=%s\n-----------",
                t1 - t0,
                raw,
                parsed,
            )
            if isinstance(parsed, dict):
                local_patch = parsed.get("patch") or {}
        except Exception:
            logger.exception("local_extract failed")
    local_state['node_data']={'appointment_patch': local_patch,}
    # set_node_data(state, node = 'basic_info',n_data = {'appointment_patch': local_patch})
    return local_state