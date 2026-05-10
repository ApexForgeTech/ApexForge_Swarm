from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_event(
    event_type: str,
    data: Any = None,
    *,
    agent: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "type": event_type,
        "data": data,
        "ts": _timestamp(),
    }
    if agent:
        event["agent"] = agent
    if meta:
        event["meta"] = meta
    return event


def session_event(session_id: str) -> Dict[str, Any]:
    return make_event("session", {"session_id": session_id})


def text_event(text: str, *, agent: Optional[str] = None) -> Dict[str, Any]:
    return make_event("text", text, agent=agent)


def thought_event(text: str, *, agent: Optional[str] = None) -> Dict[str, Any]:
    return make_event("thought", text, agent=agent)


def tool_call_event(
    name: str,
    args: Dict[str, Any],
    *,
    agent: Optional[str] = None,
    primary: Optional[bool] = None,
) -> Dict[str, Any]:
    meta = {"primary": primary} if primary is not None else None
    return make_event("tool_call", {"name": name, "args": args}, agent=agent, meta=meta)


def tool_result_event(
    name: str,
    result: str,
    *,
    agent: Optional[str] = None,
    primary: Optional[bool] = None,
) -> Dict[str, Any]:
    meta = {"primary": primary} if primary is not None else None
    return make_event("tool_result", {"name": name, "result": result}, agent=agent, meta=meta)


def interrupted_event(partial_text: str) -> Dict[str, Any]:
    return make_event("interrupted", partial_text)


def error_event(message: str, *, agent: Optional[str] = None, code: Optional[str] = None) -> Dict[str, Any]:
    meta = {"code": code} if code else None
    return make_event("error", message, agent=agent, meta=meta)


def done_event() -> Dict[str, Any]:
    return make_event("done", None)


def compact_event(summary: str, *, turn: int, auto: bool = False) -> Dict[str, Any]:
    return make_event("compact", {"summary": summary, "turn": turn, "auto": auto})


def info_event(message: str, *, category: Optional[str] = None, round_index: Optional[int] = None) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    if category:
        meta["category"] = category
    if round_index is not None:
        meta["round"] = round_index
    return make_event("info", message, meta=meta or None)


def final_event(message: str, *, agent: Optional[str] = None) -> Dict[str, Any]:
    return make_event("final", message, agent=agent)


def agent_chat_event(agent: str, message: str, *, phase: Optional[str] = None) -> Dict[str, Any]:
    meta = {"phase": phase} if phase else None
    return make_event("agent_chat", message, agent=agent, meta=meta)


def assignment_event(agent: str, role: str, task: str, *, round_index: Optional[int] = None) -> Dict[str, Any]:
    meta = {"round": round_index} if round_index is not None else None
    return make_event("assignment", {"role": role, "task": task}, agent=agent, meta=meta)


def worker_status_event(
    agent: str,
    status: str,
    *,
    task: Optional[str] = None,
    round_index: Optional[int] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {"status": status}
    if task:
        data["task"] = task
    meta = {"round": round_index} if round_index is not None else None
    return make_event("worker_status", data, agent=agent, meta=meta)


def report_event(
    agent: str,
    summary: str,
    *,
    full_report: Optional[str] = None,
    findings: Optional[list[str]] = None,
    completed_actions: Optional[list[str]] = None,
    evidence: Optional[list[str]] = None,
    open_questions: Optional[list[str]] = None,
    round_index: Optional[int] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {"summary": summary}
    if full_report:
        data["full_report"] = full_report
    if findings:
        data["findings"] = findings
    if completed_actions:
        data["completed_actions"] = completed_actions
    if evidence:
        data["evidence"] = evidence
    if open_questions:
        data["open_questions"] = open_questions
    meta = {"round": round_index} if round_index is not None else None
    return make_event("report", data, agent=agent, meta=meta)


def review_event(
    agent: str,
    summary: str,
    status: str,
    *,
    feedback: str = "",
    final_answer: str = "",
    round_index: Optional[int] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {"summary": summary, "status": status}
    if feedback:
        data["feedback"] = feedback
    if final_answer:
        data["final_answer"] = final_answer
    meta = {"round": round_index} if round_index is not None else None
    return make_event("review", data, agent=agent, meta=meta)
