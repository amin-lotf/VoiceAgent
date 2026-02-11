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