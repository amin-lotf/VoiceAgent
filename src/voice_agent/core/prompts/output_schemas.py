from enum import StrEnum
from typing import TypedDict

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.types import AssistantPhase, NextAction, AssistantIntent, UserIntent

OPERATOR_OUTPUT_SCHEMA = {
    AssistantPhase.COLLECTING_USER_INTENT: {
        "assistant_intent": f"{AssistantIntent.CONTINUE} | {AssistantIntent.HANGUP} | {AssistantIntent.HUMAN_HANDOFF}",
        "user_intent": f"{NOT_SPECIFIED} | {UserIntent.BOOK_APPOINTMENT} | {UserIntent.UNDECIDED}",
        "next_action": f"{NextAction.ASK_USER} | {NextAction.PROCESS_INTENT}"
    },
    AssistantPhase.COLLECTING_INFO: {
        "assistant_intent": f"{AssistantIntent.CONTINUE} | {AssistantIntent.HANGUP} | {AssistantIntent.HUMAN_HANDOFF}",
        "next_action": f"{NextAction.ASK_USER} | {NextAction.EXTRACT_INFO}"
    },
    AssistantPhase.VERIFYING_INFO: {
        "assistant_intent": f"{AssistantIntent.CONTINUE} | {AssistantIntent.HANGUP} | {AssistantIntent.HUMAN_HANDOFF}",
        "next_action": f"{NextAction.ASK_USER} | {NextAction.EXTRACT_INFO} | {NextAction.MARK_VERIFIED}"
    },
    AssistantPhase.CONFIRMING_SLOT: {
        "assistant_intent": f"{AssistantIntent.CONTINUE} | {AssistantIntent.HANGUP} | {AssistantIntent.HUMAN_HANDOFF}",
        "next_action":f"{NextAction.ASK_USER} | {NextAction.EXTRACT_INFO} | {NextAction.EXTRACT_DATETIME}",
        "requested_time_text": NOT_SPECIFIED,
    },
    AssistantPhase.BOOKING_APPOINTMENT: {
        "assistant_intent": f"{AssistantIntent.CONTINUE} | {AssistantIntent.HANGUP} | {AssistantIntent.HUMAN_HANDOFF}",
        "next_action": NextAction.BOOK_APPOINTMENT,
    },
    AssistantPhase.COLLECTING_NOTES: {
        "assistant_intent": f"{AssistantIntent.CONTINUE} | {AssistantIntent.HANGUP} | {AssistantIntent.HUMAN_HANDOFF}",
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
