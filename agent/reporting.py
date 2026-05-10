from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class WorkerReport:
    worker: str
    summary: str
    findings: List[str] = field(default_factory=list)
    completed_actions: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    raw_output: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EnhancedWorkerReport(WorkerReport):
    tool_calls_made: int = 0
    duration_seconds: float = 0.0
    confidence: float = 0.0

    def quality_score(self) -> float:
        """0.0–1.0 composite quality estimate based on output richness."""
        score = 0.0
        if self.findings:
            score += min(len(self.findings) * 0.1, 0.3)
        if self.completed_actions:
            score += min(len(self.completed_actions) * 0.1, 0.3)
        if self.evidence:
            score += min(len(self.evidence) * 0.1, 0.2)
        if self.tool_calls_made > 0:
            score += 0.2
        return round(min(score, 1.0), 2)


def normalize_worker_report(worker: str, text: str, payload: Dict[str, Any] | None = None) -> WorkerReport:
    payload = payload or {}

    def _listify(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    summary = str(payload.get("summary") or "").strip()
    raw_output = (text or "").strip()
    if not summary:
        summary = raw_output[:400] if raw_output else f"{worker} completed the assigned task."

    report = WorkerReport(
        worker=worker,
        summary=summary,
        findings=_listify(payload.get("findings")),
        completed_actions=_listify(payload.get("completed_actions") or payload.get("actions")),
        evidence=_listify(payload.get("evidence")),
        open_questions=_listify(payload.get("open_questions") or payload.get("open_items")),
        raw_output=raw_output,
    )
    return report
