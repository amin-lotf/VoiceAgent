from langgraph.config import get_stream_writer

from voice_agent.core.graph.nodes.utils import get_state_data, stream_text_response, reset_node_data
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

    node_data = get_state_data(state, "detect_intent")
    topics = node_data.get('office_topics') or []
    if not topics:
        return {}
    text = _compose_office_response(topics)
    local_state=stream_text_response(text)
    reset_node_data(local_state, "detect_intent")
    return local_state
