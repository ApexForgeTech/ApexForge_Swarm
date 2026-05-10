import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .core_helpers import ascii_json, normalize_text, resolve_file_path, shell_quote


class RequestRouter:
    def __init__(self, config, memory):
        self.config = config
        self.memory = memory

    def extract_shell_command(self, text: str) -> Optional[str]:
        if not text:
            return None
        match = re.search(r"```(?:sh|bash|shell)?\s*\n(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        lines = [line.strip() for line in match.group(1).splitlines() if line.strip()]
        if len(lines) != 1:
            return None
        command = lines[0]
        if len(command) > 200:
            return None
        return command

    def prepare_user_message(self, user_message: str, images: Optional[List[str]] = None) -> str:
        if images or not self.looks_like_tool_required_task(user_message):
            return user_message
        return (
            "[Execution requirement: this request depends on real machine, file, repository, document, "
            "or web state. Use tools before answering. For safe read-only actions, do the work immediately "
            "instead of asking for confirmation.]\n\n"
            f"{user_message}"
        )

    def route_simple_request(
        self,
        user_message: str,
        pending_shell_command: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized = normalize_text(user_message)
        tokens = set(re.findall(r"[a-z0-9_]+", normalized))

        if pending_shell_command and self._is_confirmation_message(user_message):
            return {"name": "run_shell", "args": {"command": pending_shell_command}}

        if (
            any(phrase in normalized for phrase in (
                "who are you", "sen kimsan", "who am i talking to", "what are you",
            ))
            and "where are you" not in normalized
        ):
            identity = (
                f"ApexForge Swarm\n"
                f"Provider: {self.config.agent.provider}\n"
                f"Model: {self.config.ollama.model}\n"
                f"Loaded skills: {', '.join(self.memory.list_skills())}"
            )
            return {"name": "run_python", "args": {"code": f"print({ascii_json(identity)})"}}

        if any(phrase in normalized for phrase in (
            "what skills do you have", "which skills do you have", "what are your skills",
            "show skills", "list skills", "skills do you have",
        )):
            skills_text = "\n".join(self.memory.list_skills()) or "No skills loaded."
            return {"name": "run_python", "args": {"code": f"print({ascii_json(skills_text)})"}}

        if normalized in {"salam", "salam aleykum", "salam eleykum", "hello", "hi", "hey", "selam", "merhaba"}:
            greeting = "Salam. Men ApexForge Swarm-em. Ne etmek istediyini yaz, birbasa icra edim."
            return {"name": "run_python", "args": {"code": f"print({ascii_json(greeting)})"}}

        if any(key in normalized for key in (
            "cari qovlu", "cari qovlug", "current directory", "working directory",
            "current folder", "pwd", "nerdeyik", "hardayiq", "haradayiq", "where are we",
        )):
            return {"name": "run_shell", "args": {"command": "pwd"}}

        if any(key in normalized for key in ("home directory", "home folder", "ev qovlugu", "ana qovluq", "home qovluq")):
            if any(key in normalized for key in ("list", "listele", "show", "files", "neler var", "what is in")):
                return {"name": "list_directory", "args": {"path": str(Path.home())}}

        wants_listing = (
            any(phrase in normalized for phrase in (
                "listele", "list", "neler var", "show files", "show me files",
            ))
            or "ls" in tokens
        )
        if wants_listing and "desktop" in normalized:
            return {"name": "list_directory", "args": {"path": str(Path.home() / "Desktop")}}
        if wants_listing and any(key in normalized for key in ("burda", "buradaki", "here", "current", "bu qovlu", "bu klasor", "files")):
            return {"name": "list_directory", "args": {"path": "."}}

        file_path = self._match_file_reference(user_message)
        filename_match = re.search(r"\b([\w.-]+\.[A-Za-z0-9]{1,12})\b", user_message or "")
        wants_file_content = any(key in normalized for key in (
            "icinde ne var", "icerisinde ne var", "content", "contents", "read",
            "show", "open", "cat",
        ))
        if file_path and wants_file_content:
            return {"name": "read_file", "args": {"path": file_path}}

        if filename_match and any(key in normalized for key in (
            "where is", "hardadir", "haradadir", "tap", "find", "locate", "axtar",
        )):
            filename = filename_match.group(1)
            cmd = (
                "results=\"$("
                "if command -v locate >/dev/null 2>&1; then "
                f"locate -b -- {shell_quote(filename)} 2>/dev/null | head -100; "
                "else "
                f"find / -type f -name {shell_quote(filename)} 2>/dev/null | head -100; "
                "fi"
                ")\"; "
                "if [ -n \"$results\" ]; then "
                "printf '%s\\n' \"$results\"; "
                "else "
                f"printf '%s\\n' 'No files found matching {filename}'; "
                "fi"
            )
            return {"name": "run_shell", "args": {"command": cmd}}

        if wants_listing and any(key in normalized for key in ("file", "fiel", "fayl", "dosya")):
            return {"name": "list_directory", "args": {"path": "."}}

        if wants_listing:
            return {"name": "list_directory", "args": {"path": "."}}

        return None

    def looks_like_tool_required_task(self, user_message: str) -> bool:
        normalized = normalize_text(user_message)
        keywords = (
            "file", "fayl", "dosya", "directory", "folder", "qovluq", "klasor",
            "repo", "git", "branch", "commit", "log", "diff",
            "run", "execute", "command", "shell", "terminal",
            "read", "open", "show", "list", "find", "search",
            "write", "edit", "create", "delete", "move", "rename",
            "url", "website", "web", "fetch", "download",
            "installed", "version", "where", "current", "pwd",
        )
        return any(keyword in normalized for keyword in keywords)

    def _is_confirmation_message(self, text: str) -> bool:
        normalized = normalize_text(text)
        confirmations = {
            "do it", "run it", "execute it", "execute", "proceed", "continue",
            "okay do it", "ok do it", "do that", "go ahead", "et", "ele",
            "islet", "calistir", "bunu et", "bunu calistir", "day it",
        }
        return normalized in confirmations

    def _match_file_reference(self, text: str) -> Optional[str]:
        matches = re.findall(r"([~./\w-]+\.[A-Za-z0-9]{1,12})", text or "")
        for match in matches:
            resolved = resolve_file_path(match)
            if resolved:
                return resolved
        return None
