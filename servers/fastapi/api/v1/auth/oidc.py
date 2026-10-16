"""Verify external OIDC bearer tokens and map them to local Presenton users.

This module is the OIDC counterpart to the cookie-JWT and API-key paths in
``principal.py``. When ``OIDC_ENABLED`` is set, an ``Authorization: Bearer`` token
that is not a Presenton API key is verified against the configured issuer's JWKS
and resolved to a local user (auto-provisioned when allowed).
"""

import logging
import secrets
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.sql.oidc_identity import OidcIdentity
from models.sql.user import User
from api.v1.auth.users import PASSWORD_HELPER
from utils.get_env import (
    get_oidc_admin_claim_env,
    get_oidc_admin_value_env,
    get_oidc_audience_env,
    get_oidc_issuer_env,
    get_oidc_jwks_uri_env,
    get_oidc_username_claim_env,
    is_oidc_user_provisioning_enabled,
)

logger = logging.getLogger(__name__)

# Cache one JWKS client per (issuer, jwks_uri) so the key set is fetched once
# and refreshed by PyJWT's built-in TTL rather than on every request.
_JWKS_CLIENTS: dict[tuple[str, str], PyJWKClient] = {}


@dataclass(frozen=True)
class OidcClaims:
    subject: str
    username: str | None
    is_admin: bool


def _jwks_client(issuer: str, jwks_uri: str) -> PyJWKClient:
    key = (issuer, jwks_uri)
    client = _JWKS_CLIENTS.get(key)
    if client is None:
        client = PyJWKClient(jwks_uri)
        _JWKS_CLIENTS[key] = client
    return client


def _claim_is_admin(claims: dict[str, Any]) -> bool:
    admin_claim = get_oidc_admin_claim_env()
    if not admin_claim:
        return False
    value = claims.get(admin_claim)
    expected = get_oidc_admin_value_env()
    if expected:
        return str(value) == expected
    return bool(value)


def verify_oidc_token(token: str) -> OidcClaims | None:
    """Verify an OIDC access token against the configured issuer's JWKS.

    Returns the extracted claims on success, or ``None`` when the token is not a
    valid token for the configured issuer/audience.
    """
    issuer = get_oidc_issuer_env()
    jwks_uri = get_oidc_jwks_uri_env()
    if not issuer or not jwks_uri:
        return None

    try:
        signing_key = _jwks_client(issuer, jwks_uri).get_signing_key_from_jwt(token)
        audience = get_oidc_audience_env() or None
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[signing_key.algorithm_name],
            audience=audience,
            issuer=issuer,
            options={"verify_aud": bool(audience)},
        )
    except jwt.PyJWTError:
        return None
    except Exception:
        # Network/JWKS fetch failures should fail closed, not crash the request.
        logger.warning("OIDC token verification failed", exc_info=True)
        return None

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        return None

    username_claim = get_oidc_username_claim_env()
    username = claims.get(username_claim)
    if not isinstance(username, str) or not username.strip():
        username = None

    return OidcClaims(
        subject=subject,
        username=username.strip() if username else None,
        is_admin=_claim_is_admin(claims),
    )


async def _provision_user(
    session: AsyncSession, username: str, is_admin: bool
) -> User:
    """Create a local user for a verified OIDC identity.

    The first provisioned user becomes the bootstrap administrator so an
    otherwise-empty deployment can be initialized through OIDC login.
    """
    account_count = int(
        await session.scalar(select(func.count()).select_from(User)) or 0
    )
    user = User(
        username=username,
        hashed_password=PASSWORD_HELPER.hash(secrets.token_urlsafe(32)),
        is_active=True,
        is_verified=True,
        is_superuser=is_admin or account_count == 0,
        auth_version=1,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def resolve_oidc_user(
    session: AsyncSession, claims: OidcClaims
) -> tuple[User | None, bool]:
    """Resolve a verified OIDC identity to a local user.

    Returns ``(user, is_admin)``. ``user`` is ``None`` when the identity is not
    mapped and provisioning is disabled. ``is_admin`` reflects the token's admin
    claim (or the user's superuser flag when no admin claim is configured).
    """
    issuer = get_oidc_issuer_env()
    identity = await session.scalar(
        select(OidcIdentity).where(
            OidcIdentity.issuer == issuer,
            OidcIdentity.subject == claims.subject,
        )
    )

    if identity is None:
        if not is_oidc_user_provisioning_enabled():
            return None, False
        username = claims.username or f"oidc-{claims.subject[:16]}"
        user = await _provision_user(session, username, claims.is_admin)
        identity = OidcIdentity(
            issuer=issuer,
            subject=claims.subject,
            user_id=user.id,
            username=username,
        )
        session.add(identity)
        await session.commit()
        await session.refresh(identity)
    else:
        user = await session.get(User, identity.user_id)
        if user is None or not user.is_active:
            return None, False

    is_admin = claims.is_admin or user.is_superuser
    return user, is_admin
