import logging

from langgraph.graph import END, START, StateGraph

from voice_agent.core.types import CallEvent, CallPhase, CallState
from voice_agent.core.graph.nodes.confirm import (
    node_confirm_appointment,
    node_handle_confirm_yes_no,
)
from voice_agent.core.graph.nodes.greeting import node_on_call_started
from voice_agent.core.graph.nodes.handoff import node_handoff_fallback
from voice_agent.core.graph.nodes.routing import (
    node_ask_clarify_intent,
    node_detect_intent,
    node_finalize_response,
    node_handle_hangup,
    node_route_event,

)
from voice_agent.core.graph.nodes.slot_filling import (
    node_ask_next_appointment_slot,
    node_fill_appointment_slot,
)
from voice_agent.core.graph.nodes.tools import node_execute_schedule_appointment
from voice_agent.core.graph.nodes.triage import (
    node_triage_precheck,
    node_triage_respond,
)

logger = logging.getLogger(__name__)

def build_call_graph():
    graph = StateGraph(state_schema=CallState)

    # Nodes
    graph.add_node("route_event", node_route_event)
    graph.add_node("route_phase", lambda state: state)
    graph.add_node("on_call_started", node_on_call_started)
    graph.add_node("triage_precheck", node_triage_precheck)
    graph.add_node("triage_respond", node_triage_respond)
    graph.add_node("detect_intent", node_detect_intent)
    graph.add_node("fill_appointment_slot", node_fill_appointment_slot)
    graph.add_node("ask_next_appointment_slot", node_ask_next_appointment_slot)
    graph.add_node("confirm_appointment", node_confirm_appointment)
    graph.add_node("handle_confirm_yes_no", node_handle_confirm_yes_no)
    graph.add_node("execute_schedule_appointment", node_execute_schedule_appointment)
    graph.add_node("handoff_fallback", node_handoff_fallback)
    graph.add_node("handle_hangup", node_handle_hangup)
    graph.add_node("ask_clarify_intent", node_ask_clarify_intent)
    graph.add_node("finalize_response", node_finalize_response)

    # Entry
    graph.add_edge(START, "route_event")

    graph.add_conditional_edges(
        "route_event",
        lambda state: state.get("event"),
        {
            CallEvent.CALL_STARTED: "on_call_started",
            CallEvent.USER_TURN: "triage_precheck",
            CallEvent.HANGUP: "handle_hangup",
            None: "finalize_response",
        },
    )

    graph.add_edge("on_call_started", END)
    graph.add_edge("handle_hangup", END)

    graph.add_conditional_edges(
        "triage_precheck",
        lambda state: bool(state.get("triage_triggered")),
        {True: "triage_respond", False: "route_phase"},
    )

    def _route_phase(state: CallState) -> str:
        phase = state.get("phase") or CallPhase.INTENT_ROUTING
        logger.warning(f"🔥Routing phase: {phase.value}")
        # normalize enums that became strings after JSON persistence
        if isinstance(phase, str):
            try:
                phase = CallPhase(phase)
            except Exception:
                phase = CallPhase.INTENT_ROUTING
                state["phase"] = phase

        if phase == CallPhase.CONFIRM:
            return "confirm_handle" if state.get("pending_question") == "confirm_yes_no" else "confirm_prompt"

        if phase == CallPhase.GREETING:
            state["phase"] = CallPhase.INTENT_ROUTING
            return CallPhase.INTENT_ROUTING.value

        if phase not in {
            CallPhase.INTENT_ROUTING,
            CallPhase.SLOT_FILL,
            CallPhase.TOOL_EXECUTION,
            CallPhase.TRIAGE,
            CallPhase.HANDOFF,
            CallPhase.DONE,
        }:
            state["phase"] = CallPhase.INTENT_ROUTING
            return CallPhase.INTENT_ROUTING.value

        return phase.value

    graph.add_conditional_edges(
        "route_phase",
        _route_phase,
        {
            "confirm_prompt": "confirm_appointment",
            "confirm_handle": "handle_confirm_yes_no",
            CallPhase.INTENT_ROUTING.value: "detect_intent",
            CallPhase.SLOT_FILL.value: "fill_appointment_slot",
            CallPhase.TOOL_EXECUTION.value: "execute_schedule_appointment",
            CallPhase.HANDOFF.value: "handoff_fallback",
            CallPhase.DONE.value: END,
        },
    )

    graph.add_edge("triage_respond", END)
    graph.add_edge("handoff_fallback", END)

    def _after_intent(state: CallState):
        phase = state.get("phase")
        if state.get("assistant_text"):
            return "respond"
        if phase == CallPhase.SLOT_FILL:
            return "slot_fill"
        if phase == CallPhase.HANDOFF:
            return "handoff"
        return "clarify"

    graph.add_conditional_edges(
        "detect_intent",
        _after_intent,
        {
            "slot_fill": "fill_appointment_slot",
            "handoff": "handoff_fallback",
            "respond": "finalize_response",
            "clarify": "ask_clarify_intent",
        },
    )

    def _after_slot_fill(state: CallState):
        if state.get("phase") == CallPhase.CONFIRM:
            return "confirm"
        return "ask"

    graph.add_conditional_edges(
        "fill_appointment_slot",
        _after_slot_fill,
        {
            "confirm": "confirm_appointment",
            "ask": "ask_next_appointment_slot",
        },
    )

    graph.add_edge("ask_next_appointment_slot", END)
    graph.add_edge("confirm_appointment", END)
    graph.add_edge("finalize_response", END)
    graph.add_edge("ask_clarify_intent", "finalize_response")

    def _after_confirm(state: CallState):
        if state.get("phase") == CallPhase.TOOL_EXECUTION:
            return "tool"
        if state.get("phase") == CallPhase.SLOT_FILL:
            return "ask_slot"
        return "respond"

    graph.add_conditional_edges(
        "handle_confirm_yes_no",
        _after_confirm,
        {
            "tool": "execute_schedule_appointment",
            "ask_slot": "ask_next_appointment_slot",
            "respond": "finalize_response",
        },
    )

    graph.add_edge("execute_schedule_appointment", END)

    return graph.compile()
