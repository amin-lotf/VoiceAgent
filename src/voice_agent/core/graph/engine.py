from datetime import datetime, timezone
from typing import AsyncIterator, Tuple, Any

from langgraph.types import Command

from voice_agent.core.graph.graph import build_interview_graph
from voice_agent.core.types import CommunicationState


def initial_state() -> CommunicationState:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "messages": [],
        "assistant_text": "",
        "started_at": now,
    }


class InterviewEngine:
    def __init__(self):
        self._graph = build_interview_graph()

    async def init(self, *, thread_id: str) -> CommunicationState:
        state = initial_state()
        out = await self._graph.ainvoke(state, config={"configurable": {"thread_id": thread_id}})
        return out

    async def resume(self, *, thread_id: str, resume_payload: dict) -> CommunicationState:
        out = await self._graph.ainvoke(
            Command(resume=resume_payload),
            config={"configurable": {"thread_id": thread_id}},
        )
        return out

    async def resume_stream(
        self, *, thread_id: str, resume_payload: dict
    ) -> AsyncIterator[Tuple[str, Any]]:
        """
        Resume execution with streaming enabled.
        Yields tuples of (event_type, data) where event_type is:
        - "question_token": streaming question generation
        - "evaluation_token": streaming evaluation feedback
        - "values": final state update
        """
        import logging
        logger = logging.getLogger(__name__)
        # logger.warning(f"🔥 resume_stream called with stream_mode=['custom', 'values']")

        chunk_count = 0
        async for chunk in self._graph.astream(
            Command(resume=resume_payload),
            config={"configurable": {"thread_id": thread_id}},
            stream_mode=["custom", "values"],
        ):
            chunk_count += 1
            # logger.warning(f"🔥 Chunk {chunk_count}: type={type(chunk)}, value={str(chunk)[:150]}")

            # Check 2-tuple format first (what we're actually getting)
            if isinstance(chunk, tuple) and len(chunk) == 2:
                mode, data = chunk

                if mode == "custom":
                    # custom event: ("custom", (event_type, token))
                    if isinstance(data, tuple) and len(data) == 2:
                        event_type, token = data
                        # logger.warning(f"🔥 Yielding custom event: {event_type}, token={str(token)[:30]}")
                        yield (event_type, token)
                    else:
                        logger.warning(f"🔥 Unexpected custom data format: {data}")
                elif mode == "values":
                    # values event: ("values", state_dict)
                    # logger.warning(f"🔥 Yielding values update")
                    yield ("values", data)
                else:
                    # Unknown mode
                    logger.warning(f"🔥 Unknown mode: {mode}")
                    yield (mode, data)

            # Check 3-tuple format (alternative format)
            elif isinstance(chunk, tuple) and len(chunk) == 3:
                namespace, mode, data = chunk
                if mode == "custom" and isinstance(data, tuple) and len(data) == 2:
                    event_type, token = data
                    # logger.warning(f"🔥 Yielding custom event (3-tuple): {event_type}")
                    yield (event_type, token)
                elif mode == "values":
                    logger.warning(f"🔥 Yielding values (3-tuple)")
                    yield ("values", data)

            elif isinstance(chunk, dict):
                # logger.warning(f"🔥 Yielding dict as values")
                yield ("values", chunk)
            else:
                logger.warning(f"🔥 Unknown chunk type: {type(chunk)}")
                yield ("update", chunk)