import yaml
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict

ROOT = Path(__file__).parent.parent
PROFILES_DIR = ROOT / "profiles"


class Profile:
    def __init__(self, name: str):
        self.name = name
        self.path = PROFILES_DIR / name
        self._data: Dict = {}
        self._load()

    def _load(self):
        cfg = self.path / "profile.yaml"
        if cfg.exists():
            with open(cfg, encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}
        else:
            self._data = {
                "name": self.name,
                "created": datetime.now().isoformat(),
                "description": "",
                "model": None,
                "temperature": None,
                "num_ctx": None,
            }

    # ── Properties ────────────────────────────────────────────────────────
    @property
    def description(self) -> str:
        return self._data.get("description", "")

    @property
    def model(self) -> Optional[str]:
        return self._data.get("model")

    @property
    def temperature(self) -> Optional[float]:
        return self._data.get("temperature")

    @property
    def num_ctx(self) -> Optional[int]:
        return self._data.get("num_ctx")

    @property
    def created(self) -> str:
        return self._data.get("created", "")[:10]

    @property
    def memory_dir(self) -> Path:
        return self.path / "memory"

    @property
    def skills_dir(self) -> Path:
        return self.path / "skills"

    @property
    def sessions_dir(self) -> Path:
        return self.path / "sessions"

    # ── Persistence ───────────────────────────────────────────────────────
    def ensure_dirs(self):
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def save(self):
        self.ensure_dirs()
        with open(self.path / "profile.yaml", "w", encoding="utf-8") as f:
            yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True)

    def update(self, **kwargs):
        self._data.update({k: v for k, v in kwargs.items() if v is not None})
        self.save()

    # ── Class methods ──────────────────────────────────────────────────────
    @classmethod
    def create(cls, name: str, model: str = None, description: str = "") -> "Profile":
        p = cls(name)
        p._data.update({"name": name, "created": datetime.now().isoformat(),
                        "description": description, "model": model})
        p.save()
        return p

    @classmethod
    def exists(cls, name: str) -> bool:
        return (PROFILES_DIR / name / "profile.yaml").exists()

    @classmethod
    def list_all(cls) -> List["Profile"]:
        if not PROFILES_DIR.exists():
            return []
        result = []
        for d in sorted(PROFILES_DIR.iterdir()):
            if d.is_dir() and (d / "profile.yaml").exists():
                result.append(cls(d.name))
        return result

    @classmethod
    def get_or_create(cls, name: str) -> "Profile":
        if cls.exists(name):
            return cls(name)
        return cls.create(name)
