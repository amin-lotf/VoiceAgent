from __future__ import annotations

from langgraph.config import get_stream_writer
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.nodes.utils import is_appointment_complete
from voice_agent.core.types import  CallState



def node_fill_appointment_slot(state: CallState) -> CallState:
    appointment = state.get("appointment_create") or {}
    text = "do you have a preferred date and time?"
    state["assistant_text"] = text
    writer = get_stream_writer()
    if writer:
        for word in text.split():
            writer(("assistant_token", word + " "))
        state["assistant_streamed"] = True
    state['read_to_confirm'] = is_appointment_complete(appointment)
    return state


async def node_confirm_appointment_slot(state: CallState,*,sessionmaker: async_sessionmaker[AsyncSession]) -> CallState:
    appointment = state.get("appointment_create") or {}
    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
    text = "do you confirm this appointment?"
    state["assistant_text"] = text
    writer = get_stream_writer()
    if writer:
        for word in text.split():
            writer(("assistant_token", word + " "))
        state["assistant_streamed"] = True
    return state