"""FastAPI dependencies for Supabase-authenticated endpoints."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .supabase import SupabaseAuthError, SupabaseUser, verify_supabase_token


security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
) -> SupabaseUser:
    """Return the authenticated Supabase user or raise HTTP 401."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")

    token = credentials.credentials
    try:
        user = verify_supabase_token(token)
    except SupabaseAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    return user


__all__ = ["get_current_user", "SupabaseUser"]
