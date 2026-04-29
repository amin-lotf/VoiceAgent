from voice_agent.core.graph.nodes.utils import ensure_spoken_on_user_turn
from voice_agent.core.types import CallState
import logging

logger = logging.getLogger(__name__)


def node_finalize_response(state: CallState) -> dict:
    """
    Finalizes turn:
    - ensures assistant_text exists
    """
    local_state: dict = {'assistant_text': state.get('assistant_text') or ''}
    local_state.update(ensure_spoken_on_user_turn(state))
    logger.info(
        f"Finalizing response",
        extra={
            'call_id': state.get('call_id'),
            'phase': state.get('assistant_phase'),
            'node': 'finalize_response',
        }
    )
    return local_state