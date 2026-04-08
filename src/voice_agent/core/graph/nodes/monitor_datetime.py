from typing import Any
import logging
from voice_agent.core.types import CallState, AppointmentDraft, NextAction

logger = logging.getLogger(__name__)

async def node_monitor_datetime(state: CallState) -> dict[str, Any]:
    local_state ={}
    node_data = state.get("node_data") or {}
    patch_resolver = node_data.get('patch_resolver') or {}
    datetime_updated = patch_resolver.get('datetime_updated') or False
    if datetime_updated:
        local_state['next_action'] = NextAction.EXTRACT_DATETIME
    else:
        local_state['next_action'] =NextAction.OTHER

    logger.warning(f'=======\nmonitor_datetime:local_state: {local_state}\n=======')
    return local_state