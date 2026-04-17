from voice_agent.core.prompts.call_operator import build_operator_prompt
from voice_agent.core.types import AppointmentField, AppointmentStatus, DirectiveKind


def test_prompt_turns_slot_acceptance_into_booking_ack_only():
    state = {
        "messages": [
            {
                "role": "assistant",
                "content": "There's a slot available on Thursday, April 16 at 10:00 in the morning. Does that work for you?",
            }
        ],
        "prev_assistant_text": "There's a slot available on Thursday, April 16 at 10:00 in the morning. Does that work for you?",
        "user_text": "yes",
        "directives": [
            {
                "kind": DirectiveKind.INFORM_HELD,
                "priority": 100,
            },
            {
                "kind": DirectiveKind.REQUEST_CONFIRMATION,
                "priority": 90,
            },
        ],
        "appointment_draft": {
            "status": AppointmentStatus.HELD,
        },
        "node_data": {
            "directive_prompt_builder": {
                "rules": [
                    "Tell the caller that a slot is available.",
                    "Ask whether the offered date and time works for the caller.",
                ]
            }
        },
    }

    prompt = build_operator_prompt(state)
    system_content = prompt[0].content

    assert "Caller Now is accepting the currently offered slot." in system_content
    assert "Do not say that a slot is available again." in system_content
    assert "Do not ask whether the slot works again." in system_content
    assert "Reply with one short booking-progress acknowledgment only" in system_content
    assert "Do not ask another question in this turn." in system_content


def test_prompt_prioritizes_schedule_change_over_note_follow_up():
    state = {
        "messages": [
            {
                "role": "assistant",
                "content": "Would you like us to note anything for the appointment?",
            }
        ],
        "prev_assistant_text": "Would you like us to note anything for the appointment?",
        "user_text": "Can I change it to tomorrow afternoon?",
        "directives": [
            {
                "field": AppointmentField.NOTES,
                "kind": DirectiveKind.REQUEST_MISSING_INFO,
                "priority": 90,
            }
        ],
        "appointment_draft": {
            "status": AppointmentStatus.SCHEDULED,
        },
        "node_data": {
            "directive_prompt_builder": {
                "rules": [
                    "Ask whether the caller wants anything noted for the appointment.",
                ]
            }
        },
    }

    prompt = build_operator_prompt(state)
    system_content = prompt[0].content

    assert "Caller Now is changing the appointment date or time." in system_content
    assert "Do not continue any earlier notes or post-booking follow-up question in this turn." in system_content
    assert "Reply with one short neutral scheduling acknowledgment only" in system_content
    assert "Do not confirm availability yet and do not ask another question in this turn." in system_content


def test_internal_booking_prompt_uses_booking_progress_after_acceptance():
    state = {
        "messages": [
            {
                "role": "assistant",
                "content": "There's a slot available on Thursday, April 16 at 12:00 PM. Does that work for you?",
            },
            {
                "role": "user",
                "content": "yes",
            },
        ],
        "prev_assistant_text": "There's a slot available on Thursday, April 16 at 12:00 PM. Does that work for you?",
        "prev_user_text": "yes",
        "directives": [
            {
                "kind": DirectiveKind.INFORM_SCHEDULED,
                "priority": 100,
            },
            {
                "field": AppointmentField.NOTES,
                "kind": DirectiveKind.REQUEST_MISSING_INFO,
                "priority": 90,
            },
        ],
        "appointment_draft": {
            "status": AppointmentStatus.SCHEDULED,
            "name": "Jack",
        },
        "node_data": {
            "directive_prompt_builder": {
                "rules": [
                    "Tell the caller that the appointment is successfully booked.",
                    "Ask whether the caller wants anything noted for the appointment.",
                ]
            }
        },
    }

    prompt = build_operator_prompt(state, internal_call=True)
    system_content = prompt[0].content

    assert "The previous caller turn already accepted the offered slot." in system_content
    assert "Do not say that a slot is available again." in system_content
    assert "Start with a short booking-progress acknowledgment" in system_content
    assert "Do not say lines like '<date and time> works.'" in system_content
    assert "If one follow-up question is still required, ask it only after the booking-progress acknowledgment." in system_content
    assert "Use exactly one short booking sentence before the follow-up question." in system_content


def test_internal_booking_prompt_skips_duplicate_progress_ack_when_already_given():
    state = {
        "messages": [
            {
                "role": "assistant",
                "content": "Perfect, I'll book that for you now.",
            },
            {
                "role": "user",
                "content": "yes",
            },
        ],
        "prev_assistant_text": "Perfect, I'll book that for you now.",
        "prev_user_text": "yes",
        "directives": [
            {
                "kind": DirectiveKind.INFORM_SCHEDULED,
                "priority": 100,
            },
            {
                "field": AppointmentField.NOTES,
                "kind": DirectiveKind.REQUEST_MISSING_INFO,
                "priority": 90,
            },
        ],
        "appointment_draft": {
            "status": AppointmentStatus.SCHEDULED,
            "name": "Jack",
        },
        "node_data": {
            "directive_prompt_builder": {
                "rules": [
                    "Tell the caller that the appointment is successfully booked.",
                    "Ask whether the caller wants anything noted for the appointment.",
                ]
            }
        },
    }

    prompt = build_operator_prompt(state, internal_call=True)
    system_content = prompt[0].content

    assert "The previous assistant turn already acknowledged that the booking is being completed." in system_content
    assert "Do not repeat another booking-progress acknowledgment" in system_content
