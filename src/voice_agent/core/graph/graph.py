import logging
from functools import partial

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from voice_agent.core.graph.nodes.basic_info import node_basic_info
from voice_agent.core.graph.nodes.book_appointment import node_book_appointment
from voice_agent.core.graph.nodes.call_operator import node_call_operator
from voice_agent.core.graph.nodes.directive_prompt_builder import node_directive_prompt_builder
from voice_agent.core.graph.nodes.hold_appointment import node_hold_appointment
from voice_agent.core.graph.nodes.load_or_create_appointment import node_load_or_create_appointment
from voice_agent.core.graph.nodes.patch_resolver import node_patch_resolver
from voice_agent.core.graph.nodes.office_info import node_office_info
from voice_agent.core.graph.nodes.planner import node_planner
from voice_agent.core.graph.nodes.slot_filling import node_fill_appointment_slot
from voice_agent.core.graph.nodes.time_extractor import node_time_extractor
from voice_agent.core.graph.nodes.time_slot import node_time_slot
from voice_agent.core.graph.nodes.verify_appointment_info import node_verify_appointment_info
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
    graph.add_node("get_office_info", node_office_info)
    graph.add_node("planner", node_planner)
    graph.add_node("directive_prompt_builder", node_directive_prompt_builder)
    graph.add_node("call_operator", node_call_operator)
    graph.add_node('patch_resolver', partial(node_patch_resolver, sessionmaker=sessionmaker))
    graph.add_node('fields_input_gate', lambda state: state)
    graph.add_node('fields_output_gate', lambda state: state)
    graph.add_node("basic_info", node_basic_info)
    graph.add_node("time_slot", node_time_slot)
    graph.add_node("verify_appointment_info", node_verify_appointment_info)
    graph.add_node("book_appointment", partial(node_book_appointment, sessionmaker=sessionmaker))
    graph.add_node("handoff_fallback", node_handoff_fallback)
    graph.add_node("handle_hangup", node_handle_hangup)
    graph.add_node('on_call_ended', partial(node_on_call_ended, sessionmaker=sessionmaker))
    graph.add_node("finalize_response", node_finalize_response)
    graph.add_edge(START, "route_event")
    graph.add_conditional_edges(
        "route_event",
        lambda state: state.get("event"),
        {
            CallEvent.CALL_STARTED: "on_call_started",
            # CallEvent.USER_TURN: "triage_precheck",
            CallEvent.USER_TURN: "get_office_info",
            CallEvent.CALL_ENDED: "on_call_ended",
            None: "finalize_response",
        },
    )

    graph.add_edge("on_call_started", 'fields_input_gate')
    graph.add_edge("handle_hangup", "finalize_response")
    graph.add_edge("handoff_fallback", 'finalize_response')
    graph.add_edge('get_office_info', 'planner')
    graph.add_edge('planner', 'directive_prompt_builder')
    graph.add_edge('directive_prompt_builder', 'call_operator')

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
    graph.add_edge('patch_resolver', 'fields_input_gate')
    graph.add_edge('fields_input_gate', 'basic_info')
    graph.add_edge('fields_input_gate', 'time_slot')
    graph.add_edge('basic_info', 'fields_output_gate')
    graph.add_edge('time_slot', 'fields_output_gate')

    def _after_fields_output_gate(state: CallState):
        assistant_phase = state.get("assistant_phase")
        if assistant_phase == AssistantPhase.POST_APPOINTMENT:
            return 'finalize_response'
        return 'verify_appointment_info'

    graph.add_conditional_edges('fields_output_gate', _after_fields_output_gate, {
        'verify_appointment_info': 'verify_appointment_info',
        'finalize_response': 'finalize_response',
    }
                                )



    graph.add_edge('verify_appointment_info', 'finalize_response')

    def _after_verify_appointment_info(state: CallState):
        assistant_phase = state.get("assistant_phase")
        if assistant_phase == AssistantPhase.FINALIZING_APPOINTMENT:
            return 'book_appointment'
        return 'finalize_response'

    graph.add_conditional_edges('verify_appointment_info', _after_verify_appointment_info, {
        'book_appointment': 'book_appointment',
        'finalize_response': 'finalize_response',
    }
                                )

    graph.add_edge('book_appointment', 'planner')

    graph.add_conditional_edges("finalize_response",
                                lambda state: 'end_call' if bool(state.get("end_call")) else 'keep_call',
                                {"end_call": 'on_call_ended', 'keep_call': END},
                                )

    graph.add_edge('on_call_ended', END)
    return graph.compile()
