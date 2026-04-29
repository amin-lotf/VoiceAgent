# voice_agent/utils/logging.py

import logging
import os


RESET = "\033[0m"

LEVEL_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;31m",
}

# NODE_COLOR = "\033[35m"   # purple
# PHASE_COLOR = "\033[34m"  # blue


class AgentFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # defaults
        for key in ("call_id", "node", "phase"):
            if not hasattr(record, key):
                setattr(record, key, "-")

        # --- color level ---
        original_levelname = record.levelname
        level_color = LEVEL_COLORS.get(original_levelname, "")
        if level_color:
            record.levelname = f"{level_color}{original_levelname}:{RESET}"

        # --- color node & phase VALUES only ---
        original_node = record.node
        original_phase = record.phase
        if level_color:
            record.node = f"{level_color}{original_node}{RESET}"
            record.phase = f"{level_color}{original_phase}{RESET}"

        try:
            return super().format(record)
        finally:
            # restore originals (important)
            record.levelname = original_levelname
            record.node = original_node
            record.phase = original_phase


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "DEBUG").upper()

    handler = logging.StreamHandler()
    handler.setFormatter(
        AgentFormatter(
            "%(levelname)-18s %(asctime)s  "
            "[%(name)s] call_id=%(call_id)s "
            "node=%(node)s phase=%(phase)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
    logging.getLogger("voice_agent").setLevel(logging.DEBUG)

    for noisy_logger in (
            "httpcore",
            "httpx",
            "openai",
            "urllib3",
            "asyncio",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)