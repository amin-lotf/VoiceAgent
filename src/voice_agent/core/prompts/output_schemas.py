from enum import StrEnum
from typing import TypedDict

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.types import AssistantPhase, NextAction, AssistantIntent

OPERATOR_OUTPUT_SCHEMA={
    AssistantPhase.COLLECTING_USER_INTENT:{
            "assistant_intent": AssistantIntent.CONTINUE,
            "user_intent": NOT_SPECIFIED,
        },
    AssistantPhase.COLLECTING_INFO:{
        "assistant_intent": AssistantIntent.CONTINUE,
        "next_action" : NextAction.ASK_USER
    }
}


INFO_EXTRACTOR_OUTPUT_SCHEMA={
    "name": NOT_SPECIFIED,
    "phone": NOT_SPECIFIED,
    "reason_for_visit": NOT_SPECIFIED,
    "requested_time_text": NOT_SPECIFIED,
    "notes": [],
}