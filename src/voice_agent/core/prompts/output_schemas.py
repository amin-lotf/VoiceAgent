from enum import StrEnum
from typing import TypedDict

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.types import AssistantPhase

OPERATOR_OUTPUT_SCHEMA={
    AssistantPhase.COLLECTING_USER_INTENT:{
            "clinic_intent": "continue",
            "user_intent": NOT_SPECIFIED,
        }
}