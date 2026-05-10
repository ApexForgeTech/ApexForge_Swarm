import subprocess
import sys
import shutil
from .base import BaseTool


class PythonTool(BaseTool):
    name = "run_python"
    description = (
        "Execute Python code and return the output. "
        "Use for calculations, data processing, file parsing, automation scripts, and system/file automation."
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute."},
            "timeout": {"type": "integer", "description": "Timeout in seconds. Default: 30."},
        },
        "required": ["code"],
    }

    def __init__(self, timeout: int = 30):
        self._timeout = timeout

    def execute(self, code: str, timeout: int = None) -> str:
        t = timeout or self._timeout
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=t,
            )
            out = result.stdout.strip()
            err = result.stderr.strip()
            parts = []
            if out:
                parts.append(out)
            if err:
                parts.append(f"[stderr]\n{err}")
            if result.returncode != 0 and not err:
                parts.append(f"[exit code: {result.returncode}]")
            return "\n".join(parts) if parts else "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: code timed out after {t}s"
        except Exception as e:
            return f"Error: {e}"


class JavaScriptTool(BaseTool):
    name = "run_javascript"
    description = (
        "Execute JavaScript code with Node.js and return the output. "
        "Use for JavaScript logic, JSON/text transformation, Node ecosystem tasks, or as an alternative runtime."
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "JavaScript code to execute."},
            "timeout": {"type": "integer", "description": "Timeout in seconds. Default: 30."},
        },
        "required": ["code"],
    }

    def __init__(self, timeout: int = 30):
        self._timeout = timeout

    def execute(self, code: str, timeout: int = None) -> str:
        t = timeout or self._timeout
        node = shutil.which("node")
        if not node:
            return "Error: Node.js is not installed or not found in PATH."
        try:
            result = subprocess.run(
                [node, "-e", code],
                capture_output=True,
                text=True,
                timeout=t,
            )
            out = result.stdout.strip()
            err = result.stderr.strip()
            parts = []
            if out:
                parts.append(out)
            if err:
                parts.append(f"[stderr]\n{err}")
            if result.returncode != 0 and not err:
                parts.append(f"[exit code: {result.returncode}]")
            return "\n".join(parts) if parts else "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: code timed out after {t}s"
        except Exception as e:
            return f"Error: {e}"
