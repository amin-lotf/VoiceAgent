from __future__ import annotations

from typing import Any
from voice_agent.core.types import CallState
import logging

logger = logging.getLogger(__name__)




async def node_basic_info(state: CallState) -> dict[str, Any]:
    next_action = state.get('next_action')
    logger.warning(f'basic_info:next_action: {next_action}')
    return {}


