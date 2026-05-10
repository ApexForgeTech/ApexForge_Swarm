import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict


def _safe_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 400:
            return value[:397] + "..."
        return value
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item) for item in list(value)[:20]]
    return repr(value)


class ApexSwarmFormatter(logging.Formatter):
    def __init__(self, *, json_mode: bool = False):
        super().__init__()
        self.json_mode = json_mode

    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "apexforge_payload", None)
        if payload:
            base = {
                "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                **payload,
            }
            if self.json_mode:
                return json.dumps(base, ensure_ascii=True, sort_keys=True)

            fields = " ".join(
                f"{key}={json.dumps(value, ensure_ascii=True)}"
                for key, value in base.items()
                if key not in {"ts", "level", "logger", "event"}
            )
            event = base.get("event", record.getMessage())
            if fields:
                return f"{base['ts']} [{base['level']}] {base['logger']} {event} | {fields}"
            return f"{base['ts']} [{base['level']}] {base['logger']} {event}"

        return super().format(record)


def configure_logging(mode: str = "cli") -> None:
    """
    mode="cli"  → WARNING+ to stderr only (keeps the terminal clean)
    mode="web"  → INFO+ to stderr (server log)
    mode="file" → INFO+ to apexforge.log
    env var APEXFORGE_LOG_LEVEL overrides the level.
    env var APEXFORGE_LOG_FORMAT sets "text" or "json".
    """
    log_format = (os.getenv("APEXFORGE_LOG_FORMAT") or "text").strip().lower()

    if os.getenv("APEXFORGE_LOG_LEVEL"):
        level = getattr(logging, os.getenv("APEXFORGE_LOG_LEVEL").upper(), logging.WARNING)
    elif mode == "cli":
        level = logging.WARNING
    else:
        level = logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    formatter = ApexSwarmFormatter(json_mode=(log_format == "json"))

    if mode == "file":
        handler = logging.FileHandler("apexforge.log", encoding="utf-8")
    else:
        import sys
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(formatter)
    handler.setLevel(level)

    if not root.handlers:
        root.addHandler(handler)
        return

    for h in root.handlers:
        h.setFormatter(formatter)
        h.setLevel(level)


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    payload: Dict[str, Any] = {"event": event}
    for key, value in fields.items():
        payload[key] = _safe_value(value)
    logger.log(level, event, extra={"apexforge_payload": payload})
