from __future__ import annotations

import sys
from voice_agent.proc import popen


def run(*, host: str = "0.0.0.0", port: int = 8000, reload: bool = True):
    api_cmd = [
        sys.executable, "-m", "uvicorn",
        "voice_agent.core.api.v1.fastapi_app:app",
        "--host", host,
        "--port", str(port),
        "--log-level", "info",
    ]
    if reload:
        api_cmd.append("--reload")

    print(f"[voice_agent] API: http://{host}:{port}")
    return popen(api_cmd)
