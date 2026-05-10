import copy
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

from .config import Config
from .core import Agent
from .events import (
    agent_chat_event,
    assignment_event,
    done_event,
    error_event,
    final_event,
    info_event,
    interrupted_event,
    report_event,
    review_event,
    thought_event,
    tool_call_event,
    tool_result_event,
    worker_status_event,
)
from .llm_backend import BackendCapabilities, configured_llama_cpp_hosts, get_backend_capabilities
from .logging_utils import log_event
from .reporting import WorkerReport, normalize_worker_report
from .runtime import build_agent

logger = logging.getLogger("multi_agent")
logger.addHandler(logging.NullHandler())


class MessageBus:
    """Thread-safe agent-to-agent message queue."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mailboxes: Dict[str, List[Dict[str, Any]]] = {}

    def send(self, sender: str, recipient: str, content: str, *, meta: Optional[Dict[str, Any]] = None) -> None:
        msg: Dict[str, Any] = {
            "from": sender,
            "content": content,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if meta:
            msg["meta"] = meta
        with self._lock:
            self._mailboxes.setdefault(recipient, []).append(msg)

    def receive(self, recipient: str) -> List[Dict[str, Any]]:
        """Consume and return all messages for *recipient*."""
        with self._lock:
            return list(self._mailboxes.pop(recipient, []))

    def peek(self, recipient: str) -> List[Dict[str, Any]]:
        """Return messages without consuming them."""
        with self._lock:
            return list(self._mailboxes.get(recipient, []))

    def pending_count(self, recipient: str) -> int:
        with self._lock:
            return len(self._mailboxes.get(recipient, []))

    def clear(self, recipient: Optional[str] = None) -> None:
        with self._lock:
            if recipient:
                self._mailboxes.pop(recipient, None)
            else:
                self._mailboxes.clear()


class MultiAgentSystem:
    """
    Supervisor/worker orchestration for heavier tasks.

    The supervisor plans and reviews. Workers execute distinct assignments in
    parallel and report their results back to the supervisor.
    """

    def __init__(
        self,
        config: Config,
        supervisor_data: Dict[str, str],
        workers_data: List[Dict[str, str]],
        *,
        template_name: str = "",
        template_hint: str = "",
    ):
        self.config = config
        self.template_name = template_name
        self.template_hint = template_hint
        self.bus = MessageBus()
        self.backend_warnings: List[str] = []
        self.backend_capabilities: BackendCapabilities = get_backend_capabilities(config)
        self._llama_cpp_hosts = configured_llama_cpp_hosts(config) if config.agent.provider == "llama_cpp" else []
        normalized_supervisor, normalized_workers = self._normalize_team_models(supervisor_data, workers_data)
        self.supervisor_role = (normalized_supervisor.get("role") or "Supervisor").strip()
        self.worker_specs = self._normalize_worker_specs(normalized_workers)
        self.member_hosts = self._build_member_host_map(normalized_supervisor, self.worker_specs)

        self.supervisor = self._create_agent(
            "Supervisor",
            self.supervisor_role,
            normalized_supervisor.get("model"),
            host=self.member_hosts.get("Supervisor"),
        )
        self.workers = [
            self._create_agent(spec["name"], spec["role"], spec.get("model"), host=self.member_hosts.get(spec["name"]))
            for spec in self.worker_specs
        ]
        self.worker_roles = {spec["name"]: spec["role"] for spec in self.worker_specs}
        self.shared_history: List[Dict[str, Any]] = []

    @classmethod
    def from_template(
        cls,
        config: Config,
        template_name: str,
        *,
        supervisor_override: Optional[Dict[str, str]] = None,
        workers_override: Optional[List[Dict[str, str]]] = None,
    ) -> "MultiAgentSystem":
        from .mission_templates import apply_template, get_template
        result = apply_template(template_name, supervisor_override, workers_override)
        if result is None:
            raise ValueError(f"Unknown template: {template_name!r}")
        supervisor, workers = result
        tmpl = get_template(template_name) or {}
        hint = str(tmpl.get("hint") or "")
        return cls(config, supervisor, workers, template_name=template_name, template_hint=hint)

    def _normalize_team_models(
        self,
        supervisor_data: Dict[str, str],
        workers_data: List[Dict[str, str]],
    ) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
        supervisor = dict(supervisor_data or {})
        workers = [dict(worker or {}) for worker in workers_data or []]

        capabilities = self.backend_capabilities
        if capabilities.mixed_model_missions == "supported" and self.config.agent.provider != "llama_cpp":
            return supervisor, workers

        selected = self._selected_model(supervisor, workers)

        requested_models = {
            model for model in
            [selected, (supervisor.get("model") or "").strip(), *[((worker.get("model") or "").strip()) for worker in workers]]
            if model
        }

        if self._llama_cpp_multi_host_enabled():
            if len(requested_models) > len(self._llama_cpp_hosts):
                self.backend_warnings.append(
                    f"llama_cpp host pool has {len(self._llama_cpp_hosts)} hosts but this mission requested {len(requested_models)} distinct models. "
                    f"Normalized all agents to `{selected}` for safety."
                )
                supervisor["model"] = selected
                for worker in workers:
                    worker["model"] = selected
                return supervisor, workers
            if len([worker for worker in workers if (worker.get('role') or '').strip()]) > len(self._llama_cpp_hosts):
                self.backend_warnings.append(
                    f"llama_cpp host pool has {len(self._llama_cpp_hosts)} hosts for {len(workers)} workers. "
                    "Some workers will share a host, so those requests may still queue per host."
                )
            return supervisor, workers

        if len(requested_models) > 1 and capabilities.mixed_model_missions == "normalized_to_single_model":
            self.backend_warnings.append(
                f"{capabilities.provider} cannot safely run mixed per-agent models in one mission under the current engine rules. "
                f"Normalized all agents to `{selected}`."
            )

        if (
            len([worker for worker in workers if (worker.get("role") or "").strip()]) > 1
            and capabilities.request_parallelism == "serialized"
        ):
            self.backend_warnings.append(
                f"{capabilities.provider} requests will be queued during multi-agent missions under the current engine safety policy."
            )

        supervisor["model"] = selected
        for worker in workers:
            worker["model"] = selected
        return supervisor, workers

    def _selected_model(self, supervisor: Dict[str, str], workers: List[Dict[str, str]]) -> str:
        return (
            (supervisor.get("model") or "").strip()
            or next(((worker.get("model") or "").strip() for worker in workers if (worker.get("model") or "").strip()), "")
            or (self.config.ollama.model or "").strip()
        )

    def _llama_cpp_multi_host_enabled(self) -> bool:
        return self.config.agent.provider == "llama_cpp" and len(self._llama_cpp_hosts) > 1

    def _normalize_worker_specs(self, workers_data: List[Dict[str, str]]) -> List[Dict[str, str]]:
        specs: List[Dict[str, str]] = []
        for worker in workers_data:
            role = (worker.get("role") or "").strip()
            if not role:
                continue
            specs.append(
                {
                    "name": f"Worker_{len(specs) + 1}",
                    "role": role,
                    "model": (worker.get("model") or "").strip(),
                }
            )
        return specs

    def _agent_system_prompt(self, name: str, role: str) -> str:
        return (
            f"{self.config.agent.system_prompt}\n\n"
            "Multi-Agent Team Protocol:\n"
            f"- Your name is {name}.\n"
            f"- Your specific role is: {role}.\n"
            "- You are part of a coordinated team with shared task context.\n"
            "- Use tools whenever the task depends on real files, commands, URLs, or system state.\n"
            "- Stay focused on your assignment instead of rewriting the whole mission.\n"
            "- Return concrete results, evidence, and next-useful findings for the team."
        )

    def _build_member_host_map(
        self,
        supervisor_data: Dict[str, str],
        worker_specs: List[Dict[str, str]],
    ) -> Dict[str, str]:
        if not self._llama_cpp_multi_host_enabled():
            return {}

        assignments: Dict[str, str] = {}
        members = [
            *[
                {"name": spec["name"], "model": (spec.get("model") or self.config.ollama.model or "").strip(), "kind": "worker"}
                for spec in worker_specs
            ],
            {"name": "Supervisor", "model": (supervisor_data.get("model") or self.config.ollama.model or "").strip(), "kind": "supervisor"},
        ]
        buckets: Dict[str, List[Dict[str, str]]] = {}
        for member in members:
            buckets.setdefault(member["model"], []).append(member)

        unassigned_hosts = list(self._llama_cpp_hosts)
        host_loads = {host: 0 for host in self._llama_cpp_hosts}
        model_hosts: Dict[str, List[str]] = {}

        for model, bucket_members in sorted(
            buckets.items(),
            key=lambda item: (
                -sum(1 for member in item[1] if member["kind"] == "worker"),
                -len(item[1]),
            ),
        ):
            if not unassigned_hosts:
                break
            host = unassigned_hosts.pop(0)
            model_hosts.setdefault(model, []).append(host)
            member = bucket_members.pop(0)
            assignments[member["name"]] = host
            host_loads[host] += 1

        for model, bucket_members in buckets.items():
            hosts_for_model = model_hosts.setdefault(model, [])
            for member in bucket_members:
                if member["kind"] == "worker" and unassigned_hosts:
                    host = unassigned_hosts.pop(0)
                    hosts_for_model.append(host)
                else:
                    host = min(hosts_for_model, key=lambda item: host_loads[item])
                assignments[member["name"]] = host
                host_loads[host] += 1

        return assignments

    def _create_agent(self, name: str, role: str, model: Optional[str] = None, host: Optional[str] = None) -> Agent:
        agent_config = copy.deepcopy(self.config)
        agent_config.agent.system_prompt = self._agent_system_prompt(name, role)
        if host and agent_config.agent.provider == "llama_cpp":
            agent_config.llama_cpp.host = host
            agent_config.llama_cpp.hosts = [host]
        agent = build_agent(agent_config)
        agent.name = name
        if model:
            agent.set_model(model)
        return agent

    def _update_all_agents(self, message: Dict[str, Any]):
        self.shared_history.append(message)
        self.supervisor.messages.append(message)
        for worker in self.workers:
            worker.messages.append(message)

    def _worker_roster(self) -> str:
        if not self.worker_specs:
            return "No workers configured."
        return "\n".join(f"- {spec['name']}: {spec['role']}" for spec in self.worker_specs)

    def _extract_json_object(self, text: str) -> Optional[Dict[str, Any]]:
        cleaned = (text or "").strip()
        if not cleaned:
            return None

        candidates = [cleaned]
        fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
        candidates.extend(fenced)

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates.append(cleaned[start:end + 1])

        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
        return None

    def _collect_agent_run(
        self,
        agent: Agent,
        prompt: str,
        *,
        stream_text: bool,
        interrupt: Optional[threading.Event] = None,
    ) -> Tuple[str, List[Dict[str, Any]], bool]:
        events: List[Dict[str, Any]] = []
        full_text = ""
        was_interrupted = False

        for event in agent.chat(prompt, interrupt=interrupt):
            event_type = event["type"]
            if event_type == "text":
                full_text += event["data"]
                if stream_text:
                    events.append(agent_chat_event(agent.name, event["data"]))
            elif event_type == "thought":
                if stream_text:
                    events.append(thought_event(event["data"], agent=agent.name))
            elif event_type == "tool_call":
                events.append(
                    tool_call_event(
                        event["data"]["name"],
                        event["data"]["args"],
                        agent=agent.name,
                        primary=event.get("meta", {}).get("primary"),
                    )
                )
            elif event_type == "tool_result":
                events.append(
                    tool_result_event(
                        event["data"]["name"],
                        event["data"]["result"],
                        agent=agent.name,
                        primary=event.get("meta", {}).get("primary"),
                    )
                )
            elif event_type == "error":
                events.append(error_event(event["data"], agent=agent.name))
            elif event_type == "interrupted":
                was_interrupted = True
                events.append(interrupted_event(event["data"]))
            elif event_type == "done":
                break

        return full_text.strip(), events, was_interrupted

    def _default_assignments(self, user_message: str, feedback: str = "") -> List[Dict[str, str]]:
        assignments: List[Dict[str, str]] = []
        extra = f" Supervisor feedback to address: {feedback}" if feedback else ""
        for spec in self.worker_specs:
            role = spec["role"]
            task = (
                f"As the {role}, handle the part of this mission that best matches your role. "
                f"User request: {user_message}.{extra} Use tools when needed and return concrete findings only."
            )
            assignments.append({"worker": spec["name"], "task": task})
        return assignments

    def _normalize_assignments(self, payload: Optional[Dict[str, Any]], *, fallback_feedback: str = "") -> List[Dict[str, str]]:
        if not payload:
            return []

        raw = payload.get("assignments") or payload.get("worker_assignments") or []
        assignments: List[Dict[str, str]] = []
        valid_workers = {spec["name"] for spec in self.worker_specs}

        for item in raw:
            if not isinstance(item, dict):
                continue
            worker = str(item.get("worker") or item.get("name") or "").strip()
            task = str(item.get("task") or item.get("assignment") or "").strip()
            if worker not in valid_workers or not task:
                continue
            assignments.append({"worker": worker, "task": task})

        return assignments

    def _build_plan_prompt(self, user_message: str, previous_feedback: str = "") -> str:
        follow_up = f"\nPrevious supervisor feedback to address:\n{previous_feedback}\n" if previous_feedback else ""
        hint_block = f"\nTemplate guidance:\n{self.template_hint}\n" if self.template_hint else ""
        return (
            "You are the team supervisor. Create a concrete plan for the workers below.\n"
            "Return JSON only with this schema:\n"
            "{\n"
            '  "mission": "short summary",\n'
            '  "success_criteria": ["criterion 1", "criterion 2"],\n'
            '  "assignments": [\n'
            '    {"worker": "Worker_1", "task": "specific task for that worker"}\n'
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- Assign distinct work to each worker.\n"
            "- Tasks must be specific enough to execute directly.\n"
            "- Prefer evidence-gathering, implementation, and verification split when appropriate.\n"
            "- Do not include markdown fences.\n\n"
            f"User request:\n{user_message}\n\n"
            f"Workers:\n{self._worker_roster()}"
            f"{hint_block}"
            f"{follow_up}"
        )

    def _build_worker_prompt(
        self,
        *,
        user_message: str,
        mission: str,
        success_criteria: List[str],
        assignment: str,
        feedback: str = "",
    ) -> str:
        criteria = "\n".join(f"- {item}" for item in success_criteria if item) or "- Complete the assigned task correctly."
        feedback_block = f"\nSupervisor feedback for this round:\n{feedback}\n" if feedback else ""
        return (
            f"Mission:\n{mission or user_message}\n\n"
            f"User request:\n{user_message}\n\n"
            f"Your assignment:\n{assignment}\n\n"
            f"Success criteria:\n{criteria}\n"
            f"{feedback_block}"
            "Work on your assigned slice only. Use tools when needed. "
            "Prefer returning JSON only with this schema:\n"
            "{\n"
            '  "summary": "short summary",\n'
            '  "findings": ["finding 1"],\n'
            '  "completed_actions": ["action 1"],\n'
            '  "evidence": ["proof 1"],\n'
            '  "open_questions": ["optional remaining gap"]\n'
            "}\n"
            "If you cannot return valid JSON, still return a concise but concrete result with evidence, findings, and completed actions."
        )

    def _build_review_prompt(
        self,
        *,
        user_message: str,
        mission: str,
        success_criteria: List[str],
        worker_reports: Dict[str, Dict[str, Any]],
    ) -> str:
        criteria = "\n".join(f"- {item}" for item in success_criteria if item) or "- Complete the assigned task correctly."
        outputs_json = json.dumps(worker_reports, ensure_ascii=False, indent=2)
        return (
            "You are the supervisor reviewing worker outputs.\n"
            "Return JSON only with this schema:\n"
            "{\n"
            '  "status": "complete" or "revise",\n'
            '  "summary": "short assessment",\n'
            '  "final_answer": "final user-facing answer if complete, else empty string",\n'
            '  "feedback": "what must be improved if revise",\n'
            '  "assignments": [\n'
            '    {"worker": "Worker_1", "task": "revised task"}\n'
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- Mark complete only if the outputs satisfy the mission.\n"
            "- If revise, provide targeted follow-up assignments instead of generic criticism.\n"
            "- Do not include markdown fences.\n\n"
            f"User request:\n{user_message}\n\n"
            f"Mission summary:\n{mission}\n\n"
            f"Success criteria:\n{criteria}\n\n"
            f"Worker reports:\n{outputs_json}"
        )

    def _normalize_worker_report_payload(self, worker_name: str, worker_output: str) -> WorkerReport:
        payload = self._extract_json_object(worker_output)
        return normalize_worker_report(worker_name, worker_output, payload)

    def _emit_events(self, events: List[Dict[str, Any]]) -> Generator[Dict[str, Any], None, None]:
        for event in events:
            yield event

    def _run_worker(
        self,
        worker: Agent,
        worker_prompt: str,
        interrupt: Optional[threading.Event] = None,
    ) -> Tuple[str, List[Dict[str, Any]], str, bool]:
        log_event(
            logger,
            logging.INFO,
            "multi_agent_worker_started",
            worker=worker.name,
            prompt_preview=worker_prompt,
        )
        text, events, was_interrupted = self._collect_agent_run(worker, worker_prompt, stream_text=True, interrupt=interrupt)
        log_event(
            logger,
            logging.INFO,
            "multi_agent_worker_completed",
            worker=worker.name,
            event_count=len(events),
            output_preview=text,
        )
        return worker.name, events, text, was_interrupted

    def _emit_interrupt_and_stop(self, message: str) -> Generator[Dict[str, Any], None, None]:
        yield info_event(message, category="interrupt")
        yield interrupted_event(message)
        yield done_event()

    def chat(
        self,
        user_message: str,
        interrupt: Optional[threading.Event] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        user_msg_obj = {"role": "user", "content": user_message}
        self._update_all_agents(user_msg_obj)
        log_event(
            logger,
            logging.INFO,
            "multi_agent_mission_started",
            provider=self.config.agent.provider,
            supervisor_role=self.supervisor_role,
            worker_count=len(self.worker_specs),
            user_message=user_message,
            backend_capabilities=self.backend_capabilities.as_dict(),
        )

        yield info_event("Team briefing started. Supervisor is preparing the plan.", category="mission")
        for warning in self.backend_warnings:
            log_event(logger, logging.WARNING, "multi_agent_backend_warning", warning=warning)
            yield info_event(warning, category="backend")

        if interrupt and interrupt.is_set():
            interrupt.clear()
            yield from self._emit_interrupt_and_stop("Mission interrupted before execution started.")
            return

        if not self.workers:
            yield info_event("No workers configured. Supervisor will handle the mission alone.", category="mission")
            final_text, events, was_interrupted = self._collect_agent_run(
                self.supervisor,
                user_message,
                stream_text=True,
                interrupt=interrupt,
            )
            yield from self._emit_events(events)
            if was_interrupted:
                if interrupt:
                    interrupt.clear()
                yield from self._emit_interrupt_and_stop("Mission interrupted while the supervisor was responding.")
                return
            if final_text:
                yield final_event(final_text, agent=self.supervisor.name)
            yield done_event()
            return

        review_feedback = ""
        latest_worker_outputs: Dict[str, str] = {}
        latest_worker_reports: Dict[str, WorkerReport] = {}
        max_rounds = 3
        plan_text = ""
        mission = ""
        success_criteria: List[str] = []
        assignments: List[Dict[str, str]] = []

        for round_index in range(max_rounds):
            if interrupt and interrupt.is_set():
                interrupt.clear()
                yield from self._emit_interrupt_and_stop(f"Mission interrupted before planning round {round_index + 1}.")
                return

            log_event(logger, logging.INFO, "multi_agent_round_started", round=round_index + 1)
            yield info_event(f"Planning round {round_index + 1}.", category="planning", round_index=round_index + 1)

            plan_prompt = self._build_plan_prompt(user_message, previous_feedback=review_feedback)
            plan_text, plan_events, plan_interrupted = self._collect_agent_run(
                self.supervisor,
                plan_prompt,
                stream_text=False,
                interrupt=interrupt,
            )
            yield from self._emit_events(plan_events)
            if plan_interrupted:
                if interrupt:
                    interrupt.clear()
                yield from self._emit_interrupt_and_stop(f"Mission interrupted during planning round {round_index + 1}.")
                return

            plan_payload = self._extract_json_object(plan_text) or {}
            mission = str(plan_payload.get("mission") or user_message).strip()
            raw_criteria = plan_payload.get("success_criteria") or []
            success_criteria = [str(item).strip() for item in raw_criteria if str(item).strip()]
            assignments = self._normalize_assignments(plan_payload, fallback_feedback=review_feedback)
            if not assignments:
                assignments = self._default_assignments(user_message, feedback=review_feedback)

            self._update_all_agents({"role": "assistant", "content": plan_text or mission, "name": self.supervisor.name})

            yield info_event(f"Mission: {mission}", category="mission", round_index=round_index + 1)
            log_event(
                logger,
                logging.INFO,
                "multi_agent_plan_created",
                round=round_index + 1,
                mission=mission,
                success_criteria=success_criteria,
                assignment_count=len(assignments),
            )
            for assignment in assignments:
                role = self.worker_roles.get(assignment["worker"], "Worker")
                log_event(
                    logger,
                    logging.INFO,
                    "multi_agent_assignment_created",
                    round=round_index + 1,
                    worker=assignment["worker"],
                    role=role,
                    task=assignment["task"],
                )
                yield assignment_event(assignment["worker"], role, assignment["task"], round_index=round_index + 1)
                yield agent_chat_event(
                    self.supervisor.name,
                    f"{assignment['worker']} ({role}), your assignment: {assignment['task']}",
                    phase="assignment",
                )
                yield info_event(
                    f"{assignment['worker']} ({role}) -> {assignment['task']}",
                    category="assignment",
                    round_index=round_index + 1,
                )

            yield info_event(
                f"Execution round {round_index + 1} started.",
                category="execution",
                round_index=round_index + 1,
            )

            assigned_prompts: List[Tuple[Agent, str]] = []
            for assignment in assignments:
                worker = next((item for item in self.workers if item.name == assignment["worker"]), None)
                if not worker:
                    continue
                prompt = self._build_worker_prompt(
                    user_message=user_message,
                    mission=mission,
                    success_criteria=success_criteria,
                    assignment=assignment["task"],
                    feedback=review_feedback,
                )
                yield worker_status_event(worker.name, "assigned", task=assignment["task"], round_index=round_index + 1)
                yield agent_chat_event(worker.name, f"Understood. I will handle: {assignment['task']}", phase="assignment_ack")
                assigned_prompts.append((worker, prompt))

            ordered_results: List[Tuple[str, List[Dict[str, Any]], str, bool]] = []
            with ThreadPoolExecutor(max_workers=max(1, len(assigned_prompts))) as executor:
                future_map = {
                    executor.submit(self._run_worker, worker, prompt, interrupt): index
                    for index, (worker, prompt) in enumerate(assigned_prompts)
                }
                temp_results: Dict[int, Tuple[str, List[Dict[str, Any]], str, bool]] = {}
                for future in as_completed(future_map):
                    temp_results[future_map[future]] = future.result()
                ordered_results = [temp_results[index] for index in sorted(temp_results)]

            latest_worker_outputs = {}
            latest_worker_reports = {}
            for worker_name, events, worker_output, worker_interrupted in ordered_results:
                if worker_interrupted:
                    yield from self._emit_events(events)
                    if interrupt:
                        interrupt.clear()
                    yield from self._emit_interrupt_and_stop(f"Mission interrupted while {worker_name} was working.")
                    return
                report = self._normalize_worker_report_payload(worker_name, worker_output)
                log_event(
                    logger,
                    logging.INFO,
                    "multi_agent_report_received",
                    round=round_index + 1,
                    worker=worker_name,
                    event_count=len(events),
                    output_preview=report.summary,
                )
                yield worker_status_event(worker_name, "completed", round_index=round_index + 1)
                yield info_event(
                    f"{worker_name} finished and submitted a report.",
                    category="report",
                    round_index=round_index + 1,
                )
                yield from self._emit_events(events)
                latest_worker_outputs[worker_name] = worker_output
                latest_worker_reports[worker_name] = report
                yield report_event(
                    worker_name,
                    report.summary,
                    full_report=report.raw_output,
                    findings=report.findings,
                    completed_actions=report.completed_actions,
                    evidence=report.evidence,
                    open_questions=report.open_questions,
                    round_index=round_index + 1,
                )
                self._update_all_agents({"role": "assistant", "content": worker_output, "name": worker_name})

            yield info_event(
                "Supervisor is reviewing the worker reports.",
                category="review",
                round_index=round_index + 1,
            )

            review_prompt = self._build_review_prompt(
                user_message=user_message,
                mission=mission,
                success_criteria=success_criteria,
                worker_reports={name: report.as_dict() for name, report in latest_worker_reports.items()},
            )
            review_text, review_events, review_interrupted = self._collect_agent_run(
                self.supervisor,
                review_prompt,
                stream_text=False,
                interrupt=interrupt,
            )
            yield from self._emit_events(review_events)
            if review_interrupted:
                if interrupt:
                    interrupt.clear()
                yield from self._emit_interrupt_and_stop(f"Mission interrupted during review round {round_index + 1}.")
                return

            review_payload = self._extract_json_object(review_text) or {}
            review_status = str(review_payload.get("status") or "").strip().lower()
            review_summary = str(review_payload.get("summary") or "").strip()
            final_answer = str(review_payload.get("final_answer") or "").strip()
            review_feedback = str(review_payload.get("feedback") or "").strip()

            self._update_all_agents({"role": "assistant", "content": review_text or review_summary, "name": self.supervisor.name})

            if review_summary:
                log_event(
                    logger,
                    logging.INFO,
                    "multi_agent_review_completed",
                    round=round_index + 1,
                    status=review_status or "revise",
                    summary=review_summary,
                )
                yield review_event(
                    self.supervisor.name,
                    review_summary,
                    review_status or "revise",
                    feedback=review_feedback,
                    final_answer=final_answer,
                    round_index=round_index + 1,
                )
                yield agent_chat_event(self.supervisor.name, review_summary, phase="review")
                yield info_event(
                    f"Supervisor review: {review_summary}",
                    category="review",
                    round_index=round_index + 1,
                )

            if review_status == "complete":
                if not final_answer:
                    final_answer = next((output.strip() for output in latest_worker_outputs.values() if output.strip()), "Task completed.")
                log_event(
                    logger,
                    logging.INFO,
                    "multi_agent_mission_completed",
                    round=round_index + 1,
                    final_answer=final_answer,
                )
                yield final_event(final_answer, agent=self.supervisor.name)
                yield info_event("Mission accomplished.", category="mission", round_index=round_index + 1)
                yield done_event()
                return

            if not review_feedback:
                review_feedback = "The current reports are incomplete. Refine the work and close the remaining gaps."
            log_event(
                logger,
                logging.WARNING,
                "multi_agent_revision_requested",
                round=round_index + 1,
                feedback=review_feedback,
            )
            yield agent_chat_event(self.supervisor.name, review_feedback, phase="revision")
            yield info_event(
                f"Supervisor requested revisions: {review_feedback}",
                category="revision",
                round_index=round_index + 1,
            )

        fallback_answer = next((output.strip() for output in latest_worker_outputs.values() if output.strip()), "")
        if not fallback_answer:
            fallback_answer = review_feedback or plan_text or "The team stopped after several review rounds without a stable final answer."
        log_event(
            logger,
            logging.WARNING,
            "multi_agent_mission_fallback_completed",
            final_answer=fallback_answer,
        )
        yield final_event(fallback_answer, agent=self.supervisor.name)
        yield info_event("Mission ended with the best available result after multiple rounds.", category="mission")
        yield done_event()
