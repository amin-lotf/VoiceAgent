from __future__ import annotations

import pytest
from pydantic import ValidationError

from voice_agent.core.settings import Settings


def test_settings_normalizes_blank_optional_strings_to_none() -> None:
    settings = Settings(
        OPENAI_API_KEY="   ",
        HUBSPOT_ACCESS_TOKEN="",
        HUBSPOT_DEAL_PIPELINE=" \t ",
        HUBSPOT_TICKET_STAGE="",
        HUBSPOT_TICKET_CANCELLED_STAGE="  ",
        HUBSPOT_TICKET_PIPELINE="\n",
    )

    assert settings.OPENAI_API_KEY is None
    assert settings.HUBSPOT_ACCESS_TOKEN is None
    assert settings.HUBSPOT_DEAL_PIPELINE is None
    assert settings.HUBSPOT_TICKET_STAGE is None
    assert settings.HUBSPOT_TICKET_CANCELLED_STAGE is None
    assert settings.HUBSPOT_TICKET_PIPELINE is None


def test_settings_rejects_blank_required_string_values() -> None:
    with pytest.raises(ValidationError):
        Settings(HUBSPOT_DEAL_CANCELLED_STAGE="")
