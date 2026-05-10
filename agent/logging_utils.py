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


def configure_logging() -> None:
    level_name = (os.getenv("APEXFORGE_LOG_LEVEL") or "INFO").upper()
    log_format = (os.getenv("APEXFORGE_LOG_FORMAT") or "text").strip().lower()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    formatter = ApexSwarmFormatter(json_mode=(log_format == "json"))
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root.addHandler(handler)
        return

    for handler in root.handlers:
        handler.setFormatter(formatter)
        handler.setLevel(level)


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    payload: Dict[str, Any] = {"event": event}
    for key, value in fields.items():
        payload[key] = _safe_value(value)
    logger.log(level, event, extra={"apexforge_payload": payload})
