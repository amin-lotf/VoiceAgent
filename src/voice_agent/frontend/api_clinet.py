import time
from dataclasses import dataclass

import httpx
import requests

class ApiError(RuntimeError):
    """Raised when an HTTP/API error occurs, with a human-readable message."""




def unwrap_error(e: Exception) -> str:
    """Extract a human-readable error message from httpx exceptions."""
    if isinstance(e, httpx.HTTPStatusError):
        # The request reached the server, but the response had an error code
        try:
            data = e.response.json()
            detail = data.get("detail") if isinstance(data, dict) else data
            return f"{e.response.status_code} {e.response.reason_phrase}: {detail}"
        except Exception:
            return f"{e.response.status_code} {e.response.reason_phrase}"

    elif isinstance(e, httpx.RequestError):
        # Connection errors, timeouts, DNS failures, etc.
        return f"Request failed: {e.__class__.__name__}: {e}"

    elif isinstance(e, httpx.TimeoutException):
        return "Request timed out."

    elif isinstance(e, httpx.ConnectError):
        return "Failed to connect to server. Is it running?"

    else:
        # Anything unexpected
        return str(e)


def handle_httpx_errors(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Wrap any error into a consistent ApiError
            raise ApiError(unwrap_error(e)) from e

    return wrapper


@dataclass(frozen=True)
class SessionView:
    status: str


@dataclass(frozen=True)
class CallTurnView:
    role: str
    content: str
    created_at: str | None
    total_tokens: int | None
    total_delay_s: float | None
    first_token_delay_s: float | None


@dataclass(frozen=True)
class CallSummaryView:
    call_id: str
    started_at: str
    ended_at: str | None
    duration_seconds: int | None
    final_status: str | None
    total_tokens: int
    avg_total_delay_s: float | None
    avg_first_token_delay_s: float | None


@dataclass(frozen=True)
class ScheduledAppointmentView:
    id: int
    name: str | None
    phone: str | None
    reason_for_visit: str | None
    start_at: str | None
    end_at: str | None
    notes: list[str]
    status: str | None
    patient_type: str | None
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True)
class CallDetailView(CallSummaryView):
    turns: list[CallTurnView]
    scheduled_appointment: ScheduledAppointmentView | None = None


class ApiClient:
    def __init__(self, base_url: str, timeout_s: float = 120.0) -> None:
        """
        Initialize API client.

        Args:
            base_url: Base URL of the Smart Interviewer API
            timeout_s: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    @handle_httpx_errors
    def health(self) -> dict:
        r = requests.get(f"{self.base_url}/", timeout=self.timeout_s)
        r.raise_for_status()
        return r.json()

    @handle_httpx_errors
    def get_state(self, *, session_id: str, retry_count: int = 5, retry_delay: float = 0.5) -> SessionView:
        last_exception: Exception | None = None

        for attempt in range(retry_count):
            try:
                r = requests.get(
                    f"{self.base_url}/session/state",
                    timeout=self.timeout_s,
                    headers={"X-Session-Id": session_id},
                )

                # Retry transient server/proxy errors
                if r.status_code in (502, 503, 504):
                    raise requests.HTTPError(f"Transient HTTP {r.status_code}", response=r)

                r.raise_for_status()
                return self._parse(r.json())

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.HTTPError) as e:
                # Don't retry on real client errors (except 429)
                if isinstance(e, requests.HTTPError) and e.response is not None:
                    code = e.response.status_code
                    if 400 <= code < 500 and code != 429:
                        raise

                last_exception = e
                if attempt < retry_count - 1:
                    time.sleep(retry_delay * (2 ** attempt))
                continue

        raise last_exception  # type: ignore

    @staticmethod
    def _parse(j: dict) -> SessionView:
        return SessionView(
            status=j.get("status", "ok"),
        )

    @handle_httpx_errors
    def list_calls(self, *, limit: int = 50) -> list[CallSummaryView]:
        r = requests.get(
            f"{self.base_url}/calls",
            timeout=self.timeout_s,
            params={"limit": limit},
        )
        r.raise_for_status()
        payload = r.json()
        return [self._parse_call_summary(item) for item in payload]

    @handle_httpx_errors
    def get_call(self, *, call_id: str) -> CallDetailView:
        r = requests.get(
            f"{self.base_url}/calls/{call_id}",
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        return self._parse_call_detail(r.json())

    @staticmethod
    def _parse_call_summary(j: dict) -> CallSummaryView:
        return CallSummaryView(
            call_id=j.get("call_id", ""),
            started_at=j.get("started_at", ""),
            ended_at=j.get("ended_at"),
            duration_seconds=j.get("duration_seconds"),
            final_status=j.get("final_status"),
            total_tokens=j.get("total_tokens") or 0,
            avg_total_delay_s=j.get("avg_total_delay_s"),
            avg_first_token_delay_s=j.get("avg_first_token_delay_s"),
        )

    @staticmethod
    def _parse_call_turn(j: dict) -> CallTurnView:
        return CallTurnView(
            role=j.get("role", ""),
            content=j.get("content", ""),
            created_at=j.get("created_at"),
            total_tokens=j.get("total_tokens"),
            total_delay_s=j.get("total_delay_s"),
            first_token_delay_s=j.get("first_token_delay_s"),
        )

    @staticmethod
    def _parse_scheduled_appointment(j: dict | None) -> ScheduledAppointmentView | None:
        if not j or j.get("id") is None:
            return None
        return ScheduledAppointmentView(
            id=int(j.get("id")),
            name=j.get("name"),
            phone=j.get("phone"),
            reason_for_visit=j.get("reason_for_visit"),
            start_at=j.get("start_at"),
            end_at=j.get("end_at"),
            notes=list(j.get("notes") or []),
            status=j.get("status"),
            patient_type=j.get("patient_type"),
            created_at=j.get("created_at"),
            updated_at=j.get("updated_at"),
        )

    @classmethod
    def _parse_call_detail(cls, j: dict) -> CallDetailView:
        summary = cls._parse_call_summary(j)
        return CallDetailView(
            call_id=summary.call_id,
            started_at=summary.started_at,
            ended_at=summary.ended_at,
            duration_seconds=summary.duration_seconds,
            final_status=summary.final_status,
            total_tokens=summary.total_tokens,
            avg_total_delay_s=summary.avg_total_delay_s,
            avg_first_token_delay_s=summary.avg_first_token_delay_s,
            turns=[cls._parse_call_turn(turn) for turn in j.get("turns", [])],
            scheduled_appointment=cls._parse_scheduled_appointment(j.get("scheduled_appointment")),
        )
