import logging
from functools import partial

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from voice_agent.core.graph.nodes.basic_info import node_basic_info
from voice_agent.core.graph.nodes.basic_info_extractor import node_basic_info_extractor
from voice_agent.core.graph.nodes.book_appointment import node_book_appointment
from voice_agent.core.graph.nodes.call_operator import node_call_operator
from voice_agent.core.graph.nodes.datetime_extractor import node_datetime_extractor
from voice_agent.core.graph.nodes.error_handling import node_error_handling
from voice_agent.core.graph.nodes.hold_appointment import node_hold_appointment
from voice_agent.core.graph.nodes.collecting_note import node_collecting_note
from voice_agent.core.graph.nodes.schedule_patch_to_requested_time_iso import node_schedule_patch_to_requested_time_iso
from voice_agent.core.graph.nodes.user_intent import node_user_intent
from voice_agent.core.graph.node_timing import with_node_timing
from voice_agent.core.graph.nodes.utils import get_state_data
from voice_agent.core.types import CallEvent, CallState, AssistantIntent, NextAction, AssistantPhase
from voice_agent.core.graph.nodes.greeting import node_on_call_started
from voice_agent.core.graph.nodes.handoff import node_handoff_fallback
from voice_agent.core.graph.nodes.routing import (
    node_route_event,
)
from voice_agent.core.graph.nodes.finalize_response import node_finalize_response
from voice_agent.core.graph.nodes.hangup import node_handle_hangup, node_on_call_ended

logger = logging.getLogger(__name__)


def build_call_graph(sessionmaker: async_sessionmaker[AsyncSession]):
    graph = StateGraph(state_schema=CallState)

    def add_timed_node(node_name: str, node_fn) -> None:
        graph.add_node(node_name, with_node_timing(node_name, node_fn))

    # Nodes
    add_timed_node("route_event", node_route_event)
    add_timed_node("on_call_started", node_on_call_started)
    add_timed_node("call_operator", node_call_operator)
    add_timed_node("user_intent", node_user_intent)
    add_timed_node('basic_info', partial(node_basic_info, sessionmaker=sessionmaker))
    add_timed_node("basic_info_extractor", node_basic_info_extractor)
    add_timed_node('datetime_extractor', node_datetime_extractor)
    add_timed_node('schedule_patch_to_requested_time_iso', node_schedule_patch_to_requested_time_iso)
    add_timed_node('hold_appointment', partial(node_hold_appointment, sessionmaker=sessionmaker))
    add_timed_node('book_appointment', partial(node_book_appointment, sessionmaker=sessionmaker))
    add_timed_node('collecting_note', partial(node_collecting_note, sessionmaker=sessionmaker))
    add_timed_node("handoff_fallback", node_handoff_fallback)
    add_timed_node("handle_hangup", node_handle_hangup)
    add_timed_node("error_handling", node_error_handling)
    add_timed_node('on_call_ended', partial(node_on_call_ended, sessionmaker=sessionmaker))
    add_timed_node("finalize_response", node_finalize_response)
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

    graph.add_edge("on_call_started", END)
    graph.add_edge("handle_hangup", "finalize_response")
    graph.add_edge("handoff_fallback", 'finalize_response')

    def _after_call_operator(state: CallState):
        next_action = state.get("next_action")
        if next_action == NextAction.REPORT_ERROR:
            return 'error_handling'
        intent = state.get("assistant_intent")
        match intent:
            case AssistantIntent.HANGUP:
                return 'handle_hangup'
            case AssistantIntent.HUMAN_HANDOFF:
                return 'handoff_fallback'
            case _:
                assistant_phase = state.get("assistant_phase")
                match assistant_phase:
                    case AssistantPhase.COLLECTING_USER_INTENT:
                        return 'user_intent'
                    case AssistantPhase.CONFIRMING_SLOT:
                        return 'datetime_extractor'
                    case AssistantPhase.BOOKING_APPOINTMENT:
                        return 'book_appointment'
                    case AssistantPhase.COLLECTING_NOTES:
                        return 'collecting_note'
                    case _:
                        return 'basic_info'

    graph.add_conditional_edges('call_operator', _after_call_operator, {
        'handle_hangup': 'handle_hangup',
        'handoff_fallback': 'handoff_fallback',
        'user_intent': 'user_intent',
        'basic_info': 'basic_info',
        'collecting_note': 'collecting_note',
        'datetime_extractor': 'datetime_extractor',
        'book_appointment': 'book_appointment',
        'error_handling': 'error_handling',
    }
                                )

    def _after_error_handling(state: CallState):
        node_data = get_state_data(state, 'error_handling')
        next_node = node_data.get('next_node')
        return next_node

    graph.add_conditional_edges('error_handling', _after_error_handling, {
        'call_operator': 'call_operator',
        'handoff_fallback': 'handoff_fallback',
        'basic_info_extractor': 'basic_info_extractor',
        'basic_info': 'basic_info',
        'datetime_extractor': 'datetime_extractor',
        'hold_appointment': 'hold_appointment',
        'book_appointment': 'book_appointment',
    }
                                )

    def _after_datetime_extractor(state: CallState):
        next_action = state.get("next_action")
        match next_action:
            case NextAction.CALL_OPERATOR:
                return 'call_operator'
            case NextAction.HOLD_APPOINTMENT:
                return 'schedule_patch_to_requested_time_iso'
            case NextAction.BOOK_APPOINTMENT:
                return 'book_appointment'
            case NextAction.REPORT_ERROR:
                return 'error_handling'
            case _:
                return 'finalize_response'

    graph.add_conditional_edges('datetime_extractor', _after_datetime_extractor, {
        'finalize_response': 'finalize_response',
        'call_operator': 'call_operator',
        'schedule_patch_to_requested_time_iso': 'schedule_patch_to_requested_time_iso',
        'book_appointment': 'book_appointment',
        'error_handling': 'error_handling',
    })

    def _after_schedule_patch_to_requested_time_iso(state: CallState):
        next_action = state.get("next_action")
        match next_action:
            case NextAction.CALL_OPERATOR:
                return 'call_operator'
            case NextAction.REPORT_ERROR:
                return 'error_handling'
            case _:
                return 'hold_appointment'

    graph.add_conditional_edges('schedule_patch_to_requested_time_iso', _after_schedule_patch_to_requested_time_iso, {
        'call_operator': 'call_operator',
        'hold_appointment': 'hold_appointment',
    })

    def _after_hold_appointment(state: CallState):
        next_action = state.get("next_action")
        match next_action:
            case NextAction.REPORT_ERROR:
                return 'error_handling'
            case _:
                return 'call_operator'

    graph.add_conditional_edges('hold_appointment', _after_hold_appointment, {
        'call_operator': 'call_operator',
        'error_handling': 'error_handling'
    })

    def _after_book_appointment(state: CallState):
        next_action = state.get("next_action")
        match next_action:
            case NextAction.REPORT_ERROR:
                return 'error_handling'
            case _:
                return 'call_operator'
    graph.add_conditional_edges('book_appointment', _after_book_appointment, {
        'call_operator': 'call_operator',
        'error_handling': 'error_handling'
    })

    def _after_collecting_note(state: CallState):
        next_action = state.get("next_action")
        match next_action:
            case NextAction.REPORT_ERROR:
                return 'error_handling'
            case _:
                return 'finalize_response'
    graph.add_conditional_edges('collecting_note', _after_collecting_note, {
        'error_handling': 'error_handling',
        'finalize_response': 'finalize_response'
    })

    def _after_user_intent(state: CallState):
        next_action = state.get("next_action")
        match next_action:
            case NextAction.CALL_OPERATOR:
                return 'call_operator'
            case _:
                return 'finalize_response'

    graph.add_conditional_edges('user_intent', _after_user_intent, {
        'finalize_response': 'finalize_response',
        'call_operator': 'call_operator',
    })

    def _after_basic_info(state: CallState):
        next_action = state.get("next_action")
        match next_action:
            case NextAction.CALL_OPERATOR:
                return 'call_operator'
            case NextAction.EXTRACT_INFO:
                return 'basic_info_extractor'
            case NextAction.EXTRACT_DATETIME:
                return 'datetime_extractor'
            case NextAction.REPORT_ERROR:
                return 'error_handling'
            case _:
                return 'finalize_response'

    graph.add_conditional_edges('basic_info', _after_basic_info, {
        'finalize_response': 'finalize_response',
        'call_operator': 'call_operator',
        'basic_info_extractor': 'basic_info_extractor',
        'datetime_extractor': 'datetime_extractor',
        'error_handling': 'error_handling',
    })

    def _after_basic_info_extractor(state: CallState):
        next_action = state.get("next_action")
        if next_action == NextAction.REPORT_ERROR:
            return 'error_handling'
        return 'basic_info'

    graph.add_conditional_edges('basic_info_extractor', _after_basic_info_extractor, {
        'error_handling': 'error_handling',
        'basic_info': 'basic_info',
    })

    graph.add_conditional_edges("finalize_response",
                                lambda state: 'end_call' if bool(state.get("end_call")) else 'keep_call',
                                {"end_call": 'on_call_ended', 'keep_call': END},
                                )

    graph.add_edge('on_call_ended', END)
    return graph.compile()
