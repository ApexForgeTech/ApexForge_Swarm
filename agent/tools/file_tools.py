from pathlib import Path
from .base import BaseTool, strip_code_fence


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read the contents of a file from the filesystem."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path."},
        },
        "required": ["path"],
    }

    def execute(self, path: str) -> str:
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return f"Error: file not found: {path}"
            if p.stat().st_size > 500_000:
                return f"Error: file too large (>{500_000} bytes). Read in chunks."
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"Error reading file: {e}"


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write content to a file. Creates parent directories if needed."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to write to."},
            "content": {"type": "string", "description": "Content to write."},
            "append": {"type": "boolean", "description": "Append instead of overwrite. Default false."},
        },
        "required": ["path", "content"],
    }

    def execute(self, path: str, content: str, append: bool = False) -> str:
        try:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            content = strip_code_fence(content)
            p.write_text(content, encoding="utf-8") if not append else open(p, "a").write(content)
            return f"{'Appended to' if append else 'Written to'} {path} ({len(content)} chars)"
        except Exception as e:
            return f"Error writing file: {e}"


class ListDirTool(BaseTool):
    name = "list_directory"
    description = "List files and directories at a given path."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path. Default: current directory."},
            "pattern": {"type": "string", "description": "Glob pattern filter, e.g. '*.py'. Default: '*'."},
        },
        "required": [],
    }

    def execute(self, path: str = ".", pattern: str = "*") -> str:
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return f"Error: path not found: {path}"
            entries = sorted(p.glob(pattern))
            if not entries:
                return f"No entries matching '{pattern}' in {path}"
            lines = []
            for e in entries[:200]:
                tag = "/" if e.is_dir() else ""
                lines.append(f"{'📁' if e.is_dir() else '📄'} {e.name}{tag}")
            if len(entries) > 200:
                lines.append(f"... and {len(entries)-200} more")
            return "\n".join(lines)
        except Exception as e:
            return f"Error listing directory: {e}"
