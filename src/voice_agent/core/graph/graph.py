import logging
from functools import partial

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from voice_agent.core.graph.nodes.basic_info import node_basic_info
from voice_agent.core.graph.nodes.book_appointment import node_book_appointment
from voice_agent.core.graph.nodes.call_operator import node_call_operator
from voice_agent.core.graph.nodes.directive_prompt_builder import node_directive_prompt_builder
from voice_agent.core.graph.nodes.held_appointment_info import node_held_appointment_info
from voice_agent.core.graph.nodes.hold_appointment import node_hold_appointment
from voice_agent.core.graph.nodes.load_or_create_appointment import node_load_or_create_appointment
from voice_agent.core.graph.nodes.monitor_appointment_confirmation import node_monitor_appointment_confirmation
from voice_agent.core.graph.nodes.monitor_datetime import node_monitor_datetime
from voice_agent.core.graph.nodes.reset_gate import node_reset_gate
from voice_agent.core.graph.nodes.schedule_patch_to_requested_time_iso import \
    node_schedule_patch_to_requested_time_iso
from voice_agent.core.graph.nodes.patch_resolver import node_patch_resolver
from voice_agent.core.graph.nodes.office_info import node_office_info
from voice_agent.core.graph.nodes.planner import node_planner
from voice_agent.core.graph.nodes.slot_filling import node_fill_appointment_slot
from voice_agent.core.graph.nodes.datetime_extractor import  node_datetime_extractor
from voice_agent.core.graph.nodes.time_slot import node_time_slot
from voice_agent.core.graph.nodes.verify_appointment_info import node_verify_appointment_info
from voice_agent.core.types import CallEvent, CallPhase, CallState, ClinicIntent, AssistantPhase, NextAction
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
    graph.add_node("reset_gate", node_reset_gate)
    graph.add_node("planner", node_planner)
    graph.add_node("directive_prompt_builder", node_directive_prompt_builder)
    graph.add_node("call_operator", node_call_operator)
    graph.add_node('patch_resolver', partial(node_patch_resolver, sessionmaker=sessionmaker))
    graph.add_node('fields_input_gate', lambda state: state)
    graph.add_node('fields_output_gate', lambda state: state)
    graph.add_node("basic_info", node_basic_info)
    graph.add_node("time_slot", node_time_slot)
    graph.add_node("verify_appointment_info", node_verify_appointment_info)
    graph.add_node("datetime_extractor", node_datetime_extractor)
    graph.add_node("schedule_patch_to_requested_time_iso", node_schedule_patch_to_requested_time_iso)
    graph.add_node("monitor_datetime", node_monitor_datetime)
    graph.add_node("monitor_appointment_confirmation", node_monitor_appointment_confirmation)
    graph.add_node("hold_appointment", partial(node_hold_appointment, sessionmaker=sessionmaker))
    graph.add_node("held_appointment_info", node_held_appointment_info)
    graph.add_node("book_appointment", partial(node_book_appointment, sessionmaker=sessionmaker))
    graph.add_node("handoff_fallback", node_handoff_fallback)
    graph.add_node("handle_hangup", node_handle_hangup)
    graph.add_node('on_call_ended', partial(node_on_call_ended, sessionmaker=sessionmaker))
    graph.add_node("finalize_response", node_finalize_response)
    graph.add_node("monitor_call", lambda state: state)
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
    def _after_patch_resolver(state: CallState):
        assistant_phase = state.get("assistant_phase")
        if assistant_phase == AssistantPhase.COLLECTING_INFO:
            return 'fields_input_gate'
        return 'monitor_datetime'


    graph.add_conditional_edges('patch_resolver', _after_patch_resolver, {
        'monitor_datetime': 'monitor_datetime',
        'fields_input_gate': 'fields_input_gate',
    })

    # graph.add_edge('patch_resolver', 'fields_input_gate')
    graph.add_edge('fields_input_gate', 'basic_info')
    graph.add_edge('fields_input_gate', 'time_slot')
    graph.add_edge('basic_info', 'fields_output_gate')
    graph.add_edge('time_slot', 'fields_output_gate')


    graph.add_edge('fields_output_gate', 'verify_appointment_info')

    def _after_verify_appointment_info(state: CallState):
        next_action = state.get("next_action")
        if next_action ==NextAction.HOLD_APPOINTMENT:
            return 'datetime_extractor'
        return 'finalize_response'


    graph.add_conditional_edges('verify_appointment_info', _after_verify_appointment_info, {
        'datetime_extractor': 'datetime_extractor',
        'finalize_response': 'finalize_response',
    }
                                )

    def _after_monitor_datetime(state: CallState):
        next_action = state.get("next_action")
        if next_action==NextAction.EXTRACT_DATETIME:
            return 'datetime_extractor'
        return 'held_appointment_info'

    graph.add_conditional_edges('monitor_datetime', _after_monitor_datetime, {
        'datetime_extractor': 'datetime_extractor',
        'held_appointment_info': 'held_appointment_info',
    })

    graph.add_edge('datetime_extractor', 'schedule_patch_to_requested_time_iso')
    graph.add_edge('schedule_patch_to_requested_time_iso', 'hold_appointment')
    graph.add_edge('hold_appointment', 'held_appointment_info')

    def _after_held_appointment_info(state: CallState):
        next_action = state.get("next_action")
        if next_action==NextAction.CALL_OPERATOR:
            return 'finalize_response'
        return 'monitor_appointment_confirmation'
    graph.add_conditional_edges('held_appointment_info', _after_held_appointment_info, {
        'monitor_appointment_confirmation': 'monitor_appointment_confirmation',
        'finalize_response': 'finalize_response',
    })

    def _after_monitor_appointment_confirmation(state: CallState):
        next_action = state.get("next_action")
        if next_action == NextAction.BOOK_APPOINTMENT:
            return 'book_appointment'
        return 'finalize_response'
    graph.add_conditional_edges('monitor_appointment_confirmation', _after_monitor_appointment_confirmation, {
        'book_appointment': 'book_appointment',
        'finalize_response': 'finalize_response',
    })

    # graph.add_edge('held_appointment_info', 'book_appointment')
    graph.add_edge('book_appointment', 'finalize_response')

    # graph.add_edge('finalize_response', 'monitor_call')

    def _after_finalize_response(state: CallState):
        next_action = state.get("next_action")
        if next_action == NextAction.CALL_OPERATOR:
            return 'reset_gate'
        return 'monitor_call'



    graph.add_conditional_edges('finalize_response', _after_finalize_response, {
        'reset_gate': 'reset_gate',
        'monitor_call': 'monitor_call',
    })

    graph.add_edge('reset_gate', 'planner')

    graph.add_conditional_edges("monitor_call",
                                lambda state: 'end_call' if bool(state.get("end_call")) else 'keep_call',
                                {"end_call": 'on_call_ended', 'keep_call': END},
                                )

    graph.add_edge('on_call_ended', END)
    return graph.compile()
