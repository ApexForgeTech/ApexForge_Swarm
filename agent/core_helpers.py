import json
import re
import shlex
import unicodedata
from pathlib import Path
from typing import Any, Optional


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text.lower()).strip()
    return text


def resolve_file_path(raw_path: str) -> Optional[str]:
    candidate = Path(raw_path).expanduser()
    if candidate.exists():
        return str(candidate)

    search_roots = [
        Path.cwd(),
        Path.home(),
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
    ]
    for root in search_roots:
        guess = root / raw_path
        if guess.exists():
            return str(guess)
    return None


def shell_quote(value: str) -> str:
    return shlex.quote(str(value))


def ascii_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)
