import yaml
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, List, TypeVar
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
T = TypeVar("T")


def _parse_env(name: str, parser: Callable[[str], T], default: T) -> T:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return parser(raw)
    except (TypeError, ValueError):
        return default


def _parse_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass
class OllamaConfig:
    host: str = "http://localhost:11434"
    model: str = "qwen2.5-3b-instruct-q4_k_m.gguf"
    temperature: float = 0.2
    num_ctx: int = 16384


@dataclass
class AgentConfig:
    max_iterations: int = 12
    provider: str = "llama_cpp"
    skills_dir: str = "skills"
    memory_dir: str = "memory"
    system_prompt: str = "You are ApexForge Swarm."


@dataclass
class ShellConfig:
    enabled: bool = True
    timeout: int = 30


@dataclass
class CodeConfig:
    enabled: bool = True
    timeout: int = 30


@dataclass
class AutonomyConfig:
    enabled: bool = False


@dataclass
class OpenAICompatConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = "gpt-4o-mini"
    max_tokens: int = 4096
    request_timeout: int = 120


@dataclass
class RAGConfig:
    enabled: bool = True
    persist_dir: str = "rag_store"
    embed_model: str = "nomic-embed-text"
    embed_backend: str = "ollama"   # "ollama" | "openai_compat"
    embed_base_url: str = ""        # for openai_compat embed backend
    embed_api_key: str = ""         # for openai_compat embed backend
    chunk_size: int = 500
    chunk_overlap: int = 50
    top_k: int = 5


@dataclass
class PluginsConfig:
    enabled: bool = True
    plugins_dir: str = "plugins"


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class LlamaCppConfig:
    host: str = "http://127.0.0.1:8081"
    hosts: List[str] = field(default_factory=list)
    server_binary: str = "llama-server"
    model_path: str = ""
    hf_model: str = ""
    auto_start: bool = False
    jinja: bool = True
    chat_template: str = ""
    chat_template_file: str = ""
    startup_timeout: int = 60
    request_timeout: int = 600
    max_tokens: int = 2048
    api_key: str = "sk-no-key-required"
    extra_args: List[str] = field(default_factory=list)


@dataclass
class Config:
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    llama_cpp: LlamaCppConfig = field(default_factory=LlamaCppConfig)
    openai_compat: OpenAICompatConfig = field(default_factory=OpenAICompatConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    shell: ShellConfig = field(default_factory=ShellConfig)
    code: CodeConfig = field(default_factory=CodeConfig)
    autonomy: AutonomyConfig = field(default_factory=AutonomyConfig)
    web: WebConfig = field(default_factory=WebConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)

    @classmethod
    def load(cls, path: Path = ROOT / "config.yaml") -> "Config":
        cfg = cls()
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            if "ollama" in data:
                cfg.ollama = OllamaConfig(**data["ollama"])
            if "llama_cpp" in data:
                cfg.llama_cpp = LlamaCppConfig(**data["llama_cpp"])
            if "agent" in data:
                cfg.agent = AgentConfig(**data["agent"])
            if "shell" in data:
                cfg.shell = ShellConfig(**data["shell"])
            if "code" in data:
                cfg.code = CodeConfig(**data["code"])
            if "web" in data:
                cfg.web = WebConfig(**data["web"])
            if "autonomy" in data:
                cfg.autonomy = AutonomyConfig(**data["autonomy"])
            if "openai_compat" in data:
                cfg.openai_compat = OpenAICompatConfig(**data["openai_compat"])
            if "rag" in data:
                cfg.rag = RAGConfig(**data["rag"])
            if "plugins" in data:
                cfg.plugins = PluginsConfig(**data["plugins"])

        # env overrides
        if os.getenv("LLM_PROVIDER"):
            cfg.agent.provider = os.getenv("LLM_PROVIDER")
        if os.getenv("OLLAMA_HOST"):
            cfg.ollama.host = os.getenv("OLLAMA_HOST")
        if os.getenv("OLLAMA_MODEL"):
            cfg.ollama.model = os.getenv("OLLAMA_MODEL")
        cfg.ollama.temperature = _parse_env("OLLAMA_TEMPERATURE", float, cfg.ollama.temperature)
        cfg.ollama.num_ctx = _parse_env("OLLAMA_NUM_CTX", int, cfg.ollama.num_ctx)
        llama_cpp_num_ctx = os.getenv("LLAMA_CPP_NUM_CTX") or os.getenv("LLAMA_CPP_CTX_SIZE")
        if llama_cpp_num_ctx is not None:
            cfg.ollama.num_ctx = _parse_env("LLAMA_CPP_NUM_CTX", int, _parse_env("LLAMA_CPP_CTX_SIZE", int, cfg.ollama.num_ctx))
        if os.getenv("LLAMA_CPP_HOST"):
            cfg.llama_cpp.host = os.getenv("LLAMA_CPP_HOST")
        if os.getenv("LLAMA_CPP_HOSTS"):
            cfg.llama_cpp.hosts = [part.strip() for part in os.getenv("LLAMA_CPP_HOSTS").split(",") if part.strip()]
        if os.getenv("LLAMA_CPP_SERVER_BINARY"):
            cfg.llama_cpp.server_binary = os.getenv("LLAMA_CPP_SERVER_BINARY")
        if os.getenv("LLAMA_CPP_MODEL_PATH"):
            cfg.llama_cpp.model_path = os.getenv("LLAMA_CPP_MODEL_PATH")
        if os.getenv("LLAMA_CPP_HF_MODEL"):
            cfg.llama_cpp.hf_model = os.getenv("LLAMA_CPP_HF_MODEL")
        cfg.llama_cpp.auto_start = _parse_env_bool("LLAMA_CPP_AUTO_START", cfg.llama_cpp.auto_start)
        cfg.llama_cpp.jinja = _parse_env_bool("LLAMA_CPP_JINJA", cfg.llama_cpp.jinja)
        if os.getenv("LLAMA_CPP_CHAT_TEMPLATE"):
            cfg.llama_cpp.chat_template = os.getenv("LLAMA_CPP_CHAT_TEMPLATE")
        if os.getenv("LLAMA_CPP_CHAT_TEMPLATE_FILE"):
            cfg.llama_cpp.chat_template_file = os.getenv("LLAMA_CPP_CHAT_TEMPLATE_FILE")
        cfg.llama_cpp.startup_timeout = _parse_env("LLAMA_CPP_STARTUP_TIMEOUT", int, cfg.llama_cpp.startup_timeout)
        cfg.llama_cpp.request_timeout = _parse_env("LLAMA_CPP_REQUEST_TIMEOUT", int, cfg.llama_cpp.request_timeout)
        cfg.llama_cpp.max_tokens = _parse_env("LLAMA_CPP_MAX_TOKENS", int, cfg.llama_cpp.max_tokens)
        if os.getenv("LLAMA_CPP_API_KEY"):
            cfg.llama_cpp.api_key = os.getenv("LLAMA_CPP_API_KEY")
        if os.getenv("LLAMA_CPP_EXTRA_ARGS"):
            cfg.llama_cpp.extra_args = [part for part in os.getenv("LLAMA_CPP_EXTRA_ARGS").split() if part]
        if os.getenv("WEB_HOST"):
            cfg.web.host = os.getenv("WEB_HOST")
        cfg.web.port = _parse_env("WEB_PORT", int, cfg.web.port)
        # autonomy env override
        cfg.autonomy.enabled = _parse_env_bool("AUX_AUTONOMY_ENABLED", cfg.autonomy.enabled)

        # openai_compat env overrides
        if os.getenv("OPENAI_COMPAT_BASE_URL") is not None:
            cfg.openai_compat.base_url = os.getenv("OPENAI_COMPAT_BASE_URL")
        _key = os.getenv("OPENAI_COMPAT_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        if _key:
            cfg.openai_compat.api_key = _key
        if os.getenv("OPENAI_COMPAT_MODEL"):
            cfg.openai_compat.model = os.getenv("OPENAI_COMPAT_MODEL")
        cfg.openai_compat.max_tokens = _parse_env("OPENAI_COMPAT_MAX_TOKENS", int, cfg.openai_compat.max_tokens)
        cfg.openai_compat.request_timeout = _parse_env("OPENAI_COMPAT_REQUEST_TIMEOUT", int, cfg.openai_compat.request_timeout)

        # RAG env overrides
        cfg.rag.enabled = _parse_env_bool("RAG_ENABLED", cfg.rag.enabled)
        if os.getenv("RAG_PERSIST_DIR"):
            cfg.rag.persist_dir = os.getenv("RAG_PERSIST_DIR")
        if os.getenv("RAG_EMBED_MODEL"):
            cfg.rag.embed_model = os.getenv("RAG_EMBED_MODEL")
        if os.getenv("RAG_EMBED_BACKEND"):
            cfg.rag.embed_backend = os.getenv("RAG_EMBED_BACKEND")
        if os.getenv("RAG_EMBED_BASE_URL"):
            cfg.rag.embed_base_url = os.getenv("RAG_EMBED_BASE_URL")
        if os.getenv("RAG_EMBED_API_KEY"):
            cfg.rag.embed_api_key = os.getenv("RAG_EMBED_API_KEY")
        cfg.rag.chunk_size = _parse_env("RAG_CHUNK_SIZE", int, cfg.rag.chunk_size)
        cfg.rag.chunk_overlap = _parse_env("RAG_CHUNK_OVERLAP", int, cfg.rag.chunk_overlap)
        cfg.rag.top_k = _parse_env("RAG_TOP_K", int, cfg.rag.top_k)

        # plugins env overrides
        cfg.plugins.enabled = _parse_env_bool("PLUGINS_ENABLED", cfg.plugins.enabled)
        if os.getenv("PLUGINS_DIR"):
            cfg.plugins.plugins_dir = os.getenv("PLUGINS_DIR")

        return cfg

    def save(self, path: Path = ROOT / "config.yaml"):
        data = {
            "ollama": {
                "host": self.ollama.host,
                "model": self.ollama.model,
                "temperature": self.ollama.temperature,
                "num_ctx": self.ollama.num_ctx,
            },
            "llama_cpp": {
                "host": self.llama_cpp.host,
                "hosts": self.llama_cpp.hosts,
                "server_binary": self.llama_cpp.server_binary,
                "model_path": self.llama_cpp.model_path,
                "hf_model": self.llama_cpp.hf_model,
                "auto_start": self.llama_cpp.auto_start,
                "jinja": self.llama_cpp.jinja,
                "chat_template": self.llama_cpp.chat_template,
                "chat_template_file": self.llama_cpp.chat_template_file,
                "startup_timeout": self.llama_cpp.startup_timeout,
                "request_timeout": self.llama_cpp.request_timeout,
                "max_tokens": self.llama_cpp.max_tokens,
                "api_key": self.llama_cpp.api_key,
                "extra_args": self.llama_cpp.extra_args,
            },
            "agent": {
                "max_iterations": self.agent.max_iterations,
                "provider": self.agent.provider,
                "skills_dir": self.agent.skills_dir,
                "memory_dir": self.agent.memory_dir,
                "system_prompt": self.agent.system_prompt,
            },
            "shell": {"enabled": self.shell.enabled, "timeout": self.shell.timeout},
            "code": {"enabled": self.code.enabled, "timeout": self.code.timeout},
            "web": {"host": self.web.host, "port": self.web.port},
            "autonomy": {"enabled": self.autonomy.enabled},
            "openai_compat": {
                "base_url": self.openai_compat.base_url,
                "api_key": self.openai_compat.api_key,
                "model": self.openai_compat.model,
                "max_tokens": self.openai_compat.max_tokens,
                "request_timeout": self.openai_compat.request_timeout,
            },
            "rag": {
                "enabled": self.rag.enabled,
                "persist_dir": self.rag.persist_dir,
                "embed_model": self.rag.embed_model,
                "embed_backend": self.rag.embed_backend,
                "embed_base_url": self.rag.embed_base_url,
                "embed_api_key": self.rag.embed_api_key,
                "chunk_size": self.rag.chunk_size,
                "chunk_overlap": self.rag.chunk_overlap,
                "top_k": self.rag.top_k,
            },
            "plugins": {
                "enabled": self.plugins.enabled,
                "plugins_dir": self.plugins.plugins_dir,
            },
        }
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    @property
    def skills_path(self) -> Path:
        p = Path(self.agent.skills_dir)
        return p if p.is_absolute() else ROOT / p

    @property
    def memory_path(self) -> Path:
        p = Path(self.agent.memory_dir)
        return p if p.is_absolute() else ROOT / p
