from typing import Optional
from .base import BaseTool
import os


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Modify a file with simple operations: append, prepend, replace."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to modify."},
            "action": {"type": "string", "description": "one of: append, prepend, replace"},
            "content": {"type": "string", "description": "Content to insert (for append/prepend)."},
            "find": {"type": "string", "description": "Text to find (for replace)."},
            "replace": {"type": "string", "description": "Replacement text (for replace)."},
        },
        "required": ["path", "action"],
    }

    def execute(self, path: str, action: str, content: Optional[str] = None,
                find: Optional[str] = None, replace: Optional[str] = None) -> str:
        try:
            if action not in {"append", "prepend", "replace"}:
                return f"Error: invalid action '{action}'"
            if not os.path.exists(path):
                return f"Error: file not found: {path}"

            if action == "append":
                if content is None:
                    return "Error: content required for append"
                with open(path, "a", encoding="utf-8") as f:
                    f.write(content)
                return f"Appended to {path}"
            if action == "prepend":
                if content is None:
                    return "Error: content required for prepend"
                with open(path, "r", encoding="utf-8") as f:
                    old = f.read()
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content + old)
                return f"Prepended to {path}"
            # replace
            if find is None or replace is None:
                return "Error: find and replace required for action 'replace'"
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
            data = data.replace(find, replace)
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
            return f"Replaced occurrences in {path}"
        except Exception as e:
            return f"Error editing file: {e}"
