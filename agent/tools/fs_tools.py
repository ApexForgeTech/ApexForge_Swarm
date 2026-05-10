import shutil
import subprocess
from pathlib import Path
from .base import BaseTool


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = "Search for text inside files (like grep). Returns matching lines with filenames."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Text or regex pattern to search for."},
            "directory": {"type": "string", "description": "Directory to search in. Default: current dir."},
            "file_pattern": {"type": "string", "description": "File glob pattern, e.g. '*.py'. Default: '*'."},
            "case_sensitive": {"type": "boolean", "description": "Case sensitive search. Default: false."},
        },
        "required": ["query"],
    }

    def execute(self, query: str, directory: str = ".", file_pattern: str = "*", case_sensitive: bool = False) -> str:
        try:
            flags = [] if case_sensitive else ["-i"]
            result = subprocess.run(
                ["grep", "-r", "--include", file_pattern, "-n", "--color=never"] + flags + [query, directory],
                capture_output=True, text=True, timeout=15,
            )
            out = result.stdout.strip()
            if not out:
                return f"No matches found for '{query}' in {directory}/{file_pattern}"
            lines = out.splitlines()
            if len(lines) > 100:
                return "\n".join(lines[:100]) + f"\n... ({len(lines)-100} more lines)"
            return out
        except Exception as e:
            return f"Error: {e}"


class MakeDirTool(BaseTool):
    name = "create_directory"
    description = "Create a directory (and parent directories if needed)."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to create."},
        },
        "required": ["path"],
    }

    def execute(self, path: str) -> str:
        try:
            Path(path).expanduser().mkdir(parents=True, exist_ok=True)
            return f"Created directory: {path}"
        except Exception as e:
            return f"Error: {e}"


class DeletePathTool(BaseTool):
    name = "delete_path"
    description = "Delete a file or directory. WARNING: irreversible."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File or directory path to delete."},
        },
        "required": ["path"],
    }

    def execute(self, path: str) -> str:
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return f"Not found: {path}"
            if p.is_dir():
                shutil.rmtree(p)
                return f"Deleted directory: {path}"
            else:
                p.unlink()
                return f"Deleted file: {path}"
        except Exception as e:
            return f"Error: {e}"


class MovePathTool(BaseTool):
    name = "move_path"
    description = "Move or rename a file or directory."
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source path."},
            "destination": {"type": "string", "description": "Destination path."},
        },
        "required": ["source", "destination"],
    }

    def execute(self, source: str, destination: str) -> str:
        try:
            src = Path(source).expanduser()
            dst = Path(destination).expanduser()
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return f"Moved: {source} → {destination}"
        except Exception as e:
            return f"Error: {e}"
