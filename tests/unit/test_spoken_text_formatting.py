from voice_agent.core.graph.utils import (
    SpokenTextStreamNormalizer,
    iso_to_human_readable,
    sanitize_spoken_text,
)


def test_iso_to_human_readable_uses_part_of_day_words():
    assert (
        iso_to_human_readable("2026-04-16T10:30:00+08:00")
        == "Thursday, April 16 at 10:30 in the morning"
    )
    assert (
        iso_to_human_readable("2026-04-16T15:00:00+08:00")
        == "Thursday, April 16 at 3:00 in the afternoon"
    )


def test_sanitize_spoken_text_removes_special_symbols_and_meridiem_labels():
    text = (
        "Perfect—Thursday, April 16 at 10:30 AM works.All set—your appointment is booked under Jack."
    )

    sanitized = sanitize_spoken_text(text)

    assert sanitized == (
        "Perfect. Thursday, April 16 at 10:30 in the morning works. "
        "All set. Your appointment is booked under Jack."
    )
    assert "—" not in sanitized
    assert "AM" not in sanitized


def test_sanitize_spoken_text_keeps_hour_only_times_natural():
    sanitized = sanitize_spoken_text("Our hours are Mon–Fri 9 AM–5 PM.")

    assert sanitized == "Our hours are Mon to Fri 9 in the morning to 5 in the afternoon."



def test_stream_normalizer_preserves_chunked_time_cleanup():
    normalizer = SpokenTextStreamNormalizer(tail_chars=24)

    first = normalizer.push("There's a slot available on Thursday, April 16 at 10:30 A")
    second = normalizer.push("M. Does that work for you?")
    trailing = normalizer.flush()

    combined = f"{first}{second}{trailing}".strip()

    assert combined == (
        "There's a slot available on Thursday, April 16 at 10:30 in the morning. "
        "Does that work for you?"
    )
