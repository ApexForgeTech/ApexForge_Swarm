import json
import logging
import os
import threading
import uuid
import webbrowser
from pathlib import Path

from ..config import Config
from ..events import error_event
from ..logging_utils import log_event
from ..multi_agent import MultiAgentSystem
from ..runtime import build_agent
from ..store import SessionStore
from . import app as web_app

try:
    import webview
    try:
        from webview.errors import WebViewException
    except Exception:
        WebViewException = Exception
except Exception:
    webview = None
    WebViewException = Exception

logger = logging.getLogger("desktop")
logger.addHandler(logging.NullHandler())


class DesktopApp:
    def __init__(self, config: Config):
        self.config = config
        self.agent = build_agent(config)
        self.mas = self._create_multi_agent(
            {"role": "Project Manager"},
            [{"role": "Developer"}, {"role": "Tester"}],
        )
        self.window = None
        self._busy_lock = threading.Lock()
        self._interrupt_event = threading.Event()
        db_path = Path(config.agent.memory_dir).parent / "sessions.db"
        self._store = SessionStore(db_path)

    def _create_multi_agent(self, supervisor_data, workers_data):
        return MultiAgentSystem(self.config, supervisor_data, workers_data)

    def _emit(self, event):
        if not self.window:
            return
        payload = json.dumps(event)
        log_event(
            logger,
            logging.DEBUG,
            "desktop_event_emitted",
            event_type=event.get("type"),
            agent=event.get("agent"),
        )
        self.window.evaluate_js(f"handleEvent({payload})")

    def start(self):
        if webview is None:
            raise RuntimeError("pywebview is not installed.")
        log_event(logger, logging.INFO, "desktop_window_starting")

        html_path = Path(__file__).parent / "static" / "comic_ui.html"
        self.window = webview.create_window(
            "ApexForge Swarm — Comic Edition",
            str(html_path),
            js_api=self,
            width=1000,
            height=800,
            background_color="#0f172a",
        )
        webview.start(debug=False)

    # JS API

    def send_message(self, message, supervisor_data=None, workers_data=None, template_name=None):
        """Called from JS when the user launches a mission."""
        mission_id = str(uuid.uuid4())

        def run():
            if not self._busy_lock.acquire(blocking=False):
                log_event(logger, logging.WARNING, "desktop_mission_rejected_busy")
                self._emit(error_event("A mission is already running. Wait for it to finish first.", code="mission_busy"))
                return

            self._store.create_mission(
                mission_id,
                message,
                provider=self.config.agent.provider,
                model=self.config.ollama.model,
            )
            final_result = ""
            status = "completed"
            try:
                self._interrupt_event.clear()
                log_event(
                    logger,
                    logging.INFO,
                    "desktop_mission_started",
                    mission_id=mission_id,
                    message_preview=message,
                    supervisor_data=supervisor_data or {"role": "Supervisor"},
                    workers_data=workers_data or [],
                    template_name=template_name or "",
                )
                if template_name:
                    self.mas = MultiAgentSystem.from_template(
                        self.config,
                        template_name,
                        supervisor_override=supervisor_data,
                        workers_override=workers_data,
                    )
                elif supervisor_data is not None or workers_data is not None:
                    self.mas = self._create_multi_agent(supervisor_data or {"role": "Supervisor"}, workers_data or [])

                for event in self.mas.chat(message, interrupt=self._interrupt_event):
                    self._emit(event)
                    self._store.append_mission_event(mission_id, event)
                    if event.get("type") == "final":
                        final_result = event.get("data", "")
            except Exception as exc:
                log_event(logger, logging.ERROR, "desktop_mission_failed", mission_id=mission_id, error=str(exc))
                self._emit(error_event(str(exc), code="desktop_mission_failed"))
                status = "failed"
            finally:
                self._store.finish_mission(mission_id, final_result, status=status)
                log_event(logger, logging.INFO, "desktop_mission_finished", mission_id=mission_id, status=status)
                self._interrupt_event.clear()
                self._busy_lock.release()

        threading.Thread(target=run, daemon=True).start()
        return {"status": "started", "mission_id": mission_id}

    def update_roles(self, supervisor_data, workers_data):
        """Update roles and models, re-init MAS."""
        if self._busy_lock.locked():
            log_event(logger, logging.WARNING, "desktop_roles_update_rejected_busy")
            return {"status": "error", "message": "Mission is running. Wait for completion before changing the team."}
        try:
            self.mas = self._create_multi_agent(supervisor_data, workers_data)
            log_event(
                logger,
                logging.INFO,
                "desktop_roles_updated",
                supervisor_data=supervisor_data,
                workers_data=workers_data,
            )
            return {"status": "success"}
        except Exception as exc:
            log_event(logger, logging.ERROR, "desktop_roles_update_failed", error=str(exc))
            return {"status": "error", "message": str(exc)}

    def cancel_mission(self):
        if not self._busy_lock.locked():
            return {"status": "idle", "message": "No mission is currently running."}
        self._interrupt_event.set()
        log_event(logger, logging.WARNING, "desktop_mission_cancel_requested")
        return {"status": "cancelling", "message": "Mission interruption requested."}

    def get_models(self):
        """Return list of available models for the UI to pick from."""
        try:
            models = self.agent.available_models()
        except Exception:
            models = []

        current = (self.config.ollama.model or "").strip()
        merged = []
        for item in models + ([current] if current else []):
            if item and item not in merged:
                merged.append(item)
        return merged

    def get_backend_capabilities(self):
        return self.agent.backend_capabilities()

    def get_templates(self):
        """Return all mission templates for the UI template picker."""
        from ..mission_templates import TEMPLATES, describe_templates
        items = describe_templates()
        for item in items:
            tmpl = TEMPLATES[item["name"]]
            item["supervisor_role"] = tmpl["supervisor"].get("role", "Supervisor")
            item["workers"] = [w["role"] for w in tmpl["workers"]]
            item["hint"] = tmpl.get("hint", "")
        return items

    def get_plugins(self):
        """Return metadata for all loaded plugin tools."""
        result = getattr(self.agent, "plugin_load_result", None)
        if result is None:
            return {"loaded": [], "errors": []}
        return {
            "loaded": [t.plugin_metadata() for t in result.loaded],
            "errors": [{"file": f, "error": e} for f, e in result.errors],
        }

    def get_mission_history(self, limit: int = 8):
        """Return recent missions from the store."""
        if not self._store:
            return []
        return self._store.list_missions(limit=limit)

    def get_runtime_diagnostics(self):
        native_desktop_available = webview is not None
        desktop_fallback_allowed = os.getenv("APEXFORGE_ALLOW_DESKTOP_WEB_FALLBACK", "").strip().lower() in {"1", "true", "yes"}
        desktop_mode = "native" if native_desktop_available else ("browser-fallback-enabled" if desktop_fallback_allowed else "browser-fallback-disabled")
        desktop_hint = (
            "Native desktop stack is ready."
            if native_desktop_available
            else "Install pywebview with a supported GUI backend to use the embedded desktop window."
        )
        return {
            "provider": self.config.agent.provider,
            "model": self.config.ollama.model,
            "native_desktop_available": native_desktop_available,
            "desktop_fallback_allowed": desktop_fallback_allowed,
            "desktop_mode": desktop_mode,
            "desktop_hint": desktop_hint,
            "backend_capabilities": self.agent.backend_capabilities(),
        }


def run_desktop(config: Config):
    app = DesktopApp(config)
    try:
        app.start()
    except (WebViewException, RuntimeError) as exc:
        allow_fallback = os.getenv("APEXFORGE_ALLOW_DESKTOP_WEB_FALLBACK", "").strip().lower() in {"1", "true", "yes"}
        if not allow_fallback:
            log_event(logger, logging.ERROR, "desktop_start_failed", error=str(exc), fallback_allowed=False)
            raise SystemExit(
                "Desktop mode requires pywebview and a native GUI backend. "
                "It is currently falling back to the browser because that desktop stack is unavailable. "
                "Install the desktop dependencies or use --web explicitly."
            ) from exc
        import uvicorn

        web_app.init(config)
        host = config.web.host or "127.0.0.1"
        port = int(config.web.port or 8080)
        browser_host = "127.0.0.1" if host == "0.0.0.0" else host
        url = f"http://{browser_host}:{port}"
        log_event(logger, logging.WARNING, "desktop_fallback_to_web", url=url, error=str(exc))
        print(f"[desktop fallback] Native webview acilmadi. Web UI basladilir: {url}")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        uvicorn.run(web_app.app, host=host, port=port, log_level="warning")
