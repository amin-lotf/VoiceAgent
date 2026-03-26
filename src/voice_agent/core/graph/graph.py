import logging
from functools import partial

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from voice_agent.core.graph.nodes.basic_info import node_basic_info
from voice_agent.core.graph.nodes.call_operator import node_call_operator
from voice_agent.core.graph.nodes.hold_appointment import node_hold_appointment
from voice_agent.core.graph.nodes.load_or_create_appointment import node_load_or_create_appointment
from voice_agent.core.graph.nodes.patch_resolver import node_patch_resolver
from voice_agent.core.graph.nodes.office_info import node_office_info
from voice_agent.core.graph.nodes.slot_filling import node_fill_appointment_slot
from voice_agent.core.graph.nodes.time_extractor import node_time_extractor
from voice_agent.core.types import CallEvent, CallPhase, CallState, ClinicIntent, AssistantPhase
from voice_agent.core.graph.nodes.greeting import node_on_call_started
from voice_agent.core.graph.nodes.handoff import node_handoff_fallback
from voice_agent.core.graph.nodes.routing import (
    node_route_event,
)
from voice_agent.core.graph.nodes.detect_intent import node_detect_intent
from voice_agent.core.graph.nodes.finalize_response import node_finalize_response
from voice_agent.core.graph.nodes.hangup import node_handle_hangup, node_on_call_ended

logger = logging.getLogger(__name__)


def build_call_graph(sessionmaker: async_sessionmaker[AsyncSession]):
    graph = StateGraph(state_schema=CallState)

    # Nodes
    graph.add_node("route_event", node_route_event)
    graph.add_node("on_call_started", node_on_call_started)
    graph.add_node("call_operator", node_call_operator)
    # graph.add_node("basic_info", node_basic_info)
    # graph.add_node("slot_filling", node_fill_appointment_slot)
    # graph.add_node("time_extractor", node_time_extractor)
    # graph.add_node("get_office_info", node_office_info)
    graph.add_node("handoff_fallback", node_handoff_fallback)
    graph.add_node("handle_hangup", node_handle_hangup)
    graph.add_node("on_call_ended", node_on_call_ended)
    graph.add_node("patch_resolver", node_patch_resolver)
    graph.add_node('load_or_create_appointment', partial(node_load_or_create_appointment, sessionmaker=sessionmaker))
    graph.add_node('hold_appointment', partial(node_hold_appointment, sessionmaker=sessionmaker))
    graph.add_node("finalize_response", node_finalize_response)
    graph.add_edge(START, "route_event")
    graph.add_conditional_edges(
        "route_event",
        lambda state: state.get("event"),
        {
            CallEvent.CALL_STARTED: "on_call_started",
            # CallEvent.USER_TURN: "triage_precheck",
            CallEvent.USER_TURN: "call_operator",
            CallEvent.CALL_ENDED: "on_call_ended",
            None: "finalize_response",
        },
    )

    graph.add_edge("on_call_started", 'finalize_response')
    graph.add_edge("handle_hangup", "finalize_response")
    graph.add_edge("handoff_fallback", 'finalize_response')

    # graph.add_edge('call_operator', 'get_office_info')
    # graph.add_edge('get_office_info', 'router_node')
    # graph.add_edge('basic_info', 'patch_resolver')
    # graph.add_edge('time_extractor', 'patch_resolver')
    def _after_call_operator(state: CallState):
        intent = state.get("clinic_intent")
        match intent:
            case ClinicIntent.HANGUP:
                return 'handle_hangup'
            case ClinicIntent.HUMAN_HANDOFF:
                return 'handoff_fallback'
            case _:
                return "patch_resolver"

    graph.add_conditional_edges('call_operator', _after_call_operator, {
        'patch_resolver': 'patch_resolver',
        'handle_hangup': 'handle_hangup',
        'handoff_fallback': 'handoff_fallback',
    }
                                )

    graph.add_edge('patch_resolver', 'load_or_create_appointment')
    graph.add_edge('load_or_create_appointment', 'hold_appointment')
    graph.add_conditional_edges(
        'hold_appointment',
        lambda state: 'call_operator' if
        state.get('assistant_phase') == AssistantPhase.SEARCHING_SLOT else
        'finalize_response',
        {'call_operator': 'call_operator', 'finalize_response': 'finalize_response'},
    )
    # graph.add_edge('hold_appointment', 'finalize_response')

    graph.add_conditional_edges("finalize_response",
                                lambda state: 'end_call' if bool(state.get("end_call")) else 'keep_call',
                                {"end_call": 'on_call_ended', 'keep_call': END},
                                )

    graph.add_edge('on_call_ended', END)
    return graph.compile()
