import hashlib
import os
import secrets

from fastapi import Header, HTTPException


def _configured_key() -> str:
    return os.getenv("APEXFORGE_API_KEY", "").strip()


def is_auth_enabled() -> bool:
    return bool(_configured_key())


def check_api_key(x_api_key: str = Header(default="")) -> None:
    """
    FastAPI Depends() üçün auth guard.
    APEXFORGE_API_KEY env boşdursa auth deaktivdir (local dev mode).
    Aktiv olduqda X-API-Key header yoxlanır.
    """
    key = _configured_key()
    if not key:
        return
    provided = x_api_key.strip()
    if not provided:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Set X-API-Key header.",
        )
    if not secrets.compare_digest(
        hashlib.sha256(provided.encode()).hexdigest(),
        hashlib.sha256(key.encode()).hexdigest(),
    ):
        raise HTTPException(status_code=403, detail="Invalid API key.")
