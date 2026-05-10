"""FastAPI web server with WebSocket streaming."""
import copy
import json
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from ..config import Config
from ..core import Agent
from ..events import error_event, session_event
from ..llm_backend import detect_available_backends
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
_store: SessionStore = None
_start_time: float = time.time()
logger = logging.getLogger("web")
logger.addHandler(logging.NullHandler())

_VERSION = "2.0.0"


def init(config: Config):
    global _config, _agent, _session_agents, _store, _start_time
    _config = config
    _agent = _make_agent(config)
    _session_agents = {}
    _start_time = time.time()
    db_path = Path(config.agent.memory_dir).parent / "sessions.db"
    _store = SessionStore(db_path)


def run_web(config: Config):
    init(config)
    host = config.web.host or "127.0.0.1"
    port = int(config.web.port or 8080)
    log_event(logger, logging.INFO, "web_server_starting", host=host, port=port)
    uvicorn.run(app, host=host, port=port, log_level="warning")


def _make_agent(config: Config) -> Agent:
    return build_agent(config)


def _clone_agent_from(base: Agent) -> Agent:
    clone = _make_agent(copy.deepcopy(base.config))
    clone.load_messages(list(base.messages))
    return clone


def _get_session_agent(session_id: str) -> Agent:
    with _session_lock:
        agent = _session_agents.get(session_id)
        if agent is None:
            agent = _make_agent(copy.deepcopy(_config))
            # Restart-dan sonra history-ni SQLite-dan yüklə
            if _store:
                saved_messages = _store.load_session(session_id)
                if saved_messages:
                    agent.load_messages(saved_messages)
            _session_agents[session_id] = agent
        return agent


def _persist_session(session_id: str, agent: Agent) -> None:
    if _store:
        try:
            _store.save_session(session_id, list(agent.messages))
        except Exception as exc:
            log_event(logger, logging.WARNING, "session_persist_failed",
                      session_id=session_id, error=str(exc))


def _reset_sessions():
    global _session_agents
    with _session_lock:
        _session_agents = {}


def _run_prompt_to_text(agent: Agent, prompt: str, images: list[str] | None = None) -> dict[str, Any]:
    text_parts: list[str] = []
    tool_events: list[dict[str, Any]] = []
    for event in agent.chat(prompt, images=images):
        if event["type"] == "text":
            text_parts.append(event["data"])
        elif event["type"] in {"tool_call", "tool_result", "error"}:
            tool_events.append(event)
        elif event["type"] == "done":
            break
    return {"response": "".join(text_parts), "events": tool_events}


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name)[:60]


# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
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
    return HTMLResponse((STATIC_DIR / "index.html").read_text())


@app.get("/api/models")
async def list_models():
    try:
        return {"models": _agent.available_models()}
    except Exception as e:
        return {"models": [], "error": str(e)}


@app.get("/api/config")
async def get_config():
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
async def list_backends():
    """Mövcud backendlərin statusunu yoxlayır."""
    backends = detect_available_backends(_config)
    active = _config.agent.provider
    return {"active": active, "backends": backends}


@app.post("/api/config")
async def update_config(data: dict, _: None = Depends(check_api_key)):
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
async def clear_chat(_: None = Depends(check_api_key)):
    _agent.clear()
    _reset_sessions()
    return {"status": "cleared"}


@app.post("/api/reload")
async def reload_memory(_: None = Depends(check_api_key)):
    _agent.reload_memory()
    return {
        "status": "reloaded",
        "skills": _agent.memory.list_skills(),
        "memories": _agent.memory.list_memories(),
    }


@app.get("/api/export")
async def export_chat():
    md = _agent.export_markdown()
    return PlainTextResponse(md, media_type="text/markdown",
                              headers={"Content-Disposition": "attachment; filename=conversation.md"})


@app.post("/api/batch")
async def run_batch(data: dict):
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
        cfg = copy.deepcopy(_config)
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
            for event in mas.chat(prompt):
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
        result = _run_prompt_to_text(agent, prompt)
        return {"index": index, "prompt": prompt, **result}

    results: list[dict[str, Any]] = []
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
async def delete_session(session_id: str, _: None = Depends(check_api_key)):
    if not _store:
        raise HTTPException(503, "Store not initialized")
    with _session_lock:
        _session_agents.pop(session_id, None)
    deleted = _store.delete_session(session_id)
    if not deleted:
        raise HTTPException(404, "Session not found")
    return {"status": "deleted", "session_id": session_id}


# ── WebSocket ──────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    current_session_id: str = ""
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
            for event in agent.chat(user_message, images=images):
                await ws.send_text(json.dumps(event))
            # Hər turn-dan sonra session-u persist et
            _persist_session(session_id, agent)
    except WebSocketDisconnect:
        log_event(logger, logging.INFO, "websocket_disconnected",
                  session_id=current_session_id)
    except Exception as e:
        log_event(logger, logging.ERROR, "websocket_error", error=str(e))
        try:
            await ws.send_text(json.dumps(error_event(str(e), code="websocket_error")))
        except Exception:
            pass
