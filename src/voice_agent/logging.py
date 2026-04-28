import logging
import os
import colorlog


class SafeExtraFormatter(colorlog.ColoredFormatter):
    def format(self, record):
        for key in ("call_id", "node", "phase"):
            if not hasattr(record, key):
                setattr(record, key, "-")
        return super().format(record)


def setup_logging():
    level = os.getenv("LOG_LEVEL", "DEBUG").upper()

    handler = colorlog.StreamHandler()

    formatter = SafeExtraFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s] [%(name)s] "
        "call_id=%(call_id)s node=%(node)s phase=%(phase)s %(message)s",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    )

    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)