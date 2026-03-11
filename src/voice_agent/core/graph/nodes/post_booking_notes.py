from __future__ import annotations

import logging
import re
from typing import Any

from langgraph.config import get_stream_writer
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork

from voice_agent.core.graph.nodes.utils import parse_date, format_date
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.services.appointments import update_appointment_notes
from voice_agent.core.services.exceptions import NotFound
from voice_agent.core.types import CallState, AppointmentView

logger = logging.getLogger(__name__)


def _stream_response(state: CallState, text: str) -> None:
    state["assistant_text"] = text
    writer = get_stream_writer()
    if writer:
        for word in text.split():
            writer(("assistant_token", word + " "))
        state["assistant_streamed"] = True

def _finalize_response(
        state: CallState,
        text: str,
        *,
        speak: bool = True,
) -> CallState:


    if speak:
        _stream_response(state, text)
        state["assistant_text"] = text
    else:
        state["assistant_text"] = ""
        state["assistant_streamed"] = False

    return state


def _coerce_notes(raw: Any) -> list[str]:
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        items = [raw]
    elif raw is None:
        items = []
    else:
        items = [str(raw)]
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            item = str(item)
        cleaned = item.strip()
        if cleaned:
            out.append(cleaned)
    return out


def _dedupe_notes(notes: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for note in notes:
        key = note.strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(note.strip())
    return out


def _looks_like_no_additional_notes(user_text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9' ]+", " ", (user_text or "").casefold())
    normalized = " ".join(normalized.split())
    if not normalized:
        return True

    if normalized in {
        "no",
        "nope",
        "nah",
        "yes",
        "yeah",
        "yep",
        "ok",
        "okay",
        "sure",
        "none",
        "nothing",
        "nothing else",
        "that is all",
        "thats all",
        "that's all",
        "all good",
        "no thanks",
        "no thank you",
    }:
        return True

    medical_cues = (
        "allerg",
        "condition",
        "diabet",
        "asthma",
        "pregnan",
        "blood pressure",
        "medication",
        "pain",
        "fever",
        "cough",
        "history",
        "surgery",
        "wheelchair",
        "accessibility",
    )
    if normalized.startswith("no ") and len(normalized.split()) <= 6:
        if not any(cue in normalized for cue in medical_cues):
            return True
    return False


def _extract_post_booking_notes(user_text: str) -> list[str]:
    text = (user_text or "").strip()
    if not text:
        return []

    parts = re.split(r"(?:,|;|\band\b|\balso\b|\bplus\b|\n|\.)", text, flags=re.IGNORECASE)
    notes: list[str] = []
    for part in parts:
        chunk = part.strip(" \t\n\r.,;:!?")
        if not chunk:
            continue
        folded = chunk.casefold()
        if folded in {"yes", "yeah", "yep", "ok", "okay", "sure"}:
            continue
        if folded in {"no", "none", "nothing", "nothing else", "that's all", "thats all"}:
            continue
        notes.append(chunk)

    if not notes:
        if text.casefold() in {"yes", "yeah", "yep", "ok", "okay", "sure"}:
            return []
        notes = [text]
    return _dedupe_notes(notes)


async def node_post_booking_notes_node(
        state: CallState, *, sessionmaker: async_sessionmaker[AsyncSession]
) -> CallState:
    appointment = state.setdefault("appointment_draft", {})
    user_text = (state.get("user_text") or "").strip()
    start_at = parse_date(appointment.get("start_at"))
    when_text = format_date(start_at) if start_at else "your appointment time"

    if _looks_like_no_additional_notes(user_text):
        return _finalize_response(
            state,
            f"If nothing else, see you at {when_text}.",
        )

    new_notes = _extract_post_booking_notes(user_text)
    if not new_notes:
        return _finalize_response(
            state,
            f"If nothing else, see you at {when_text}.",
        )

    existing_notes = _coerce_notes(appointment.get("notes"))
    merged_notes = _dedupe_notes(existing_notes + new_notes)
    appointment["notes"] = merged_notes

    view = state.get("appointment_view") or {}
    appt_id = view.get("id") if isinstance(view, dict) else None

    async def _commit() -> AppointmentView:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            return await update_appointment_notes(
                uow,
                appointment_id=int(appt_id),
                notes=merged_notes,
            )

    if appt_id:
        try:
            updated_view = await run_non_interruptible(state, _commit)
            state["appointment_view"] = updated_view if isinstance(updated_view, dict) else view
        except NotFound:
            logger.info("post_booking_notes update skipped: appointment not found %s", appt_id)
        except Exception:
            logger.exception("post_booking_notes update failed for %s", appt_id)

    return _finalize_response(
        state,
        f"Noted. If nothing else, see you at {when_text}.",

    )
