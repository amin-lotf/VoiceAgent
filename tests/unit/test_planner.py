import pytest

from voice_agent.core.graph.nodes.held_appointment_info import node_held_appointment_info
from voice_agent.core.graph.nodes.planner import collect_directives
from voice_agent.core.types import (
    AssistantPhase,
    AppointmentStatus,
    AppointmentField,
    ConfirmationTopic,
    DirectiveKind,
)


def test_collect_directives_skips_stale_held_confirmation_on_schedule_change():
    state = {
        "user_text": "can i change it to tomorrow afternoon",
        "assistant_phase": AssistantPhase.HOLDING_APPOINTMENT,
        "appointment_draft": {
            "status": AppointmentStatus.HELD,
        },
        "node_data": {
            "held_appointment_info": {
                "exclusive_directives": True,
                "directives": [
                    {
                        "kind": DirectiveKind.INFORM_HELD,
                        "priority": 100,
                    },
                    {
                        "kind": DirectiveKind.REQUEST_CONFIRMATION,
                        "confirmation_topic": ConfirmationTopic.HOLD_CONFIRMATION,
                        "priority": 90,
                    },
                ],
            },
            "time_slot": {
                "directives": [
                    {
                        "kind": DirectiveKind.REQUEST_MISSING_INFO,
                        "field": AppointmentField.REQUESTED_TIME_TEXT,
                        "priority": 70,
                    }
                ]
            },
        },
    }

    directives = collect_directives(state)

    assert directives == [
        {
            "kind": DirectiveKind.REQUEST_MISSING_INFO,
            "field": AppointmentField.REQUESTED_TIME_TEXT,
            "priority": 70,
        }
    ]


@pytest.mark.asyncio
async def test_held_appointment_info_clears_stale_directives_after_acceptance():
    state = {
        "appointment_draft": {
            "status": AppointmentStatus.HELD,
            "offered_time_confirmed": True,
        },
    }

    local_state = await node_held_appointment_info(state)

    assert local_state["node_data"]["held_appointment_info"]["directives"] == []
    assert local_state["node_data"]["held_appointment_info"]["exclusive_directives"] is False
