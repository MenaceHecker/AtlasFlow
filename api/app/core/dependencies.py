"""
Reusable FastAPI security dependency for admin endpoints.

Usage:
    from app.core.dependencies import require_admin_key

    @router.post("/some-admin-action", dependencies=[Depends(require_admin_key)])
    def my_action(): ...
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

_api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def require_admin_key(key: str | None = Security(_api_key_header)) -> None:
    """
    Validates the X-Admin-Key request header.

    - If ADMIN_API_KEY is not configured, returns 503 (admin disabled).
    - If the header is missing or wrong, returns 401.
    """
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints are disabled on this instance.",
        )
    if key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
