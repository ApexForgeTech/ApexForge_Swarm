"""
Example plugin: datetime_tool
Returns current date/time in the requested timezone or format.
Drop this file in the plugins/ directory and it will be auto-loaded.
"""
from datetime import datetime, timezone

from agent.plugins import PluginTool


class DateTimeTool(PluginTool):
    name = "get_datetime"
    description = (
        "Return the current date and time. "
        "Optionally specify a format string (strftime) or 'utc' / 'local' timezone."
    )
    version = "1.0.0"
    author = "ApexForge Swarm"
    tags = ["utility", "time"]
    parameters = {
        "type": "object",
        "properties": {
            "tz": {
                "type": "string",
                "description": "'utc' (default) or 'local'",
                "default": "utc",
            },
            "fmt": {
                "type": "string",
                "description": "strftime format string, e.g. '%Y-%m-%d %H:%M:%S'",
                "default": "%Y-%m-%d %H:%M:%S",
            },
        },
        "required": [],
    }

    def execute(self, tz: str = "utc", fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        if tz.lower() == "local":
            now = datetime.now()
        else:
            now = datetime.now(timezone.utc)
        try:
            return now.strftime(fmt)
        except Exception as exc:
            return f"Error formatting datetime: {exc}"
