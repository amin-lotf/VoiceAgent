from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph,START,END

from voice_agent.core.graph.nodes import node_wait_start
from voice_agent.core.types import CallState


def build_call_graph():
    g = StateGraph(CallState)

    g.add_node("wait_start", node_wait_start)
    g.add_edge(START, "wait_start")
    g.add_edge('wait_start',END)
    return g.compile(checkpointer=InMemorySaver())