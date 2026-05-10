import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


class Session:
    def __init__(self, sessions_dir: Path, session_id: str = None, model: str = ""):
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        if session_id and (sessions_dir / f"{session_id}.json").exists():
            self.id = session_id
            self._load_existing()
        else:
            self.id = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.created = datetime.now().isoformat()
            self.updated = self.created
            self.model = model
            self._log: List[Dict] = []
            self._resumed_messages: List[Dict] = []

        self.json_path = self.sessions_dir / f"{self.id}.json"
        self.md_path = self.sessions_dir / f"{self.id}.md"
        self._md_initialized = self.md_path.exists()

    def _load_existing(self):
        data = json.loads((self.sessions_dir / f"{self.id}.json").read_text(encoding="utf-8"))
        self.created = data.get("created", "")
        self.updated = data.get("updated", "")
        self.model = data.get("model", "")
        self._log = data.get("log", [])
        self._resumed_messages = data.get("messages", [])

    @property
    def resumed_messages(self) -> List[Dict]:
        """Return full messages list for resuming with LLM."""
        return self._resumed_messages

    @property
    def turn_count(self) -> int:
        return sum(1 for x in self._log if x.get("role") == "user")

    @property
    def created_display(self) -> str:
        return self.created[:16].replace("T", " ")

    @property
    def updated_display(self) -> str:
        return self.updated[:16].replace("T", " ")

    # ── Save methods ───────────────────────────────────────────────────────

    def _flush(self, messages: List[Dict]):
        """Persist session to disk."""
        self.updated = datetime.now().isoformat()
        data = {
            "id": self.id,
            "created": self.created,
            "updated": self.updated,
            "model": self.model,
            "log": self._log,
            "messages": messages,  # full LLM message history for resume
        }
        self.json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _md_append(self, role: str, content: str, extra: str = ""):
        if not self._md_initialized:
            header = (
                f"# Session: {self.id}\n\n"
                f"**Started:** {self.created_display}  "
                f"**Model:** {self.model}\n\n---\n\n"
            )
            self.md_path.write_text(header, encoding="utf-8")
            self._md_initialized = True

        ts = datetime.now().strftime("%H:%M:%S")
        if role == "user":
            block = f"\n**[{ts}] You:**\n\n{content}\n"
        elif role == "assistant":
            block = f"\n**[{ts}] Agent:**\n\n{content}\n"
        elif role == "tool":
            preview = content[:300] + ("…" if len(content) > 300 else "")
            block = f"\n> ⚙ `{extra}` → {preview}\n"
        else:
            block = f"\n[{role}]: {content}\n"

        with open(self.md_path, "a", encoding="utf-8") as f:
            f.write(block)

    def save_user(self, content: str, messages: List[Dict]):
        self._log.append({"role": "user", "content": content, "time": datetime.now().isoformat()})
        self._flush(messages)
        self._md_append("user", content)

    def save_agent(self, content: str, messages: List[Dict]):
        self._log.append({"role": "assistant", "content": content, "time": datetime.now().isoformat()})
        self._flush(messages)
        self._md_append("assistant", content)

    def save_tool(self, name: str, result: str, messages: List[Dict]):
        self._log.append({"role": "tool", "tool": name, "content": result, "time": datetime.now().isoformat()})
        self._flush(messages)
        self._md_append("tool", result, extra=name)

    # ── List sessions ──────────────────────────────────────────────────────

    @classmethod
    def list_all(cls, sessions_dir: Path) -> List[Dict]:
        if not sessions_dir.exists():
            return []
        result = []
        for p in sorted(sessions_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                turns = sum(1 for x in data.get("log", []) if x.get("role") == "user")
                result.append({
                    "id": data.get("id", p.stem),
                    "created": data.get("created", "")[:16].replace("T", " "),
                    "updated": data.get("updated", "")[:16].replace("T", " "),
                    "model": data.get("model", ""),
                    "turns": turns,
                })
            except Exception:
                pass
        return result

    @classmethod
    def latest_id(cls, sessions_dir: Path) -> Optional[str]:
        sessions = cls.list_all(sessions_dir)
        return sessions[0]["id"] if sessions else None
