from voice_agent.core.db.models import Appointment
from voice_agent.core.types import AppointmentView


def to_view(a:Appointment) -> AppointmentView:
    return {
        "id": a.id,
        "name": a.name or "",
        "phone": a.phone or "",
        "reason_for_visit": a.reason_for_visit or "",
        "start_at": a.start_at.isoformat() if a.start_at else None,
        "end_at": a.end_at.isoformat() if a.end_at else None,
        "notes": list(a.notes or []),
        "status": a.status,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
    }
