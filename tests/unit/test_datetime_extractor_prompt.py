from datetime import datetime
from zoneinfo import ZoneInfo

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.prompts.datetime_extractor import build_time_resolution_prompt


def test_time_resolution_prompt_exposes_contextual_day_anchor_for_bare_time_updates():
    messages = build_time_resolution_prompt(
        state={
            "appointment_draft": {
                "requested_time_text": "at 1pm",
                "requested_time_iso": "2026-04-16T09:00:00+08:00",
                "last_offered_slot_start_at": "2026-04-16T09:00:00+08:00",
            },
            "prev_user_text": "tomorrow morning works",
            "prev_assistant_text": "I can hold tomorrow morning at 9.",
        },
        now=datetime(2026, 4, 15, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        tz_info=ZoneInfo("Asia/Taipei"),
    )

    system_content = messages[0].content
    human_content = messages[1].content

    assert "If requested_time_text only changes the time or time-of-day" in system_content
    assert 'requested_time_text: "at 1 pm"' in system_content
    assert "existing_requested_date_key: 2026-04-16" in human_content
    assert "offered_slot_date_key: 2026-04-16" in human_content
    assert "established_context_date_key: 2026-04-16" in human_content


def test_time_resolution_prompt_marks_missing_context_anchor_as_not_specified():
    messages = build_time_resolution_prompt(
        state={
            "appointment_draft": {
                "requested_time_text": "1pm",
                "requested_time_iso": "not-a-datetime",
            },
        },
        now=datetime(2026, 4, 15, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        tz_info=ZoneInfo("Asia/Taipei"),
    )

    human_content = messages[1].content

    assert f"existing_requested_date_key: {NOT_SPECIFIED}" in human_content
    assert f"established_context_date_key: {NOT_SPECIFIED}" in human_content
