from typing import Any
import logging

from voice_agent.core.graph.nodes.utils import get_state_data
from voice_agent.core.types import CallState, AppointmentDraft, NextAction

logger = logging.getLogger(__name__)

async def node_monitor_datetime(state: CallState) -> dict[str, Any]:
    local_state ={}
    patch_resolver = get_state_data(state,'patch_resolver')
    datetime_updated = patch_resolver.get('datetime_updated') or False
    if datetime_updated:
        local_state['next_action'] = NextAction.EXTRACT_DATETIME
    else:
        local_state['next_action'] =NextAction.OTHER

    logger.warning(f'=======\nmonitor_datetime:local_state: {local_state}\n=======')
    return local_state