from __future__ import annotations

import time

from voice_agent.core.api.v1.runner import run as api_run
from voice_agent.frontend.runner import run as ui_run
from voice_agent.proc import terminate_tree

HOST= '127.0.0.1'
# HOST= '0.0.0.0'
def main() -> None:
    api_proc = api_run(host=HOST, port=8000, reload=True)
    ui_proc = ui_run(port=8501, address=HOST)

    try:
        while True:
            api_rc = api_proc.poll()
            ui_rc = ui_proc.poll()

            # If either dies, kill the other and exit with a helpful error
            if api_rc is not None:
                raise SystemExit(f"[voice_agent] API exited with code {api_rc}")
            if ui_rc is not None:
                raise SystemExit(f"[voice_agent] UI exited with code {ui_rc}")

            time.sleep(0.3)

    except KeyboardInterrupt:
        print("\n[voice_agent] Ctrl+C received, shutting down...")
    finally:
        terminate_tree(ui_proc)
        terminate_tree(api_proc)


if __name__ == "__main__":
    main()
