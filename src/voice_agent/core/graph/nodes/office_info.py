from langgraph.config import get_stream_writer

from voice_agent.core.graph.nodes.utils import get_node_data, set_node_data, delete_node_value, stream_text_response
from voice_agent.core.types import CallEvent, CallPhase, CallState, ClinicIntent, OfficeTopic

OFFICE_TEMPLATES = {
    OfficeTopic.HOURS: "We're open Monday through Friday, 9 AM to 5 PM.",
    OfficeTopic.ADDRESS: "Our clinic is at 123 Main Street.",
    OfficeTopic.LOCATION: "We're located in the main office building downtown.",
    OfficeTopic.PARKING: "Parking is available in the lot next to the building.",
}

OFFICE_ORDER = [OfficeTopic.HOURS, OfficeTopic.ADDRESS, OfficeTopic.LOCATION, OfficeTopic.PARKING]

def _compose_office_response(topics: list[OfficeTopic]) -> str:
    norm = []
    seen = set()
    for t in topics:
        if t in OFFICE_TEMPLATES and t not in seen:
            norm.append(t)
            seen.add(t)

    # If router gave nothing usable, fall back
    if not norm:
        return (
            "I can share our hours, address, location, or parking info. "
            "What do you need?"
        )

    # Order them consistently
    ordered = [t for t in OFFICE_ORDER if t in seen]
    parts = [OFFICE_TEMPLATES[t] for t in ordered]

    msg = " ".join(parts)
    # msg += " Would you like to book, reschedule, or cancel an appointment?"
    return msg


def node_office_info(state: CallState) -> dict:
    if state.get("intent") != ClinicIntent.OFFICE_INFO:
        return {}
    node_data = get_node_data(state, "office_info")
    topics = node_data.get('office_topics') or []
    text = _compose_office_response(topics)
    local_state=stream_text_response(text)
    local_state['node_data'] = {"office_info": {}}
    pending_intent = state.get("pending_intent")
    if pending_intent:
        local_state['intent'] = pending_intent
    return local_state
