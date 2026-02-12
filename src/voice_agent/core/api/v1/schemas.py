from __future__ import annotations

from typing import Any, Literal, Optional, Union
from pydantic import BaseModel



# -------------------------
# Retell -> Your Server
# -------------------------
class RetellPingPongIn(BaseModel):
    interaction_type: Literal["ping_pong"]
    timestamp: int


class RetellUpdateOnlyIn(BaseModel):
    interaction_type: Literal["update_only"]
    transcript: list[dict[str, Any]]
    transcript_with_tool_calls: Optional[list[dict[str, Any]]] = None
    turntaking: Optional[Literal["agent_turn", "user_turn"]] = None


class RetellResponseRequiredIn(BaseModel):
    interaction_type: Literal["response_required", "reminder_required"]
    response_id: int
    transcript: list[dict[str, Any]]
    transcript_with_tool_calls: Optional[list[dict[str, Any]]] = None


RetellInbound = Union[RetellPingPongIn, RetellUpdateOnlyIn, RetellResponseRequiredIn]


# -------------------------
# Your Server -> Retell
# -------------------------
class RetellConfig(BaseModel):
    auto_reconnect: bool = True
    call_details: bool = False
    transcript_with_tool_calls: bool = False


class RetellConfigOut(BaseModel):
    response_type: Literal["config"] = "config"
    config: RetellConfig


class RetellPingPongOut(BaseModel):
    response_type: Literal["ping_pong"] = "ping_pong"
    timestamp: int


class RetellResponseOut(BaseModel):
    response_type: Literal["response"] = "response"
    response_id: int
    content: str
    content_complete: bool

    # optional controls supported by Retell:
    no_interruption_allowed: Optional[bool] = None
    end_call: Optional[bool] = None
    transfer_number: Optional[str] = None
    digit_to_press: Optional[str] = None