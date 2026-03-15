import logging
from functools import partial

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from voice_agent.core.graph.nodes.basic_info import node_basic_info
from voice_agent.core.graph.nodes.check_pending import node_check_pending
from voice_agent.core.graph.nodes.merger import node_merger
from voice_agent.core.graph.nodes.office_info import node_office_info
from voice_agent.core.types import CallEvent, CallPhase, CallState, ClinicIntent
from voice_agent.core.graph.nodes.greeting import node_on_call_started
from voice_agent.core.graph.nodes.handoff import node_handoff_fallback
from voice_agent.core.graph.nodes.routing import (
    node_route_event,
)
from voice_agent.core.graph.nodes.detect_intent import node_detect_intent
from voice_agent.core.graph.nodes.finalize_response import node_finalize_response
from voice_agent.core.graph.nodes.hangup import node_handle_hangup, node_on_call_ended
from voice_agent.core.graph.nodes.slot_filling import (
    node_fill_appointment_slot,
)
from voice_agent.core.graph.nodes.book_appointment import node_book_appointment_node
from voice_agent.core.graph.nodes.post_booking_notes import node_post_booking_notes_node
from voice_agent.core.graph.nodes.reschedule_cancel import (
    node_reschedule_cancel_node,
    node_update_appointment_node,
)

logger = logging.getLogger(__name__)

def build_call_graph(sessionmaker: async_sessionmaker[AsyncSession]):
    graph = StateGraph(state_schema=CallState)

    # Nodes
    graph.add_node("route_event", node_route_event)
    graph.add_node("on_call_started", node_on_call_started)
    graph.add_node("detect_intent", node_detect_intent)
    graph.add_node("basic_info", node_basic_info)
    graph.add_node("get_office_info", node_office_info)
    graph.add_node("handoff_fallback", node_handoff_fallback)
    graph.add_node("handle_hangup", node_handle_hangup)
    graph.add_node("on_call_ended", node_on_call_ended)
    graph.add_node("merger", node_merger)
    graph.add_node('router_node', lambda state: state)
    graph.add_node("finalize_response", node_finalize_response)
    graph.add_edge(START, "route_event")
    graph.add_conditional_edges(
        "route_event",
        lambda state: state.get("event"),
        {
            CallEvent.CALL_STARTED: "on_call_started",
            # CallEvent.USER_TURN: "triage_precheck",
            CallEvent.USER_TURN: "router_node",
            CallEvent.CALL_ENDED: "on_call_ended",
            None: "finalize_response",
        },
    )

    graph.add_edge("on_call_started", 'finalize_response')
    graph.add_edge("handle_hangup", "finalize_response")
    graph.add_edge("handoff_fallback", 'finalize_response')



    graph.add_edge('router_node', 'detect_intent')
    graph.add_edge('router_node', 'basic_info')
    graph.add_edge('detect_intent', 'get_office_info')
    graph.add_edge('get_office_info', 'merger')
    graph.add_edge('basic_info', 'merger')
    def _after_merger(state: CallState):
        intent = state.get("intent")
        match intent:
            case ClinicIntent.OFFICE_INFO:
                return "finalize_response"
            case ClinicIntent.HANGUP:
                return 'handle_hangup'
            case ClinicIntent.HUMAN_HANDOFF | ClinicIntent.TRIAGE:
                return 'handoff_fallback'
            case _:
                return "finalize_response"
    graph.add_conditional_edges('merger',_after_merger,{
        'finalize_response': 'finalize_response',
        'handle_hangup': 'handle_hangup',
        'handoff_fallback': 'handoff_fallback',
    }
                                )
    graph.add_edge('merger', 'finalize_response')

    graph.add_conditional_edges("finalize_response",
                                lambda state: 'end_call' if bool(state.get("end_call")) else 'keep_call',
                                {"end_call": 'on_call_ended', 'keep_call': END},
                                )

    graph.add_edge('on_call_ended', END)
    return graph.compile()
