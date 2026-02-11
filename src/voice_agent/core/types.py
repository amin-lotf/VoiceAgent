from typing import TypedDict, Annotated, List

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class CommunicationState(TypedDict, total=False):
    # output for UI
    assistant_text: str
    # memory/messages
    messages: Annotated[List[BaseMessage], add_messages]
    started_at: str
    finished_at: str