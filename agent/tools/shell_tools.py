import subprocess
from .base import BaseTool


class ShellTool(BaseTool):
    name = "run_shell"
    description = (
        "Execute a shell command and return stdout + stderr. "
        "Use for file operations, git, package management, running scripts, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute."},
            "cwd": {"type": "string", "description": "Working directory. Default: current dir."},
            "timeout": {"type": "integer", "description": "Timeout in seconds. Default: 30."},
        },
        "required": ["command"],
    }

    def __init__(self, timeout: int = 30):
        self._timeout = timeout

    def execute(self, command: str, cwd: str = None, timeout: int = None) -> str:
        t = timeout or self._timeout
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=t,
                cwd=cwd,
            )
            out = result.stdout.strip()
            err = result.stderr.strip()
            parts = []
            if out:
                parts.append(out)
            if err:
                parts.append(f"[stderr]\n{err}")
            if result.returncode != 0:
                parts.append(f"[exit code: {result.returncode}]")
            return "\n".join(parts) if parts else "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {t}s"
        except Exception as e:
            return f"Error running command: {e}"
