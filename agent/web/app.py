"""FastAPI web server with WebSocket streaming."""
import asyncio
import copy
import json
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from ..config import Config
from ..core import Agent
from ..events import error_event, session_event
from ..llm_backend import configured_llama_cpp_hosts, detect_available_backends
from ..logging_utils import log_event
from ..multi_agent import MultiAgentSystem
from ..runtime import build_agent
from ..store import SessionStore
from .auth import check_api_key, is_auth_enabled

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="ApexForge Swarm")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_config: Config = None
_agent: Agent = None
_session_agents: dict[str, Agent] = {}
_session_lock = threading.Lock()
_session_run_locks: dict[str, threading.RLock] = {}
_session_run_lock_guard = threading.Lock()
_session_hosts: dict[str, str] = {}
_host_cycle_index = 0
_host_cycle_lock = threading.Lock()
_store: SessionStore = None
_start_time: float = time.time()
_web_mode: str = "web"
_shutdown_event = threading.Event()
_active_interrupts: set[threading.Event] = set()
_active_interrupts_lock = threading.Lock()
logger = logging.getLogger("web")
logger.addHandler(logging.NullHandler())

_VERSION = "2.0.0"


def _warmup_model_background(config: Config) -> None:
    """Model yüklənmə warm-up — server başladıqda arxa planda işləyir.
    Llama.cpp modeli ilk sorğuda yüklənir (~60 saniyə).
    Bu funksiya server başladıqda kiçik bir dummy sorğu göndərir ki
    real sorğular gəldikdə model artıq yüklənmiş olsun."""
    if not config or config.agent.provider != "llama_cpp":
        return
    import requests
    hosts = configured_llama_cpp_hosts(config)
    if not hosts:
        hosts = [f"http://{config.llama_cpp.host}:{getattr(config.llama_cpp, 'port', 8081)}"]
    model = getattr(config.llama_cpp, 'model_path', '') or getattr(config.ollama, 'model', '')
    log_event(logger, logging.INFO, "model_warmup_started",
              hosts=hosts, model=model)
    for host in hosts:
        try:
            # OpenAI-compatible /v1/chat/completions endpoint
            url = host.rstrip('/') + "/v1/chat/completions"
            requests.post(
                url,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                    "temperature": 0,
                },
                timeout=180,
            )
            log_event(logger, logging.INFO, "model_warmup_done", host=host)
        except Exception as exc:
            log_event(logger, logging.WARNING, "model_warmup_failed",
                      host=host, error=str(exc))


def init(config: Config, mode: str = "web", warmup: bool = False):
    global _config, _agent, _session_agents, _session_run_locks, _session_hosts, _host_cycle_index, _store, _start_time, _web_mode
    _config = config
    _agent = _make_agent(config)
    _session_agents = {}
    _session_run_locks = {}
    _session_hosts = {}
    _host_cycle_index = 0
    _start_time = time.time()
    _web_mode = mode
    _shutdown_event.clear()
    db_path = Path(config.agent.memory_dir).parent / "sessions.db"
    _store = SessionStore(db_path)

    # Model pre-warm: yalnız --warmup-model flag-i veriləndə işləyir
    if warmup:
        warmup_thread = threading.Thread(
            target=_warmup_model_background,
            args=(config,),
            daemon=True,
            name="model-warmup",
        )
        warmup_thread.start()


def run_web(config: Config, *, api_only: bool = False, warmup: bool = False):
    mode = "serve" if api_only else "web"
    init(config, mode=mode, warmup=warmup)
    host = config.web.host or "127.0.0.1"
    port = int(config.web.port or 8090)
    log_event(logger, logging.INFO, "web_server_starting", host=host, port=port, mode=mode)
    uvicorn.run(app, host=host, port=port, log_level="warning")


def _make_agent(config: Config) -> Agent:
    return build_agent(config)


def _llama_cpp_host_pool() -> list[str]:
    if not _config or _config.agent.provider != "llama_cpp":
        return []
    return configured_llama_cpp_hosts(_config)


def _next_llama_cpp_host() -> str | None:
    global _host_cycle_index
    hosts = _llama_cpp_host_pool()
    if len(hosts) <= 1:
        return None
    with _host_cycle_lock:
        host = hosts[_host_cycle_index % len(hosts)]
        _host_cycle_index += 1
    return host


def _config_for_host(base: Config, host: str | None) -> Config:
    cfg = copy.deepcopy(base)
    if host and cfg.agent.provider == "llama_cpp":
        cfg.llama_cpp.host = host
        cfg.llama_cpp.hosts = [host]
    return cfg


def _clone_agent_from(base: Agent) -> Agent:
    clone = _make_agent(copy.deepcopy(base.config))
    clone.load_messages(list(base.messages))
    return clone


def _get_session_agent(session_id: str) -> Agent:
    with _session_lock:
        agent = _session_agents.get(session_id)
        if agent is None:
            host = _session_hosts.get(session_id)
            if host is None:
                host = _next_llama_cpp_host()
                if host:
                    _session_hosts[session_id] = host
            agent = _make_agent(_config_for_host(_config, host))
            # Restart-dan sonra history-ni SQLite-dan yüklə
            if _store:
                saved_messages = _store.load_session(session_id)
                if saved_messages:
                    agent.load_messages(saved_messages)
            _session_agents[session_id] = agent
        return agent


def _get_session_run_lock(session_id: str) -> threading.RLock:
    with _session_run_lock_guard:
        lock = _session_run_locks.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _session_run_locks[session_id] = lock
        return lock


def _drop_session_run_lock(session_id: str) -> None:
    with _session_run_lock_guard:
        _session_run_locks.pop(session_id, None)
    with _session_lock:
        _session_hosts.pop(session_id, None)


def _persist_session(session_id: str, agent: Agent) -> None:
    if _store:
        try:
            _store.save_session(session_id, list(agent.messages))
        except Exception as exc:
            log_event(logger, logging.WARNING, "session_persist_failed",
                      session_id=session_id, error=str(exc))


def _reset_sessions():
    global _session_agents, _session_run_locks, _session_hosts
    with _session_lock:
        _session_agents = {}
        _session_hosts = {}
    with _session_run_lock_guard:
        _session_run_locks = {}


@contextmanager
def _managed_interrupt_event():
    interrupt = threading.Event()
    if _shutdown_event.is_set():
        interrupt.set()
    with _active_interrupts_lock:
        _active_interrupts.add(interrupt)
    try:
        yield interrupt
    finally:
        with _active_interrupts_lock:
            _active_interrupts.discard(interrupt)


def _interrupt_all_active_requests() -> None:
    _shutdown_event.set()
    with _active_interrupts_lock:
        events = list(_active_interrupts)
    for event in events:
        event.set()


def _stop_agent_runtime(agent: Agent | None) -> None:
    if not agent:
        return
    llm = getattr(agent, "llm", None)
    stop_server = getattr(llm, "_stop_server", None)
    if callable(stop_server):
        try:
            stop_server()
        except Exception as exc:
            log_event(logger, logging.WARNING, "runtime_stop_failed", error=str(exc))


def _shutdown_runtime() -> None:
    _interrupt_all_active_requests()
    agents: list[Agent] = []
    if _agent is not None:
        agents.append(_agent)
    with _session_lock:
        agents.extend(_session_agents.values())
    seen: set[int] = set()
    for agent in agents:
        key = id(agent)
        if key in seen:
            continue
        seen.add(key)
        _stop_agent_runtime(agent)


def _run_prompt_to_text(
    agent: Agent,
    prompt: str,
    images: list[str] | None = None,
    interrupt: threading.Event | None = None,
) -> dict[str, Any]:
    text_parts: list[str] = []
    tool_events: list[dict[str, Any]] = []
    try:
        stream = agent.chat(prompt, images=images, interrupt=interrupt)
    except TypeError as exc:
        if "interrupt" not in str(exc):
            raise
        stream = agent.chat(prompt, images=images)
    for event in stream:
        if event["type"] == "text":
            text_parts.append(event["data"])
        elif event["type"] in {"tool_call", "tool_result", "error"}:
            tool_events.append(event)
        elif event["type"] == "interrupted":
            if event.get("data"):
                text_parts.append(event["data"])
            tool_events.append(event)
            break
        elif event["type"] == "done":
            break
    return {"response": "".join(text_parts), "events": tool_events}


def _extract_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts).strip()
    if content is None:
        return ""
    return str(content).strip()


def _normalize_chat_messages(raw_messages: Any) -> list[dict[str, str]]:
    if not isinstance(raw_messages, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"system", "user", "assistant"}:
            continue
        content = _extract_message_content(item.get("content"))
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _parse_combined_system_user_prompt(message: str) -> list[dict[str, str]]:
    text = (message or "").strip()
    if not text.lower().startswith("system:"):
        return []
    match = re.match(r"(?is)^system:\s*(.*?)\n\s*user:\s*(.+)$", text)
    if not match:
        return []
    system_prompt = match.group(1).strip()
    user_prompt = match.group(2).strip()
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if user_prompt:
        messages.append({"role": "user", "content": user_prompt})
    return messages


def _prepare_structured_chat(agent: Agent, data: dict[str, Any]) -> tuple[Agent | None, str]:
    messages = _normalize_chat_messages(data.get("messages"))
    if not messages:
        messages = _parse_combined_system_user_prompt(str(data.get("message") or ""))
    if not messages:
        return None, str(data.get("message") or "").strip()

    user_index = next((idx for idx in range(len(messages) - 1, -1, -1) if messages[idx]["role"] == "user"), -1)
    if user_index < 0:
        return None, str(data.get("message") or "").strip()

    prompt = messages[user_index]["content"].strip()
    if not prompt:
        return None, str(data.get("message") or "").strip()

    prepared = _clone_agent_from(agent)
    system_messages = [item["content"] for item in messages[: user_index + 1] if item["role"] == "system"]
    if system_messages:
        base_system = str(prepared.messages[0].get("content", "") or "")
        external_system = "\n\n".join(system_messages)
        prepared.messages[0] = {
            "role": "system",
            "content": (
                f"{base_system}\n\n"
                "## External System Instructions\n"
                f"{external_system}"
            ).strip(),
        }

    prepared.load_messages(messages[:user_index])
    return prepared, prompt


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name)[:60]


@app.on_event("shutdown")
async def shutdown_runtime():
    _shutdown_runtime()


# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    models: list[str] = []
    backend_ok = False
    try:
        models = _agent.available_models()
        backend_ok = True
    except Exception:
        pass
    uptime = int(time.time() - _start_time)
    store_stats = _store.stats() if _store else {}
    return {
        "status": "ok" if backend_ok else "degraded",
        "version": _VERSION,
        "provider": _config.agent.provider,
        "model": _config.ollama.model,
        "models_available": len(models),
        "auth_enabled": is_auth_enabled(),
        "uptime_seconds": uptime,
        "store": store_stats,
    }


@app.get("/")
async def index():
    if _web_mode == "serve":
        return JSONResponse(
            {
                "service": "ApexForge Swarm API",
                "mode": "serve",
                "provider": _config.agent.provider if _config else "",
                "model": _config.ollama.model if _config else "",
                "docs": "/docs",
                "health": "/health",
                "chat": "/api/chat",
                "ws": "/ws",
            }
        )
    return HTMLResponse((STATIC_DIR / "index.html").read_text())


@app.get("/api/models")
def list_models():
    try:
        return {"models": _agent.available_models()}
    except Exception as e:
        return {"models": [], "error": str(e)}


@app.get("/api/config")
def get_config():
    return {
        "provider": _config.agent.provider,
        "model": _config.ollama.model,
        "temperature": _config.ollama.temperature,
        "num_ctx": _config.ollama.num_ctx,
        "system_prompt": _config.agent.system_prompt,
        "openai_compat": {
            "base_url": _config.openai_compat.base_url,
            "model": _config.openai_compat.model,
            "max_tokens": _config.openai_compat.max_tokens,
        },
        "skills": _agent.memory.list_skills(),
        "memories": _agent.memory.list_memories(),
        "token_estimate": _agent.token_estimate(),
        "message_count": _agent.message_count(),
        "backend_capabilities": _agent.backend_capabilities(),
    }


@app.get("/api/backends")
def list_backends():
    """Mövcud backendlərin statusunu yoxlayır."""
    backends = detect_available_backends(_config)
    active = _config.agent.provider
    return {"active": active, "backends": backends}


@app.post("/api/config")
def update_config(data: dict, _: None = Depends(check_api_key)):
    if "provider" in data:
        _agent.set_provider(data["provider"])
    if "model" in data:
        _config.ollama.model = data["model"]
        _agent.set_model(data["model"])
    if "temperature" in data:
        _config.ollama.temperature = float(data["temperature"])
    if "num_ctx" in data:
        _config.ollama.num_ctx = int(data["num_ctx"])
    if "system_prompt" in data:
        _config.agent.system_prompt = data["system_prompt"]
        _agent.reload_memory()
    if "openai_compat" in data:
        oc = data["openai_compat"]
        if "base_url" in oc:
            _config.openai_compat.base_url = str(oc["base_url"])
        if "api_key" in oc:
            _config.openai_compat.api_key = str(oc["api_key"])
        if "model" in oc:
            _config.openai_compat.model = str(oc["model"])
        if "max_tokens" in oc:
            _config.openai_compat.max_tokens = int(oc["max_tokens"])
    _reset_sessions()
    _config.save()
    return {"status": "saved"}


@app.post("/api/clear")
def clear_chat(_: None = Depends(check_api_key)):
    _agent.clear()
    _reset_sessions()
    return {"status": "cleared"}


@app.post("/api/reload")
def reload_memory(_: None = Depends(check_api_key)):
    _agent.reload_memory()
    return {
        "status": "reloaded",
        "skills": _agent.memory.list_skills(),
        "memories": _agent.memory.list_memories(),
    }


@app.get("/api/export")
def export_chat():
    md = _agent.export_markdown()
    return PlainTextResponse(md, media_type="text/markdown",
                              headers={"Content-Disposition": "attachment; filename=conversation.md"})


@app.post("/api/batch")
def run_batch(data: dict):
    prompts = [str(item).strip() for item in data.get("prompts", []) if str(item).strip()]
    if not prompts:
        raise HTTPException(400, "No prompts provided")

    model = str(data.get("model", "")).strip()
    max_workers = max(1, min(int(data.get("max_workers", len(prompts))), len(prompts)))
    use_multi_agent = bool(data.get("multi_agent", False))
    template_name = str(data.get("template") or "").strip()
    supervisor = data.get("supervisor") or {"role": "Supervisor"}
    workers = data.get("workers") or [{"role": "Developer"}, {"role": "Researcher"}]
    log_event(
        logger,
        logging.INFO,
        "web_batch_started",
        prompt_count=len(prompts),
        max_workers=max_workers,
        multi_agent=use_multi_agent,
        model=model or _config.ollama.model,
    )

    def run_one(index: int, prompt: str) -> dict[str, Any]:
        cfg = _config_for_host(_config, _next_llama_cpp_host())
        if model:
            temp_agent = _make_agent(cfg)
            temp_agent.set_model(model)
            cfg = temp_agent.config
        if use_multi_agent:
            if template_name:
                mas = MultiAgentSystem.from_template(cfg, template_name, supervisor_override=data.get("supervisor"), workers_override=data.get("workers"))
            else:
                mas = MultiAgentSystem(cfg, supervisor, workers)
            final_answer = ""
            events: list[dict[str, Any]] = []
            fallback_parts: list[str] = []
            for event in mas.chat(prompt, interrupt=interrupt_event):
                if event["type"] in {"agent_chat", "tool_call", "tool_result", "info", "error"}:
                    events.append(event)
                if event["type"] == "agent_chat" and event.get("data"):
                    fallback_parts.append(event["data"])
                if event["type"] == "final":
                    final_answer = event["data"]
            if not final_answer:
                final_answer = "".join(fallback_parts).strip()
            return {"index": index, "prompt": prompt, "response": final_answer, "events": events}

        agent = _make_agent(cfg)
        if model:
            agent.set_model(model)
        result = _run_prompt_to_text(agent, prompt, interrupt=interrupt_event)
        return {"index": index, "prompt": prompt, **result}

    results: list[dict[str, Any]] = []
    with _managed_interrupt_event() as interrupt_event:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(run_one, idx, prompt): idx
                for idx, prompt in enumerate(prompts)
            }
            for future in as_completed(future_map):
                results.append(future.result())
    results.sort(key=lambda item: item["index"])
    log_event(
        logger,
        logging.INFO,
        "web_batch_completed",
        prompt_count=len(prompts),
        result_count=len(results),
        multi_agent=use_multi_agent,
    )
    return {"results": results}


@app.post("/api/chat")
def run_chat(data: dict):
    message = str(data.get("message", "")).strip()
    images = data.get("images", []) or []
    session_id = _safe_name(str(data.get("session_id") or "")).strip()
    model = str(data.get("model") or "").strip()

    if not message and not images:
        raise HTTPException(400, "No message or images provided")

    with _managed_interrupt_event() as interrupt_event:
        if session_id:
            agent = _get_session_agent(session_id)
            with _get_session_run_lock(session_id):
                structured_agent, structured_prompt = _prepare_structured_chat(agent, data)
                active_agent = structured_agent or agent
                active_prompt = structured_prompt if structured_agent else message
                result = _run_prompt_to_text(active_agent, active_prompt, images=images, interrupt=interrupt_event)
                if structured_agent is None:
                    _persist_session(session_id, agent)
                    return {"session_id": session_id, **result}
            return {"session_id": session_id, **result}

        cfg = _config_for_host(_config, _next_llama_cpp_host())
        agent = _make_agent(cfg)
        if model:
            agent.set_model(model)
        structured_agent, structured_prompt = _prepare_structured_chat(agent, data)
        active_agent = structured_agent or agent
        active_prompt = structured_prompt if structured_agent else message
        result = _run_prompt_to_text(active_agent, active_prompt, images=images, interrupt=interrupt_event)
        return {"session_id": "", **result}


# ── Skills CRUD ────────────────────────────────────────────────────────────

@app.get("/api/skills")
async def list_skills():
    mem = _agent.memory
    result = {}
    for name in mem.list_skills():
        path = mem.skills_dir / f"{name}.md"
        result[name] = path.read_text(encoding="utf-8") if path.exists() else ""
    return result


@app.get("/api/skills/{name}")
async def get_skill(name: str):
    path = _agent.memory.skills_dir / f"{_safe_name(name)}.md"
    if not path.exists():
        raise HTTPException(404, "Skill not found")
    return {"name": name, "content": path.read_text(encoding="utf-8")}


@app.post("/api/skills/{name}")
async def save_skill(name: str, data: dict, _: None = Depends(check_api_key)):
    content = data.get("content", "")
    result = _agent.memory.learn_skill(name, content)
    _agent.reload_memory()
    return {"status": "saved", "result": result}


@app.delete("/api/skills/{name}")
async def delete_skill(name: str, _: None = Depends(check_api_key)):
    path = _agent.memory.skills_dir / f"{_safe_name(name)}.md"
    if path.exists():
        path.unlink()
        _agent.reload_memory()
        return {"status": "deleted"}
    raise HTTPException(404, "Skill not found")


# ── Memory CRUD ────────────────────────────────────────────────────────────

@app.get("/api/memory")
async def list_memory():
    mem = _agent.memory
    result = {}
    for name in mem.list_memories():
        path = mem.memory_dir / f"{name}.md"
        result[name] = path.read_text(encoding="utf-8") if path.exists() else ""
    return result


@app.get("/api/memory/{name}")
async def get_memory(name: str):
    path = _agent.memory.memory_dir / f"{_safe_name(name)}.md"
    if not path.exists():
        raise HTTPException(404, "Memory not found")
    return {"name": name, "content": path.read_text(encoding="utf-8")}


@app.post("/api/memory/{name}")
async def save_memory(name: str, data: dict, _: None = Depends(check_api_key)):
    content = data.get("content", "")
    result = _agent.memory.remember(name, content)
    return {"status": "saved", "result": result}


@app.delete("/api/memory/{name}")
async def delete_memory(name: str, _: None = Depends(check_api_key)):
    path = _agent.memory.memory_dir / f"{_safe_name(name)}.md"
    if path.exists():
        path.unlink()
        return {"status": "deleted"}
    raise HTTPException(404, "Memory not found")


# ── Plugins ───────────────────────────────────────────────────────────────

@app.get("/api/plugins")
async def list_plugins():
    from ..plugins.loader import PluginLoader
    plugins_cfg = _config.plugins if _config else None
    if not plugins_cfg or not plugins_cfg.enabled:
        return {"plugins": [], "enabled": False}
    from pathlib import Path as _Path
    plugins_dir = _Path(plugins_cfg.plugins_dir)
    if not plugins_dir.is_absolute():
        plugins_dir = _Path(__file__).parent.parent.parent / plugins_dir
    loader = PluginLoader(plugins_dir)
    result = loader.load()
    return {
        "enabled": True,
        "plugins_dir": str(plugins_dir),
        "plugins": [t.plugin_metadata() for t in result.loaded],
        "skipped": result.skipped,
        "errors": [{"file": f, "error": e} for f, e in result.errors],
    }


# ── Templates ─────────────────────────────────────────────────────────────

@app.get("/api/templates")
async def list_mission_templates():
    from ..mission_templates import describe_templates
    return {"templates": describe_templates()}


@app.get("/api/templates/{name}")
async def get_mission_template(name: str):
    from ..mission_templates import get_template
    tmpl = get_template(name)
    if not tmpl:
        raise HTTPException(404, "Template not found")
    return {"name": name, **tmpl}


# ── Missions ───────────────────────────────────────────────────────────────

@app.get("/api/missions")
async def list_missions(limit: int = 50, status: str = ""):
    if not _store:
        return {"missions": []}
    return {"missions": _store.list_missions(limit=limit, status=status or None)}


@app.get("/api/missions/{mission_id}")
async def get_mission(mission_id: str):
    if not _store:
        raise HTTPException(503, "Store not initialized")
    mission = _store.get_mission(mission_id)
    if not mission:
        raise HTTPException(404, "Mission not found")
    return mission


@app.delete("/api/missions/{mission_id}")
async def delete_mission(mission_id: str, _: None = Depends(check_api_key)):
    if not _store:
        raise HTTPException(503, "Store not initialized")
    deleted = _store.delete_mission(mission_id)
    if not deleted:
        raise HTTPException(404, "Mission not found")
    return {"status": "deleted", "mission_id": mission_id}


@app.get("/api/sessions")
async def list_sessions(limit: int = 50):
    if not _store:
        return {"sessions": []}
    return {"sessions": _store.list_sessions(limit=limit)}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, _: None = Depends(check_api_key)):
    if not _store:
        raise HTTPException(503, "Store not initialized")
    with _session_lock:
        _session_agents.pop(session_id, None)
    _drop_session_run_lock(session_id)
    deleted = _store.delete_session(session_id)
    if not deleted:
        raise HTTPException(404, "Session not found")
    return {"status": "deleted", "session_id": session_id}


# ── WebSocket ──────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    current_session_id: str = ""
    current_interrupt_event: threading.Event | None = None
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            user_message = data.get("message", "").strip()
            images = data.get("images", [])
            session_id = _safe_name(data.get("session_id") or str(uuid.uuid4()))
            current_session_id = session_id
            log_event(
                logger,
                logging.INFO,
                "websocket_message_received",
                session_id=session_id,
                has_images=bool(images),
                message_preview=user_message,
            )
            await ws.send_text(json.dumps(session_event(session_id)))
            if not user_message and not images:
                continue
            agent = _get_session_agent(session_id)
            queue: asyncio.Queue[Any] = asyncio.Queue()
            done_marker = object()
            loop = asyncio.get_running_loop()

            with _managed_interrupt_event() as interrupt_event:
                current_interrupt_event = interrupt_event
                def worker() -> None:
                    try:
                        with _get_session_run_lock(session_id):
                            for event in agent.chat(user_message, images=images, interrupt=interrupt_event):
                                asyncio.run_coroutine_threadsafe(queue.put(event), loop).result()
                            _persist_session(session_id, agent)
                    except Exception as exc:
                        asyncio.run_coroutine_threadsafe(
                            queue.put(error_event(str(exc), code="websocket_error")),
                            loop,
                        ).result()
                    finally:
                        asyncio.run_coroutine_threadsafe(queue.put(done_marker), loop).result()

                threading.Thread(target=worker, daemon=True).start()

                while True:
                    event = await queue.get()
                    if event is done_marker:
                        break
                    await ws.send_text(json.dumps(event))
                current_interrupt_event = None
    except WebSocketDisconnect:
        if current_interrupt_event is not None:
            current_interrupt_event.set()
        log_event(logger, logging.INFO, "websocket_disconnected",
                  session_id=current_session_id)
    except Exception as e:
        log_event(logger, logging.ERROR, "websocket_error", error=str(e))
        try:
            await ws.send_text(json.dumps(error_event(str(e), code="websocket_error")))
        except Exception:
            pass
