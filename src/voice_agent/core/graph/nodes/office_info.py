from voice_agent.core.types import CallState


async def node_office_info(state:CallState):
    return {
        "node_data": {
            "office_info": {
                "knowledge": {
                    "hours": "Mon–Fri 9 AM–5 PM",
                    "address": "123 Main Street",
                    "parking": "Available next to building",
                }
            }
        }
    }