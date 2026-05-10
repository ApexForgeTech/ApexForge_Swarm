from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ApexError(Exception):
    message: str
    code: str
    provider: Optional[str] = None
    recoverable: bool = True

    def __str__(self) -> str:
        parts = [f"[{self.code}]", self.message]
        if self.provider:
            parts.insert(1, f"({self.provider})")
        return " ".join(parts)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "provider": self.provider,
            "recoverable": self.recoverable,
        }


@dataclass
class BackendError(ApexError):
    recoverable: bool = True


@dataclass
class BackendNotReady(BackendError):
    code: str = "backend_not_ready"
    recoverable: bool = True


@dataclass
class BackendTimeout(BackendError):
    code: str = "backend_timeout"
    recoverable: bool = True


@dataclass
class BackendHTTPError(BackendError):
    code: str = "backend_http_error"
    status_code: int = 0
    recoverable: bool = True


@dataclass
class BackendStreamError(BackendError):
    code: str = "backend_stream_error"
    recoverable: bool = True


@dataclass
class ToolError(ApexError):
    code: str = "tool_error"
    tool_name: Optional[str] = None
    recoverable: bool = True


@dataclass
class ConfigError(ApexError):
    code: str = "config_error"
    recoverable: bool = False


@dataclass
class ModelNotFound(BackendError):
    code: str = "model_not_found"
    model: Optional[str] = None
    recoverable: bool = False
