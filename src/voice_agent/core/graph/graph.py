import logging
from langgraph.graph import END, START, StateGraph
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
from voice_agent.core.graph.nodes.slot_filling import node_fill_appointment_slot
from voice_agent.core.graph.nodes.triage import node_triage_precheck

logger = logging.getLogger(__name__)

def build_call_graph():
    graph = StateGraph(state_schema=CallState)

    # Nodes
    graph.add_node("route_event", node_route_event)
    # graph.add_node("route_phase", lambda state: state)
    graph.add_node("on_call_started", node_on_call_started)
    # graph.add_node("triage_precheck", node_triage_precheck)
    graph.add_node("detect_intent", node_detect_intent)
    graph.add_node("get_office_info", node_office_info)
    graph.add_node("fill_appointment_slot", node_fill_appointment_slot)
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
            case ClinicIntent.BOOK_APPOINTMENT | ClinicIntent.RESCHEDULE | ClinicIntent.CANCEL:
                return "slot_fill"
            case ClinicIntent.HUMAN_HANDOFF | ClinicIntent.TRIAGE:
                return "handoff"
            case ClinicIntent.HANGUP:
                return "hangup"
            case ClinicIntent.OFFICE_INFO:
                return "office_info"
            case _:
                return "clarify"


    graph.add_conditional_edges(
        "detect_intent",
        _after_intent,
        {
            "slot_fill": "fill_appointment_slot",
            "handoff": "handoff_fallback",
            "hangup": "handle_hangup",
            "office_info": "get_office_info",
            "clarify": "ask_clarify_intent",
        },
    )

    graph.add_edge("fill_appointment_slot",'finalize_response')
    graph.add_edge("get_office_info",'finalize_response')
    graph.add_conditional_edges("finalize_response",
                                lambda state:  'end_call' if bool(state.get("end_call")) else 'keep_call',
                                {"end_call": 'on_call_ended', 'keep_call': END},
                   )
    graph.add_edge("ask_clarify_intent", "finalize_response")
    return graph.compile()
