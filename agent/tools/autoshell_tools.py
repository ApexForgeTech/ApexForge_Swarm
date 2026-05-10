import subprocess
from .base import BaseTool


class AutoShellTool(BaseTool):
    name = "auto_shell"
    description = (
        "Execute a restricted set of shell commands. Supports safe read/list operations."
    )
    # Very conservative whitelist to avoid dangerous operations
    WHITELIST = {
        "pwd",
        "ls",
        "date",
        "whoami",
        "echo",
        "cat",
        "head",
        "tail",
        "grep",
        "wc",
        "cut",
        "sort",
        "uniq",
        # Some directory/file operations that are relatively safe
        "mkdir",
        "rmdir",
        "cp",
        "mv",
        "rm",
        "touch",
    }
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute (restricted)."},
            "cwd": {"type": "string", "description": "Working directory. Optional."},
            "timeout": {"type": "integer", "description": "Timeout in seconds. Optional."},
        },
        "required": ["command"],
    }

    def __init__(self, default_timeout: int = 30):
        self._default_timeout = max(0, int(default_timeout))

    def execute(self, command: str, cwd: str = None, timeout: int = None) -> str:
        t = timeout if timeout is not None else self._default_timeout
        # Basic whitelisting based on the first token
        if not command:
            return "(no command)"
        first = command.strip().split()[0]
        if first not in self.WHITELIST:
            return f"Error: command '{first}' is not allowed in AutoShell."
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
