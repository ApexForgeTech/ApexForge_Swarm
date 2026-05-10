import json
import os
import re
import threading
import logging
from pathlib import Path
import subprocess
import time
from dataclasses import dataclass, field
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional
from urllib.parse import urljoin, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import shutil

from .errors import BackendHTTPError, BackendNotReady, BackendStreamError, BackendTimeout
from .logging_utils import log_event

logger = logging.getLogger("llm_backend")
logger.addHandler(logging.NullHandler())

_BACKEND_LOCKS: Dict[str, threading.RLock] = {}
_BACKEND_LOCKS_GUARD = threading.Lock()


def _backend_lock_for(key: str) -> threading.RLock:
    with _BACKEND_LOCKS_GUARD:
        lock = _BACKEND_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _BACKEND_LOCKS[key] = lock
        return lock


@dataclass
class LLMToolCallFunction:
    name: str
    arguments: Any


@dataclass
class LLMToolCall:
    id: Optional[str]
    function: LLMToolCallFunction


@dataclass
class LLMChunk:
    content: str = ""
    tool_calls: List[LLMToolCall] = field(default_factory=list)


@dataclass
class BackendCapabilities:
    provider: str
    multi_agent_supported: bool
    request_parallelism: str
    mixed_model_missions: str
    auto_start_supported: bool
    local_model_discovery: bool
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "multi_agent_supported": self.multi_agent_supported,
            "request_parallelism": self.request_parallelism,
            "mixed_model_missions": self.mixed_model_missions,
            "auto_start_supported": self.auto_start_supported,
            "local_model_discovery": self.local_model_discovery,
            "notes": list(self.notes),
        }


class BaseLLMBackend:
    def __init__(self, config):
        self.config = config

    def _lock_key(self) -> str:
        return f"{self.__class__.__name__}:default"

    @contextmanager
    def _lifecycle_slot(self):
        lock = _backend_lock_for(self._lock_key())
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    @contextmanager
    def _request_slot(self):
        serialize = os.getenv("APEXFORGE_SERIALIZE_LLM_REQUESTS", "").strip().lower() in {"1", "true", "yes"}
        if not serialize:
            yield
            return
        with self._lifecycle_slot():
            yield

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Generator[LLMChunk, None, None]:
        raise NotImplementedError

    def chat_once(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        raise NotImplementedError

    def list_models(self) -> List[str]:
        raise NotImplementedError

    def capabilities(self) -> BackendCapabilities:
        serialize = os.getenv("APEXFORGE_SERIALIZE_LLM_REQUESTS", "").strip().lower() in {"1", "true", "yes"}
        return BackendCapabilities(
            provider=self.__class__.__name__.replace("Backend", "").lower(),
            multi_agent_supported=True,
            request_parallelism="serialized" if serialize else "parallel",
            mixed_model_missions="provider_managed",
            auto_start_supported=False,
            local_model_discovery=False,
            notes=[],
        )


class OllamaBackend(BaseLLMBackend):
    def _lock_key(self) -> str:
        return f"ollama:{self.config.ollama.host}:{self.config.ollama.model}"

    def _client(self):
        try:
            import ollama
        except ImportError as exc:
            raise RuntimeError(
                "Ollama backend selected, but Python package 'ollama' is not installed."
            ) from exc
        return ollama.Client(host=self.config.ollama.host)

    def _tool_calls_from_message(self, message: Any) -> List[LLMToolCall]:
        raw_tool_calls = getattr(message, "tool_calls", None)
        if raw_tool_calls is None and isinstance(message, dict):
            raw_tool_calls = message.get("tool_calls")
        tool_calls: List[LLMToolCall] = []
        for tc in raw_tool_calls or []:
            function = getattr(tc, "function", None)
            if function is None and isinstance(tc, dict):
                function = tc.get("function", {})
            name = getattr(function, "name", None) if function is not None else None
            if name is None and isinstance(function, dict):
                name = function.get("name")
            arguments = getattr(function, "arguments", None) if function is not None else None
            if arguments is None and isinstance(function, dict):
                arguments = function.get("arguments", {})
            tool_calls.append(
                LLMToolCall(
                    id=getattr(tc, "id", None) if not isinstance(tc, dict) else tc.get("id"),
                    function=LLMToolCallFunction(name=name or "", arguments=arguments or {}),
                )
            )
        return tool_calls

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Generator[LLMChunk, None, None]:
        with self._request_slot():
            log_event(
                logger,
                logging.INFO,
                "backend_request_started",
                provider="ollama",
                mode="stream",
                model=self.config.ollama.model,
                message_count=len(messages),
                tool_schema_count=len(tools or []),
            )
            client = self._client()
            stream = client.chat(
                model=self.config.ollama.model,
                messages=messages,
                tools=tools or None,
                stream=True,
                options={
                    "temperature": self.config.ollama.temperature,
                    "num_ctx": self.config.ollama.num_ctx,
                },
            )
            for chunk in stream:
                message = chunk.message if hasattr(chunk, "message") else chunk.get("message", {})
                content = getattr(message, "content", None)
                if content is None and isinstance(message, dict):
                    content = message.get("content", "")
                yield LLMChunk(
                    content=content or "",
                    tool_calls=self._tool_calls_from_message(message),
                )
            log_event(
                logger,
                logging.INFO,
                "backend_request_completed",
                provider="ollama",
                mode="stream",
                model=self.config.ollama.model,
            )

    def chat_once(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        with self._request_slot():
            log_event(
                logger,
                logging.INFO,
                "backend_request_started",
                provider="ollama",
                mode="once",
                model=self.config.ollama.model,
                message_count=len(messages),
                tool_schema_count=len(tools or []),
            )
            client = self._client()
            resp = client.chat(
                model=self.config.ollama.model,
                messages=messages,
                tools=tools or None,
                stream=False,
                options={
                    "temperature": self.config.ollama.temperature,
                    "num_ctx": self.config.ollama.num_ctx,
                },
            )
            message = resp.message if hasattr(resp, "message") else resp.get("message", {})
            content = getattr(message, "content", None)
            if content is None and isinstance(message, dict):
                content = message.get("content", "")
            log_event(
                logger,
                logging.INFO,
                "backend_request_completed",
                provider="ollama",
                mode="once",
                model=self.config.ollama.model,
                response_preview=content or "",
            )
            return content or ""

    def list_models(self) -> List[str]:
        try:
            models = self._client().list().models
            return [m.model for m in models]
        except Exception:
            pass
        try:
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=False)
            if result.returncode != 0:
                return []
            lines = result.stdout.splitlines()
            if lines and lines[0].strip().startswith("NAME"):
                lines = lines[1:]
            return [line.split()[0] for line in lines if line.strip()]
        except Exception:
            return []

    def capabilities(self) -> BackendCapabilities:
        serialize = os.getenv("APEXFORGE_SERIALIZE_LLM_REQUESTS", "").strip().lower() in {"1", "true", "yes"}
        notes = [
            "Ollama is the most flexible backend in this repo for multi-agent missions with per-agent model selection.",
            "Real throughput still depends on the Ollama server and available machine resources.",
        ]
        if serialize:
            notes.append("Global request serialization is enabled through APEXFORGE_SERIALIZE_LLM_REQUESTS.")
        return BackendCapabilities(
            provider="ollama",
            multi_agent_supported=True,
            request_parallelism="serialized" if serialize else "provider_managed",
            mixed_model_missions="supported",
            auto_start_supported=False,
            local_model_discovery=True,
            notes=notes,
        )


class LlamaCppBackend(BaseLLMBackend):
    def __init__(self, config):
        super().__init__(config)
        self._server_process: Optional[subprocess.Popen] = None
        self._running_model_source: str = ""

    def _lock_key(self) -> str:
        return f"llama_cpp:{self.config.llama_cpp.host}"

    @contextmanager
    def _request_slot(self):
        # A single llama.cpp server host can only serve one loaded model safely in
        # this architecture. Queue the whole request lifecycle to prevent model
        # switching races and HTTP 500s across multi-agent turns.
        with self._lifecycle_slot():
            yield

    def _base_url(self) -> str:
        return self.config.llama_cpp.host.rstrip("/") + "/"

    def _model_directory(self) -> Path:
        if self.config.llama_cpp.model_path:
            return Path(self.config.llama_cpp.model_path).expanduser().resolve().parent
        return Path.cwd() / ".runtime" / "models"

    def _active_model_writes(self) -> set[str]:
        model_dir = self._model_directory()
        if not model_dir.exists() or not shutil.which("lsof"):
            return set()
        try:
            result = subprocess.run(
                ["lsof", "+D", str(model_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            return set()
        active: set[str] = set()
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 9:
                continue
            fd = parts[3]
            path = parts[-1]
            if "w" in fd and path.endswith(".gguf"):
                active.add(str(Path(path).resolve()))
        return active

    def _local_model_map(self) -> Dict[str, str]:
        model_dir = self._model_directory()
        if not model_dir.exists():
            return {}

        active_writes = self._active_model_writes()
        files = sorted(p.resolve() for p in model_dir.glob("*.gguf"))
        available: Dict[str, str] = {}
        shard_groups: Dict[str, Dict[str, Any]] = {}

        for path in files:
            if str(path) in active_writes:
                continue

            match = re.match(r"^(?P<base>.+)-(?P<index>\d+)-of-(?P<total>\d+)\.gguf$", path.name)
            if not match:
                available[path.name] = str(path)
                continue

            base = match.group("base")
            total = int(match.group("total"))
            group = shard_groups.setdefault(base, {"total": total, "parts": {}})
            group["parts"][int(match.group("index"))] = path

        for base, info in shard_groups.items():
            total = int(info["total"])
            parts = info["parts"]
            if all(index in parts for index in range(1, total + 1)):
                available[f"{base}.gguf"] = str(parts[1])

        return dict(sorted(available.items()))

    def _canonical_model_name(self, name: str) -> str:
        match = re.match(r"^(?P<base>.+)-\d+-of-\d+\.gguf$", name or "")
        if match:
            return f"{match.group('base')}.gguf"
        return name

    def _local_model_names(self) -> List[str]:
        return list(self._local_model_map().keys())

    def resolve_model_path(self, model_name: str) -> Optional[str]:
        return self._local_model_map().get(model_name)

    def _desired_model_source(self) -> str:
        if self.config.llama_cpp.model_path:
            return f"path:{Path(self.config.llama_cpp.model_path).expanduser().resolve()}"
        if self.config.llama_cpp.hf_model:
            return f"hf:{self.config.llama_cpp.hf_model}"
        return ""

    def _stop_server(self):
        if not self._server_process:
            return
        log_event(
            logger,
            logging.INFO,
            "llama_server_stopping",
            host=self.config.llama_cpp.host,
            model_source=self._running_model_source,
        )
        if self._server_process.poll() is None:
            self._server_process.terminate()
            try:
                self._server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
                self._server_process.wait(timeout=5)
        self._server_process = None
        self._running_model_source = ""

    def _is_local_host(self) -> bool:
        parsed = urlparse(self.config.llama_cpp.host)
        return (parsed.hostname or "127.0.0.1") in {"127.0.0.1", "localhost", "::1"}

    def _listener_pids(self) -> List[int]:
        parsed = urlparse(self.config.llama_cpp.host)
        port = str(parsed.port or 8081)
        if not shutil.which("lsof"):
            return []
        try:
            result = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            return []
        pids: List[int] = []
        for line in result.stdout.splitlines():
            if line.startswith("p"):
                try:
                    pids.append(int(line[1:]))
                except ValueError:
                    continue
        return pids

    def _stop_conflicting_server(self):
        if not self._is_local_host():
            return
        current_pid = self._server_process.pid if self._server_process else None
        for pid in self._listener_pids():
            if current_pid and pid == current_pid:
                continue
            try:
                subprocess.run(["kill", str(pid)], check=False)
            except Exception:
                continue
        time.sleep(1.0)

    def _is_transient_models_http_error(self, method: str, path: str, status_code: int, body: str) -> bool:
        normalized_path = "/" + path.lstrip("/")
        normalized_body = (body or "").lower()
        return (
            method.upper() == "GET"
            and normalized_path == "/v1/models"
            and status_code == 503
            and "loading model" in normalized_body
        )

    def _is_transient_models_url_error(self, method: str, path: str, reason: str) -> bool:
        normalized_path = "/" + path.lstrip("/")
        normalized_reason = (reason or "").lower()
        return (
            method.upper() == "GET"
            and normalized_path == "/v1/models"
            and any(marker in normalized_reason for marker in ("connection refused", "errno 111", "failed to establish a new connection"))
        )

    def _is_context_overflow_error(self, method: str, path: str, status_code: int, body: str) -> bool:
        normalized_path = "/" + path.lstrip("/")
        normalized_body = (body or "").lower()
        return (
            method.upper() == "POST"
            and normalized_path == "/v1/chat/completions"
            and status_code == 500
            and "context size has been exceeded" in normalized_body
        )

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        url = urljoin(self._base_url(), path.lstrip("/"))
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(
            url,
            data=data,
            method=method.upper(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.llama_cpp.api_key}",
            },
        )
        try:
            with urlopen(req, timeout=timeout or self.config.llama_cpp.request_timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
        except HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                pass
            detail = f"HTTP {exc.code}: {exc.reason}"
            if body:
                detail += f" | {re.sub(r'\s+', ' ', body)[:300]}"
            transient = self._is_transient_models_http_error(method, path, exc.code, body)
            if self._is_context_overflow_error(method, path, exc.code, body):
                detail = (
                    f"{detail}\n\n"
                    f"Hint: llama.cpp context window is too small for this request. "
                    f"Current `num_ctx` is {self.config.ollama.num_ctx}. "
                    f"Increase it with `OLLAMA_NUM_CTX` or `LLAMA_CPP_NUM_CTX`, then restart the process/server. "
                    f"If the conversation is already long, start a fresh session or reduce attached context."
                )
            log_event(
                logger,
                logging.INFO if transient else logging.ERROR,
                "backend_http_waiting" if transient else "backend_http_error",
                provider="llama_cpp",
                method=method.upper(),
                path=path,
                host=self.config.llama_cpp.host,
                status_code=exc.code,
                error=detail,
            )
            raise BackendHTTPError(
                message=detail,
                code="backend_http_error",
                provider="llama_cpp",
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            reason = str(exc.reason)
            transient = self._is_transient_models_url_error(method, path, reason)
            log_event(
                logger,
                logging.INFO if transient else logging.ERROR,
                "backend_url_waiting" if transient else "backend_url_error",
                provider="llama_cpp",
                method=method.upper(),
                path=path,
                host=self.config.llama_cpp.host,
                error=reason,
            )
            raise BackendNotReady(
                message=f"Cannot reach llama.cpp at {self.config.llama_cpp.host}: {reason}",
                code="backend_not_ready",
                provider="llama_cpp",
            ) from exc

    def _normalize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        last_tool_ids: Dict[str, str] = {}
        call_index = 0

        for msg in messages:
            role = msg.get("role")
            if role not in {"system", "user", "assistant", "tool"}:
                continue

            entry: Dict[str, Any] = {"role": role}
            if role in {"system", "user", "assistant"}:
                entry["content"] = str(msg.get("content", "") or "")

            if role == "assistant" and msg.get("tool_calls"):
                tool_calls = []
                for tc in msg.get("tool_calls", []):
                    call_index += 1
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    raw_args = fn.get("arguments", {})
                    args = raw_args if isinstance(raw_args, str) else json.dumps(raw_args, ensure_ascii=False)
                    call_id = tc.get("id") or f"call_{call_index}"
                    if name:
                        last_tool_ids[name] = call_id
                    tool_calls.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": args},
                        }
                    )
                entry["tool_calls"] = tool_calls

            if role == "tool":
                entry["content"] = str(msg.get("content", "") or "")
                if msg.get("name"):
                    entry["name"] = msg["name"]
                entry["tool_call_id"] = msg.get("tool_call_id") or last_tool_ids.get(msg.get("name", ""), f"tool_{call_index + 1}")

            normalized.append(entry)

        return normalized

    def _parse_tool_calls(self, raw_tool_calls: Any) -> List[LLMToolCall]:
        tool_calls: List[LLMToolCall] = []
        for tc in raw_tool_calls or []:
            function = tc.get("function", {}) if isinstance(tc, dict) else {}
            raw_args = function.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = raw_args
            else:
                arguments = raw_args
            tool_calls.append(
                LLMToolCall(
                    id=tc.get("id") if isinstance(tc, dict) else None,
                    function=LLMToolCallFunction(
                        name=function.get("name", ""),
                        arguments=arguments,
                    ),
                )
            )
        return tool_calls

    def _ping(self) -> bool:
        try:
            self._request_json("GET", "/v1/models", timeout=min(15, self.config.llama_cpp.request_timeout))
            return True
        except Exception:
            return False

    def _server_model_ids(self) -> List[str]:
        response = self._request_json("GET", "/v1/models", timeout=min(15, self.config.llama_cpp.request_timeout))
        return [item.get("id", "") for item in response.get("data", []) if item.get("id")]

    def _desired_model_ids(self) -> set[str]:
        desired = {self.config.ollama.model} if self.config.ollama.model else set()
        if self.config.llama_cpp.model_path:
            path = Path(self.config.llama_cpp.model_path).expanduser().resolve()
            desired.add(path.name)
            match = re.match(r"^(?P<base>.+)-\d+-of-\d+\.gguf$", path.name)
            if match:
                desired.add(f"{match.group('base')}.gguf")
        return {item for item in desired if item}

    def _loaded_model_matches_desired(self) -> bool:
        desired = self._desired_model_ids()
        if not desired:
            return True
        loaded = set(self._server_model_ids())
        return bool(loaded & desired)

    def _wait_until_ready(self):
        deadline = time.time() + max(5, int(self.config.llama_cpp.startup_timeout))
        while time.time() < deadline:
            if self._ping():
                return
            if self._server_process and self._server_process.poll() is not None:
                raise BackendNotReady(
                    message="llama-server process exited before becoming ready.",
                    code="backend_not_ready",
                    provider="llama_cpp",
                    recoverable=False,
                )
            time.sleep(0.5)
        raise BackendTimeout(
            message=f"Timed out waiting for llama-server to become ready ({self.config.llama_cpp.startup_timeout}s).",
            code="backend_timeout",
            provider="llama_cpp",
        )

    def _start_server(self):
        binary = self.config.llama_cpp.server_binary or "llama-server"
        resolved_binary = binary if "/" in binary else shutil.which(binary) or binary
        if not shutil.which(binary) and "/" not in binary and resolved_binary == binary:
            from .errors import ConfigError
            raise ConfigError(
                message=f"llama.cpp server binary not found: '{binary}'. Install llama.cpp or set LLAMA_CPP_SERVER_BINARY.",
                code="config_error",
                provider="llama_cpp",
            )

        source_args: List[str] = []
        if self.config.llama_cpp.model_path:
            source_args = ["-m", self.config.llama_cpp.model_path]
        elif self.config.llama_cpp.hf_model:
            source_args = ["-hf", self.config.llama_cpp.hf_model]
        else:
            from .errors import ConfigError
            raise ConfigError(
                message="llama.cpp auto-start requires LLAMA_CPP_MODEL_PATH or LLAMA_CPP_HF_MODEL to be set.",
                code="config_error",
                provider="llama_cpp",
            )

        parsed = urlparse(self.config.llama_cpp.host)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8081

        cmd = [
            resolved_binary,
            *source_args,
            "--host",
            host,
            "--port",
            str(port),
            "-c",
            str(self.config.ollama.num_ctx),
        ]
        if self.config.llama_cpp.jinja:
            cmd.append("--jinja")
        if self.config.llama_cpp.chat_template:
            cmd.extend(["--chat-template", self.config.llama_cpp.chat_template])
        if self.config.llama_cpp.chat_template_file:
            cmd.extend(["--chat-template-file", self.config.llama_cpp.chat_template_file])
        cmd.extend(self.config.llama_cpp.extra_args)
        log_event(
            logger,
            logging.INFO,
            "llama_server_starting",
            host=self.config.llama_cpp.host,
            command=cmd,
            model_source=self._desired_model_source(),
        )

        self._server_process = subprocess.Popen(
            cmd,
            cwd=str(Path(resolved_binary).parent if "/" in resolved_binary else Path.cwd()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._running_model_source = self._desired_model_source()
        self._wait_until_ready()

    def ensure_ready(self):
        with self._lifecycle_slot():
            log_event(
                logger,
                logging.INFO,
                "llama_backend_ensure_ready",
                host=self.config.llama_cpp.host,
                desired_model_source=self._desired_model_source(),
                auto_start=self.config.llama_cpp.auto_start,
            )
            desired = self._desired_model_source()
            if self._server_process and self._server_process.poll() is None and desired and self._running_model_source != desired:
                self._stop_server()
            if self._ping():
                if self._loaded_model_matches_desired():
                    return
                if self._server_process and self._server_process.poll() is None:
                    self._stop_server()
                elif self.config.llama_cpp.auto_start:
                    self._stop_conflicting_server()
                else:
                    raise BackendNotReady(
                        message=(
                            "llama.cpp server is reachable but loaded with a different model. "
                            "Restart the server or free the port so the requested model can start."
                        ),
                        code="backend_not_ready",
                        provider="llama_cpp",
                        recoverable=False,
                    )
            if not self.config.llama_cpp.auto_start:
                raise BackendNotReady(
                    message=(
                        "llama.cpp backend selected but server is unreachable. "
                        "Start llama-server manually or set LLAMA_CPP_AUTO_START=true."
                    ),
                    code="backend_not_ready",
                    provider="llama_cpp",
                    recoverable=True,
                )
            if self._server_process and self._server_process.poll() is None:
                self._wait_until_ready()
                return
            self._start_server()

    def _stream_sse(
        self,
        payload: Dict[str, Any],
    ) -> Generator[LLMChunk, None, None]:
        """
        Server-Sent Events streaming üçün. Tool calling olmadıqda işlədilir.
        llama-server /v1/chat/completions SSE protokolunu dəstəkləyir.
        """
        url = urljoin(self._base_url(), "/v1/chat/completions")
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.llama_cpp.api_key}",
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urlopen(req, timeout=self.config.llama_cpp.request_timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    if not body:
                        continue
                    try:
                        chunk_data = json.loads(body)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk_data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content") or ""
                    if content:
                        yield LLMChunk(content=content)
        except HTTPError as exc:
            body_text = ""
            try:
                body_text = exc.read().decode("utf-8", errors="replace").strip()[:300]
            except Exception:
                pass
            raise RuntimeError(
                f"llama.cpp SSE error HTTP {exc.code}: {exc.reason}"
                + (f" | {body_text}" if body_text else "")
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"llama.cpp SSE connection error: {exc.reason}") from exc

    def _request_no_stream(
        self,
        payload: Dict[str, Any],
    ) -> LLMChunk:
        """Tool calling üçün stream=False path — tam cavabı bir dəfə alır."""
        response = self._request_json(
            "POST",
            "/v1/chat/completions",
            payload,
            timeout=self.config.llama_cpp.request_timeout,
        )
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message", {})
        return LLMChunk(
            content=message.get("content") or "",
            tool_calls=self._parse_tool_calls(message.get("tool_calls")),
        )

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Generator[LLMChunk, None, None]:
        with self._request_slot():
            use_streaming = not bool(tools)
            log_event(
                logger,
                logging.INFO,
                "backend_request_started",
                provider="llama_cpp",
                mode="sse" if use_streaming else "batch",
                model=self.config.ollama.model,
                host=self.config.llama_cpp.host,
                message_count=len(messages),
                tool_schema_count=len(tools or []),
            )
            self.ensure_ready()

            base_payload: Dict[str, Any] = {
                "model": self.config.ollama.model,
                "messages": self._normalize_messages(messages),
                "temperature": self.config.ollama.temperature,
                "max_tokens": self.config.llama_cpp.max_tokens,
            }

            if use_streaming:
                # Tool yoxdur — real SSE streaming
                payload = {**base_payload, "stream": True}
                accumulated = ""
                for chunk in self._stream_sse(payload):
                    accumulated += chunk.content
                    yield chunk
                log_event(
                    logger,
                    logging.INFO,
                    "backend_request_completed",
                    provider="llama_cpp",
                    mode="sse",
                    model=self.config.ollama.model,
                    host=self.config.llama_cpp.host,
                    response_preview=accumulated[:200],
                )
            else:
                # Tool var — stream=False (OpenAI spec tələbi)
                payload = {
                    **base_payload,
                    "stream": False,
                    "tools": tools,
                    "tool_choice": "auto",
                    "parallel_tool_calls": False,
                }
                chunk = self._request_no_stream(payload)
                log_event(
                    logger,
                    logging.INFO,
                    "backend_request_completed",
                    provider="llama_cpp",
                    mode="batch",
                    model=self.config.ollama.model,
                    host=self.config.llama_cpp.host,
                    response_preview=(chunk.content or "")[:200],
                )
                yield chunk

    def chat_once(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        chunks = list(self.chat_stream(messages, tools=tools))
        return "".join(chunk.content for chunk in chunks)

    def list_models(self) -> List[str]:
        local = self._local_model_names()
        try:
            self.ensure_ready()
            response = self._request_json("GET", "/v1/models")
            names = [self._canonical_model_name(item.get("id")) for item in response.get("data", []) if item.get("id")]
            merged = []
            for name in names + local:
                if name and name not in merged:
                    merged.append(name)
            return merged or ([self.config.ollama.model] if self.config.ollama.model else [])
        except Exception:
            fallback = []
            for name in local + ([self.config.ollama.model] if self.config.ollama.model else []):
                if name and name not in fallback:
                    fallback.append(name)
            return fallback

    def capabilities(self) -> BackendCapabilities:
        notes = [
            "In this architecture, a single llama.cpp host is treated as a single active-model server.",
            "Multi-agent missions are supported, but worker requests are queued per host to prevent model-switch races and HTTP 500 errors.",
            "Mixed per-agent model missions are normalized to one shared model for safety.",
        ]
        if self.config.llama_cpp.auto_start:
            notes.append("Auto-start is enabled, so ApexForge Swarm can launch llama-server when the host is local and free.")
        else:
            notes.append("Auto-start is disabled; llama-server must already be running or startup will fail.")
        return BackendCapabilities(
            provider="llama_cpp",
            multi_agent_supported=True,
            request_parallelism="serialized",
            mixed_model_missions="normalized_to_single_model",
            auto_start_supported=True,
            local_model_discovery=True,
            notes=notes,
        )


class OpenAICompatBackend(BaseLLMBackend):
    """
    OpenAI Python SDK üzərindən işləyən universal backend.
    Dəstəklənənlər: OpenAI, Groq, Together.ai, Mistral, Anthropic (compat),
                    LM Studio, vllm, Jan.ai, və istənilən OpenAI-uyğun server.

    Konfiqurasiya (env və ya config.yaml openai_compat:):
        OPENAI_COMPAT_API_KEY   — API açarı
        OPENAI_COMPAT_BASE_URL  — boş = rəsmi OpenAI; digər URL = digər provider
        OPENAI_COMPAT_MODEL     — model adı (məs. gpt-4o-mini, llama-3.3-70b-versatile)
        OPENAI_COMPAT_MAX_TOKENS
        OPENAI_COMPAT_REQUEST_TIMEOUT
    """

    def _client(self):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai paketi tapılmadı: pip install openai"
            ) from exc

        cfg = self.config.openai_compat
        kwargs: Dict[str, Any] = {
            "api_key": cfg.api_key or "sk-placeholder",
            "timeout": cfg.request_timeout,
            "max_retries": 1,
        }
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url

        from openai import OpenAI
        return OpenAI(**kwargs)

    def _active_model(self) -> str:
        return (
            self.config.openai_compat.model
            or self.config.ollama.model
            or "gpt-4o-mini"
        )

    def _parse_openai_tool_calls(self, tool_calls_raw: Any) -> List[LLMToolCall]:
        result: List[LLMToolCall] = []
        for tc in tool_calls_raw or []:
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            raw_args = getattr(fn, "arguments", None) or "{}"
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                arguments = raw_args
            result.append(
                LLMToolCall(
                    id=getattr(tc, "id", None),
                    function=LLMToolCallFunction(
                        name=getattr(fn, "name", "") or "",
                        arguments=arguments,
                    ),
                )
            )
        return result

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Generator[LLMChunk, None, None]:
        use_streaming = not bool(tools)
        log_event(
            logger,
            logging.INFO,
            "backend_request_started",
            provider="openai_compat",
            mode="stream" if use_streaming else "batch",
            model=self._active_model(),
            base_url=self.config.openai_compat.base_url or "openai-official",
            message_count=len(messages),
            tool_schema_count=len(tools or []),
        )

        client = self._client()
        kwargs: Dict[str, Any] = {
            "model": self._active_model(),
            "messages": messages,
            "temperature": self.config.ollama.temperature,
            "max_tokens": self.config.openai_compat.max_tokens,
        }

        if use_streaming:
            kwargs["stream"] = True
            accumulated = ""
            try:
                stream = client.chat.completions.create(**kwargs)
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    content = getattr(delta, "content", None) or ""
                    if content:
                        accumulated += content
                        yield LLMChunk(content=content)
            except Exception as exc:
                raise BackendStreamError(
                    message=str(exc),
                    code="backend_stream_error",
                    provider="openai_compat",
                ) from exc
            log_event(
                logger,
                logging.INFO,
                "backend_request_completed",
                provider="openai_compat",
                mode="stream",
                model=self._active_model(),
                response_preview=accumulated[:200],
            )
        else:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
            try:
                resp = client.chat.completions.create(**kwargs)
            except Exception as exc:
                raise BackendHTTPError(
                    message=str(exc),
                    code="backend_http_error",
                    provider="openai_compat",
                ) from exc
            msg = resp.choices[0].message if resp.choices else None
            content = getattr(msg, "content", None) or ""
            tool_calls = self._parse_openai_tool_calls(getattr(msg, "tool_calls", None))
            log_event(
                logger,
                logging.INFO,
                "backend_request_completed",
                provider="openai_compat",
                mode="batch",
                model=self._active_model(),
                response_preview=content[:200],
            )
            yield LLMChunk(content=content, tool_calls=tool_calls)

    def chat_once(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        chunks = list(self.chat_stream(messages, tools=tools))
        return "".join(c.content for c in chunks)

    def list_models(self) -> List[str]:
        try:
            client = self._client()
            models = [m.id for m in client.models.list().data]
            return sorted(models) or [self._active_model()]
        except Exception:
            return [self._active_model()]

    def capabilities(self) -> BackendCapabilities:
        base = self.config.openai_compat.base_url or ""
        provider_hint = (
            "groq" if "groq.com" in base
            else "together" if "together" in base
            else "mistral" if "mistral" in base
            else "lm-studio" if "1234" in base
            else "openai" if not base
            else "custom"
        )
        notes = [
            f"Active endpoint: {base or 'https://api.openai.com/v1 (official)'}",
            f"Detected provider hint: {provider_hint}",
            "Streaming is enabled for text-only turns; tool calls use batch mode.",
            "Mixed per-agent models are fully supported — each agent can use a different model.",
        ]
        return BackendCapabilities(
            provider="openai_compat",
            multi_agent_supported=True,
            request_parallelism="parallel",
            mixed_model_missions="supported",
            auto_start_supported=False,
            local_model_discovery=False,
            notes=notes,
        )


def detect_available_backends(config) -> List[Dict[str, Any]]:
    """
    Mövcud backendləri yoxlayır, hər birinin statusunu qaytarır.
    Startup zamanı istifadəçiyə nəyin işlədiyini göstərmək üçün.
    """
    results: List[Dict[str, Any]] = []

    # Ollama
    try:
        import ollama as _ollama
        models = _ollama.Client(host=config.ollama.host).list().models
        model_names = [m.model for m in models] if models else []
        results.append({
            "provider": "ollama",
            "status": "available",
            "host": config.ollama.host,
            "models": model_names,
            "model_count": len(model_names),
        })
    except ImportError:
        results.append({
            "provider": "ollama",
            "status": "package_missing",
            "note": "pip install ollama",
        })
    except Exception as exc:
        results.append({
            "provider": "ollama",
            "status": "unreachable",
            "host": config.ollama.host,
            "error": str(exc),
        })

    # llama.cpp
    try:
        req = Request(
            config.llama_cpp.host.rstrip("/") + "/v1/models",
            headers={"Authorization": f"Bearer {config.llama_cpp.api_key}"},
        )
        with urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        model_ids = [item.get("id", "") for item in data.get("data", [])]
        results.append({
            "provider": "llama_cpp",
            "status": "available",
            "host": config.llama_cpp.host,
            "models": model_ids,
            "model_count": len(model_ids),
        })
    except Exception as exc:
        results.append({
            "provider": "llama_cpp",
            "status": "unreachable" if config.llama_cpp.host else "not_configured",
            "host": config.llama_cpp.host,
            "error": str(exc),
        })

    # OpenAI compat
    api_key = config.openai_compat.api_key
    if api_key:
        try:
            from openai import OpenAI
            kwargs: Dict[str, Any] = {"api_key": api_key, "timeout": 5, "max_retries": 0}
            if config.openai_compat.base_url:
                kwargs["base_url"] = config.openai_compat.base_url
            client = OpenAI(**kwargs)
            models = [m.id for m in client.models.list().data]
            results.append({
                "provider": "openai_compat",
                "status": "available",
                "base_url": config.openai_compat.base_url or "https://api.openai.com/v1",
                "models": models[:10],
                "model_count": len(models),
            })
        except ImportError:
            results.append({
                "provider": "openai_compat",
                "status": "package_missing",
                "note": "pip install openai",
            })
        except Exception as exc:
            results.append({
                "provider": "openai_compat",
                "status": "error",
                "base_url": config.openai_compat.base_url or "https://api.openai.com/v1",
                "error": str(exc),
            })
    else:
        results.append({
            "provider": "openai_compat",
            "status": "not_configured",
            "note": "Set OPENAI_COMPAT_API_KEY to enable",
        })

    return results


def create_llm_backend(config) -> BaseLLMBackend:
    provider = (getattr(config.agent, "provider", "ollama") or "ollama").lower()
    _registry: Dict[str, type] = {
        "llama_cpp": LlamaCppBackend,
        "openai_compat": OpenAICompatBackend,
        "ollama": OllamaBackend,
    }
    backend_cls = _registry.get(provider)
    if backend_cls is None:
        log_event(
            logger,
            logging.WARNING,
            "backend_unknown_provider",
            provider=provider,
            fallback="ollama",
        )
        backend_cls = OllamaBackend
    return backend_cls(config)


def get_backend_capabilities(config) -> BackendCapabilities:
    return create_llm_backend(config).capabilities()
