"""
Credential system — stored in ~/.apexforge_ai_agent/credentials.json
Generated once per machine/user, never sent anywhere (local-only).
"""
import uuid
import hashlib
import socket
import getpass
import json
import platform
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

CONFIG_DIR = Path.home() / ".apexforge_ai_agent"
CREDS_FILE = CONFIG_DIR / "credentials.json"


def _machine_fingerprint() -> str:
    parts = [
        socket.gethostname(),
        getpass.getuser(),
        platform.system(),
        platform.machine(),
    ]
    raw = ":".join(parts) + ":" + str(uuid.getnode())  # uuid.getnode() = MAC address int
    return hashlib.sha256(raw.encode()).hexdigest()


def _generate_key() -> str:
    fingerprint = _machine_fingerprint()
    salt = uuid.uuid4().hex
    combined = hashlib.sha256(f"{fingerprint}:{salt}".encode()).hexdigest()
    return f"apx_{combined[:32]}"


def load() -> Optional[Dict]:
    """Return credentials dict or None if not set up yet."""
    if CREDS_FILE.exists():
        try:
            return json.loads(CREDS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def create(username: str) -> Dict:
    """Create new credentials for a user."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    creds = {
        "username": username,
        "key": _generate_key(),
        "machine": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "created": datetime.now().isoformat(),
        "plan": "free",
        "usage": {
            "sessions": 0,
            "messages": 0,
            "last_active": None,
        },
    }
    CREDS_FILE.write_text(json.dumps(creds, indent=2, ensure_ascii=False), encoding="utf-8")
    return creds


def increment(sessions: int = 0, messages: int = 0):
    """Update usage counters."""
    creds = load()
    if not creds:
        return
    creds["usage"]["sessions"] += sessions
    creds["usage"]["messages"] += messages
    creds["usage"]["last_active"] = datetime.now().isoformat()
    CREDS_FILE.write_text(json.dumps(creds, indent=2, ensure_ascii=False), encoding="utf-8")


def key_short(creds: Dict) -> str:
    k = creds.get("key", "")
    return k[:8] + "…" + k[-4:] if len(k) > 12 else k


def config_dir() -> Path:
    return CONFIG_DIR
