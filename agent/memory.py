from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Dict, List, Optional

import yaml


_SKILL_PRIORITY = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
}


@dataclass
class SkillDocument:
    slug: str
    title: str
    body: str
    priority: str = "normal"
    summary: str = ""
    triggers: List[str] = field(default_factory=list)
    mandatory: List[str] = field(default_factory=list)

    @property
    def sort_key(self):
        return (_SKILL_PRIORITY.get(self.priority, 2), self.title.lower())

    def compact_block(self) -> str:
        lines = [f"### {self.title}", f"Priority: `{self.priority}`"]
        if self.summary:
            lines.append(f"Summary: {self.summary}")
        if self.triggers:
            lines.append("Applies when: " + "; ".join(self.triggers))
        if self.mandatory:
            lines.append("Mandatory requirements:")
            lines.extend(f"- {item}" for item in self.mandatory[:6])
        return "\n".join(lines)


class MemorySystem:
    """
    Two-layer memory:
      global: skills/ and memory/ at project root (shared across all profiles)
      profile: profiles/NAME/skills/ and profiles/NAME/memory/ (profile-specific)
    Profile layer takes priority over global.
    """

    def __init__(
        self,
        global_skills_dir: Path,
        global_memory_dir: Path,
        profile_skills_dir: Optional[Path] = None,
        profile_memory_dir: Optional[Path] = None,
    ):
        self.global_skills_dir = global_skills_dir
        self.global_memory_dir = global_memory_dir
        self.profile_skills_dir = profile_skills_dir
        self.profile_memory_dir = profile_memory_dir

        global_skills_dir.mkdir(parents=True, exist_ok=True)
        global_memory_dir.mkdir(parents=True, exist_ok=True)
        if profile_skills_dir:
            profile_skills_dir.mkdir(parents=True, exist_ok=True)
        if profile_memory_dir:
            profile_memory_dir.mkdir(parents=True, exist_ok=True)

    # ── Reading ────────────────────────────────────────────────────────────

    def _load_dir(self, directory: Path) -> Dict[str, str]:
        result = {}
        if not directory or not directory.exists():
            return result
        for f in sorted(directory.glob("*.md")):
            try:
                content = f.read_text(encoding="utf-8").strip()
                if content:
                    result[f.stem] = content
            except Exception:
                pass
        return result

    def _load_skill_docs(self, directory: Path) -> Dict[str, SkillDocument]:
        result: Dict[str, SkillDocument] = {}
        if not directory or not directory.exists():
            return result
        for f in sorted(directory.glob("*.md")):
            try:
                raw = f.read_text(encoding="utf-8").strip()
                if not raw:
                    continue
                result[f.stem] = self._parse_skill_doc(f.stem, raw)
            except Exception:
                pass
        return result

    def _parse_skill_doc(self, slug: str, raw: str) -> SkillDocument:
        meta: Dict = {}
        body = raw.strip()
        if raw.startswith("---"):
            match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, flags=re.DOTALL)
            if match:
                try:
                    meta = yaml.safe_load(match.group(1)) or {}
                except Exception:
                    meta = {}
                body = match.group(2).strip()

        title = str(meta.get("title") or self._extract_title(body) or slug.replace("_", " ").title())
        priority = str(meta.get("priority", "normal")).lower()
        summary = str(meta.get("summary") or self._extract_summary(body))
        triggers = self._normalize_list(meta.get("triggers"))
        mandatory = self._normalize_list(meta.get("mandatory"))

        return SkillDocument(
            slug=slug,
            title=title,
            body=body,
            priority=priority if priority in _SKILL_PRIORITY else "normal",
            summary=summary,
            triggers=triggers,
            mandatory=mandatory,
        )

    def _extract_title(self, body: str) -> str:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
        return ""

    def _extract_summary(self, body: str) -> str:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped
        return ""

    def _normalize_list(self, value) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]

    def _merge(self, base: Dict, override: Dict) -> Dict:
        merged = dict(base)
        merged.update(override)
        return merged

    def build_context(self) -> str:
        skills = self._merge(
            self._load_skill_docs(self.global_skills_dir),
            self._load_skill_docs(self.profile_skills_dir) if self.profile_skills_dir else {},
        )
        memories = self._merge(
            self._load_dir(self.global_memory_dir),
            self._load_dir(self.profile_memory_dir) if self.profile_memory_dir else {},
        )

        parts = []
        if skills:
            ordered = sorted(skills.values(), key=lambda skill: skill.sort_key)
            summary_lines = []
            compact_blocks = []
            for skill in ordered:
                prefix = f"[{skill.priority}] " if skill.priority else ""
                summary = skill.summary or "Follow this skill when it applies."
                summary_lines.append(f"- {prefix}{skill.title} — {summary}")
                compact_blocks.append(skill.compact_block())

            parts.append(
                "## Loaded Skills\n"
                "Treat every loaded skill as an active operating rule. When several skills apply, follow the stricter rule.\n"
                + "\n".join(summary_lines)
                + "\n\n## Skill Rules\n"
                + "\n\n".join(compact_blocks)
            )
        if memories:
            block = "\n\n".join(f"### {n}\n{c}" for n, c in memories.items())
            parts.append(f"## Your Memory\n{block}")

        return "\n\n---\n\n".join(parts)

    # ── Writing — always goes to profile layer if available ────────────────

    def _active_memory_dir(self) -> Path:
        return self.profile_memory_dir or self.global_memory_dir

    def _active_skills_dir(self) -> Path:
        return self.profile_skills_dir or self.global_skills_dir

    @property
    def memory_dir(self) -> Path:
        return self._active_memory_dir()

    @property
    def skills_dir(self) -> Path:
        return self._active_skills_dir()

    def remember(self, topic: str, content: str) -> str:
        slug = _slug(topic)
        path = self._active_memory_dir() / f"{slug}.md"
        path.write_text(f"# {topic}\n\n{content}\n", encoding="utf-8")
        layer = "profile" if self.profile_memory_dir else "global"
        return f"Saved to {layer} memory: {slug}.md"

    def recall(self, topic: str) -> str:
        slug = _slug(topic)
        # Profile takes priority
        for d in [self.profile_memory_dir, self.global_memory_dir]:
            if not d:
                continue
            exact = d / f"{slug}.md"
            if exact.exists():
                return exact.read_text(encoding="utf-8")
            for f in d.glob("*.md"):
                if topic.lower() in f.stem:
                    return f.read_text(encoding="utf-8")
        return f"No memory found for '{topic}'."

    def learn_skill(self, name: str, content: str) -> str:
        slug = _slug(name)
        path = self._active_skills_dir() / f"{slug}.md"
        path.write_text(f"# {name}\n\n{content}\n", encoding="utf-8")
        layer = "profile" if self.profile_skills_dir else "global"
        return f"Skill saved to {layer} skills: {slug}.md"

    # ── Listing ────────────────────────────────────────────────────────────

    def list_skills(self) -> List[str]:
        merged = self._merge(
            self._load_dir(self.global_skills_dir),
            self._load_dir(self.profile_skills_dir) if self.profile_skills_dir else {},
        )
        return sorted(merged.keys())

    def list_memories(self) -> List[str]:
        merged = self._merge(
            self._load_dir(self.global_memory_dir),
            self._load_dir(self.profile_memory_dir) if self.profile_memory_dir else {},
        )
        return sorted(merged.keys())

    def list_global_skills(self) -> List[str]:
        return sorted(self._load_dir(self.global_skills_dir).keys())

    def list_profile_skills(self) -> List[str]:
        return sorted(self._load_dir(self.profile_skills_dir).keys()) if self.profile_skills_dir else []

    def list_global_memories(self) -> List[str]:
        return sorted(self._load_dir(self.global_memory_dir).keys())

    def list_profile_memories(self) -> List[str]:
        return sorted(self._load_dir(self.profile_memory_dir).keys()) if self.profile_memory_dir else []


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^\w\-]", "_", text.lower())[:60]
