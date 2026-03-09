import logging
from functools import partial

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from voice_agent.core.graph.nodes.check_pending import node_check_pending
from voice_agent.core.graph.nodes.office_info import node_office_info
from voice_agent.core.types import CallEvent, CallPhase, CallState, ClinicIntent
from voice_agent.core.graph.nodes.greeting import node_on_call_started
from voice_agent.core.graph.nodes.handoff import node_handoff_fallback
from voice_agent.core.graph.nodes.routing import (
    node_ask_clarify_intent,
    node_detect_intent,
    node_finalize_response,
    node_route_event,
)
from voice_agent.core.graph.nodes.hangup import node_handle_hangup, node_on_call_ended
from voice_agent.core.graph.nodes.slot_filling import (
    node_fill_appointment_slot,
    node_book_appointment_node,
    node_post_booking_notes_node,
)
from voice_agent.core.graph.nodes.reschedule_cancel import (
    node_reschedule_cancel_node,
    node_update_appointment_node,
)

logger = logging.getLogger(__name__)

def build_call_graph(sessionmaker: async_sessionmaker[AsyncSession]):
    graph = StateGraph(state_schema=CallState)

    # Nodes
    graph.add_node("route_event", node_route_event)
    # graph.add_node("route_phase", lambda state: state)
    graph.add_node("on_call_started", node_on_call_started)
    graph.add_node("check_pending", node_check_pending)
    graph.add_node("detect_intent", node_detect_intent)
    graph.add_node("get_office_info", node_office_info)

    graph.add_node(
        "fill_appointment_slot",
        partial(
            node_fill_appointment_slot,
            sessionmaker=sessionmaker,
        ),
    )
    graph.add_node(
        "book_appointment_node",
        partial(
            node_book_appointment_node,
            sessionmaker=sessionmaker,
        ),
    )
    graph.add_node(
        "post_booking_notes_node",
        partial(
            node_post_booking_notes_node,
            sessionmaker=sessionmaker,
        ),
    )
    graph.add_node(
        "reschedule_cancel_node",
        partial(
            node_reschedule_cancel_node,
            sessionmaker=sessionmaker,
        ),
    )
    graph.add_node(
        "update_appointment_node",
        partial(
            node_update_appointment_node,
            sessionmaker=sessionmaker,
        ),
    )
    graph.add_node("handoff_fallback", node_handoff_fallback)
    graph.add_node("handle_hangup", node_handle_hangup)
    graph.add_node("on_call_ended", node_on_call_ended)
    graph.add_node("ask_clarify_intent", node_ask_clarify_intent)
    graph.add_node("finalize_response", node_finalize_response)

    # Entry
    graph.add_edge(START, "route_event")

    graph.add_conditional_edges(
        "route_event",
        lambda state: state.get("event"),
        {
            CallEvent.CALL_STARTED: "on_call_started",
            # CallEvent.USER_TURN: "triage_precheck",
            CallEvent.USER_TURN: "detect_intent",
            CallEvent.CALL_ENDED: "on_call_ended",
            None: "finalize_response",
        },
    )

    graph.add_edge("on_call_started", 'finalize_response')
    graph.add_edge("handle_hangup", "finalize_response")

    # graph.add_conditional_edges(
    #     "triage_precheck",
    #     lambda state: bool(state.get("triage_triggered")),
    #     {True: "handoff_fallback", False: "detect_intent"},
    # )


    graph.add_edge("handoff_fallback", 'finalize_response')

    def _after_intent(state: CallState):
        intent = state.get("intent")
        match intent:
            case ClinicIntent.BOOK_APPOINTMENT:
                return "slot_fill"
            case ClinicIntent.RESCHEDULE | ClinicIntent.CANCEL:
                return "reschedule_cancel"
            case ClinicIntent.POST_APPOINTMENT:
                return "post_booking_notes"
            case ClinicIntent.HUMAN_HANDOFF | ClinicIntent.TRIAGE:
                return "handoff"
            case ClinicIntent.HANGUP:
                return "hangup"
            case ClinicIntent.OFFICE_INFO:
                return "office_info"
            case ClinicIntent.CHECK_PENDING:
                return 'check_pending'
            case _:
                return "clarify"

    def _after_pending(state: CallState):
        intent = state.get("intent")
        match intent:
            case ClinicIntent.BOOK_APPOINTMENT:
                return "slot_fill"
            case ClinicIntent.RESCHEDULE | ClinicIntent.CANCEL:
                return "reschedule_cancel"
            case ClinicIntent.POST_APPOINTMENT:
                return "post_booking_notes"
            case _:
                return "clarify"


    graph.add_conditional_edges(
        "detect_intent",
        _after_intent,
        {
            "slot_fill": "fill_appointment_slot",
            "reschedule_cancel": "reschedule_cancel_node",
            "post_booking_notes": "post_booking_notes_node",
            "handoff": "handoff_fallback",
            "hangup": "handle_hangup",
            "office_info": "get_office_info",
            "clarify": "ask_clarify_intent",
            'check_pending': 'check_pending'
        },
    )

    graph.add_conditional_edges('check_pending',
                                _after_pending,
                                {"slot_fill": "fill_appointment_slot",
                                 "reschedule_cancel": "reschedule_cancel_node",
                                 "post_booking_notes": "post_booking_notes_node",
                                 'clarify': 'ask_clarify_intent'},
                                )

    # graph.add_edge("fill_appointment_slot",'finalize_response')
    graph.add_conditional_edges(
        "fill_appointment_slot",
        lambda state: (
            "book"
            if bool(state.get("ready_to_confirm"))
            else ("reschedule" if bool(state.get("ready_to_reschedule")) else "finalize")
        ),
        {
            "book": "book_appointment_node",
            "reschedule": "reschedule_cancel_node",
            "finalize": "finalize_response",
        },
    )
    graph.add_conditional_edges("reschedule_cancel_node",
                                lambda state: 'true' if bool(state.get("ready_to_update")) else 'false',
                                {'true': 'update_appointment_node', 'false': 'finalize_response'})
    graph.add_edge("book_appointment_node", "finalize_response")
    graph.add_edge("update_appointment_node", "finalize_response")
    graph.add_edge("post_booking_notes_node", "finalize_response")
    graph.add_edge("get_office_info",'finalize_response')
    graph.add_conditional_edges("finalize_response",
                                lambda state:  'end_call' if bool(state.get("end_call")) else 'keep_call',
                                {"end_call": 'on_call_ended', 'keep_call': END},
                   )
    graph.add_edge("ask_clarify_intent", "finalize_response")
    return graph.compile()
