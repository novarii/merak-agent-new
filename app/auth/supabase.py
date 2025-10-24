"""Supabase JWT verification helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict

import jwt
from jwt import InvalidTokenError, PyJWKClient
from pydantic import BaseModel, Field

from app.core.settings import settings


class SupabaseAuthError(RuntimeError):
    """Raised when Supabase authentication fails."""


class SupabaseUser(BaseModel):
    """Authenticated Supabase user extracted from JWT claims."""

    id: str = Field(alias="user_id")
    email: str | None = None
    role: str | None = None
    claims: Dict[str, Any] = Field(default_factory=dict, repr=False)

    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }


def _require_configured(method: str) -> None:
    if not any(
        (
            settings.supabase_jwt_secret,
            settings.supabase_jwks_url,
        )
    ):
        raise SupabaseAuthError(
            f"{method} requires SUPABASE_JWT_SECRET or SUPABASE_JWKS_URL configuration."
        )


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    url = settings.supabase_jwks_url
    if not url:
        raise SupabaseAuthError("SUPABASE_JWKS_URL is not configured.")
    return PyJWKClient(url)


def _decode_with_shared_secret(token: str) -> dict[str, Any]:
    secret = settings.supabase_jwt_secret
    if not secret:
        raise SupabaseAuthError("SUPABASE_JWT_SECRET is not configured.")

    options = {"verify_aud": bool(settings.supabase_jwt_audience)}
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience=settings.supabase_jwt_audience,
        issuer=settings.supabase_jwt_issuer,
        options=options,
    )


def _decode_with_jwks(token: str) -> dict[str, Any]:
    client = _jwks_client()
    signing_key = client.get_signing_key_from_jwt(token)
    options = {"verify_aud": bool(settings.supabase_jwt_audience)}
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.supabase_jwt_audience,
        issuer=settings.supabase_jwt_issuer,
        options=options,
    )


def verify_supabase_token(token: str) -> SupabaseUser:
    """Validate the provided JWT and return the embedded Supabase user."""

    if not token:
        raise SupabaseAuthError("Missing Supabase access token.")

    _require_configured("verify_supabase_token")

    try:
        if settings.supabase_jwt_secret:
            claims = _decode_with_shared_secret(token)
        else:
            claims = _decode_with_jwks(token)
    except InvalidTokenError as exc:  # pragma: no cover - library exception path
        raise SupabaseAuthError("Supabase token verification failed.") from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise SupabaseAuthError("Unexpected Supabase verification error.") from exc

    user_id = claims.get("sub") or claims.get("user_id")
    if not user_id:
        raise SupabaseAuthError("Supabase token missing user identifier.")

    supabase_user = SupabaseUser.model_construct(
        user_id=str(user_id),
        email=claims.get("email"),
        role=claims.get("role") or claims.get("app_metadata", {}).get("role"),
        claims=claims,
    )
    return supabase_user


__all__ = ["SupabaseAuthError", "SupabaseUser", "verify_supabase_token"]
