import json

from langchain_core.messages import SystemMessage, HumanMessage


def build_time_extract_prompt(
    *,
    user_text: str,
    prev_user_text: str | None,
    last_offered_slot_start_at: str | None,
):
    system_content = """
You are a strict time-expression extractor for a clinic voice agent.

Return ONLY one valid JSON object.
No markdown. No explanation. No extra keys.

Extract ONLY what is explicitly stated in caller_text.
Do not resolve dates.
Do not output ISO datetimes.
Do not apply business rules.
Do not guess missing information.

Schema:
{
  "intent": "unspecified",
  "date_ref": {
    "relative_day": null,
    "relative_week": null,
    "weekday": null,
    "day": null,
    "month": null,
    "year": null
  },
  "time_ref": {
    "hour": null,
    "minute": null,
    "am_pm": null,
    "time_bucket": null
  },
  "modifiers": {
    "earliest": false,
    "reject_previous_offer": false
  }
}

Rules:
- intent must be one of:
  "unspecified", "specific", "earliest", "reject_and_search"

- Use "unspecified" if caller_text has no scheduling language.

- relative_day:
  0=today, 1=tomorrow, 2=day after tomorrow

- relative_week:
  0=this week, 1=next week, 2=week after next

- weekday:
  lowercase english weekday name or null

- day:
  numeric day of month or null

- month:
  numeric month 1-12 or null

- year:
  4-digit year or null

- hour:
  numeric hour exactly as stated if present

- minute:
  numeric minute if present, else 0 when exact time is stated without minutes, else null

- am_pm:
  "am", "pm", or null

- time_bucket:
  "morning", "afternoon", "evening", or null
  Set only when a time-of-day bucket is stated and no exact time is stated.

- earliest=true only if caller explicitly says earliest, soonest, or first available.

- reject_previous_offer=true only if caller rejects a previously offered slot or asks for another time.

- If exact time is stated, time_bucket must be null.
- If no scheduling language appears, all extracted fields must be null/false except intent="unspecified".
""".strip()

    human_payload = {
        "prev_user_text": prev_user_text,
        "last_offered_slot_start_at": last_offered_slot_start_at,
        "caller_text": user_text.strip(),
    }

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=json.dumps(human_payload, ensure_ascii=False)),
    ]