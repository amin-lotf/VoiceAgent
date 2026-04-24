from enum import StrEnum
from typing import TypedDict

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.types import AssistantPhase, NextAction, AssistantIntent

OPERATOR_OUTPUT_SCHEMA = {
    AssistantPhase.COLLECTING_USER_INTENT: {
        "assistant_intent": AssistantIntent.CONTINUE,
        "user_intent": NOT_SPECIFIED,
        "next_action": NextAction.ASK_USER
    },
    AssistantPhase.COLLECTING_INFO: {
        "assistant_intent": AssistantIntent.CONTINUE,
        "next_action": NextAction.ASK_USER
    },
    AssistantPhase.VERIFYING_INFO: {
        "assistant_intent": AssistantIntent.CONTINUE,
        "next_action": NextAction.ASK_USER,
    },
    AssistantPhase.CONFIRMING_SLOT: {
        "assistant_intent": AssistantIntent.CONTINUE,
        "next_action": NextAction.ASK_USER,
    },
    AssistantPhase.BOOKING_APPOINTMENT: {
        "assistant_intent": AssistantIntent.CONTINUE,
        "next_action": NextAction.BOOK_APPOINTMENT,
    },
    AssistantPhase.COLLECTING_NOTES: {
        "assistant_intent": AssistantIntent.CONTINUE,
        "notes": [],
    },
}

INFO_EXTRACTOR_OUTPUT_SCHEMA = {
    "name": NOT_SPECIFIED,
    "phone": NOT_SPECIFIED,
    "reason_for_visit": NOT_SPECIFIED,
    "requested_time_text": NOT_SPECIFIED,
    "notes": [],
}

DATETIME_EXTRACTOR_OUTPUT_SCHEMA = {
    "schedule_patch": {
        "date_mode": NOT_SPECIFIED,
        "date_key": NOT_SPECIFIED,
        "time_pref": NOT_SPECIFIED,
        "exact_time_text": NOT_SPECIFIED,
        "relative_to_offered": NOT_SPECIFIED,
    }
}
