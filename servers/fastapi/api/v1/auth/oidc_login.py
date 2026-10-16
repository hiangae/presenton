"""Browser OIDC login via the Authorization Code flow with PKCE.

This is the interactive counterpart to ``oidc.py`` (bearer-token auth). The
login page links to ``GET /api/v1/auth/oidc/login``, which redirects the user
to the identity provider's authorization endpoint. After the user signs in,
the IdP redirects back to ``GET /api/v1/auth/oidc/callback`` with an
authorization code; we exchange it for tokens, verify the access token against
the issuer's JWKS, resolve/provision the local user, and set the same session
cookie used by username/password login.

PKCE (S256) is always used so public clients work without a secret; when
``OIDC_CLIENT_SECRET`` is configured it is sent as well for confidential
clients.
"""

import base64
import hashlib
import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, RedirectResponse

from api.v1.auth.config import SESSION_COOKIE_NAME, SESSION_TTL_SECONDS
from api.v1.auth.oidc import OidcClaims, resolve_oidc_user, verify_oidc_token
from api.v1.auth.users import get_jwt_strategy
from services.database import get_async_session
from utils.get_env import (
    get_oidc_client_id_env,
    get_oidc_client_secret_env,
    get_oidc_issuer_env,
    get_oidc_redirect_uri_env,
    get_oidc_scopes_env,
    get_session_cookie_secure_override,
    is_oidc_login_enabled,
)

logger = logging.getLogger(__name__)

# Mounted under API_V1_AUTH_ROUTER (prefix /api/v1/auth), so the effective
# paths are /api/v1/auth/oidc/login and /api/v1/auth/oidc/callback.
OIDC_LOGIN_ROUTER = APIRouter(prefix="/oidc", tags=["Auth"])

# Short-lived state cookie that binds the callback to this browser tab.
_STATE_COOKIE = "presenton_oidc_state"
_STATE_TTL_SECONDS = 10 * 60


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _pkce_pair() -> tuple[str, str]:
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("utf-8")).digest())
    return verifier, challenge


def _secure_request(request: Request) -> bool:
    override = get_session_cookie_secure_override()
    if override is not None:
        return override
    return (
        request.headers.get("x-forwarded-proto", "").lower() == "https"
        or request.url.scheme == "https"
    )


def _redirect_uri(request: Request) -> str:
    explicit = get_oidc_redirect_uri_env()
    if explicit:
        return explicit
    # Same-origin deployment: derive from the incoming request origin.
    return f"{request.url.scheme}://{request.url.netloc}/api/v1/auth/oidc/callback"


def _discovery_url(issuer: str) -> str:
    return f"{issuer}/.well-known/openid-configuration"


async def _fetch_discovery(issuer: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0), follow_redirects=True
        ) as client:
            response = await client.get(_discovery_url(issuer))
    except httpx.HTTPError as exc:
        # Unreachable issuer (bad URL, DNS failure, firewall) must surface as a
        # readable error instead of an unhandled 500.
        logger.warning("OIDC discovery request failed", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the identity provider",
        ) from exc
    if not response.is_success:
        raise HTTPException(
            status_code=502,
            detail="Could not load the identity provider configuration",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="The identity provider returned an invalid configuration",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Invalid identity provider configuration")
    return payload


@OIDC_LOGIN_ROUTER.get("/login")
async def oidc_login_start(request: Request):
    """Redirect the browser to the identity provider's authorization page."""
    if not is_oidc_login_enabled():
        raise HTTPException(status_code=404, detail="OIDC login is not enabled")

    issuer = get_oidc_issuer_env()
    discovery = await _fetch_discovery(issuer)
    authorize_endpoint = discovery.get("authorization_endpoint")
    if not isinstance(authorize_endpoint, str) or not authorize_endpoint:
        raise HTTPException(
            status_code=502,
            detail="The identity provider did not expose an authorization endpoint",
        )

    redirect_uri = _redirect_uri(request)
    state = secrets.token_urlsafe(24)
    code_verifier, code_challenge = _pkce_pair()

    params = {
        "response_type": "code",
        "client_id": get_oidc_client_id_env(),
        "redirect_uri": redirect_uri,
        "scope": get_oidc_scopes_env(),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{authorize_endpoint}?{urlencode(params)}"

    response = RedirectResponse(authorize_url, status_code=302)
    response.set_cookie(
        _STATE_COOKIE,
        state,
        max_age=_STATE_TTL_SECONDS,
        httponly=True,
        secure=_secure_request(request),
        samesite="lax",
        path="/",
    )
    # Store the PKCE verifier alongside the state so the callback can complete
    # the token exchange. It is bound to this browser via the state cookie.
    response.set_cookie(
        "presenton_oidc_pkce",
        code_verifier,
        max_age=_STATE_TTL_SECONDS,
        httponly=True,
        secure=_secure_request(request),
        samesite="lax",
        path="/",
    )
    return response


@OIDC_LOGIN_ROUTER.get("/callback")
async def oidc_login_callback(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    """Exchange the authorization code for tokens and establish a session."""
    if not is_oidc_login_enabled():
        raise HTTPException(status_code=404, detail="OIDC login is not enabled")

    error = request.query_params.get("error")
    if error:
        description = request.query_params.get("error_description", error)
        raise HTTPException(status_code=401, detail=f"Identity provider sign-in failed: {description}")

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    expected_state = request.cookies.get(_STATE_COOKIE)
    code_verifier = request.cookies.get("presenton_oidc_pkce")

    if not code or not state or not expected_state or state != expected_state:
        logger.warning(
            "OIDC callback rejected: state mismatch (code=%s state=%s cookie_state=%s)",
            bool(code), bool(state), bool(expected_state),
        )
        raise HTTPException(status_code=400, detail="Invalid or expired sign-in attempt")
    if not code_verifier:
        logger.warning("OIDC callback rejected: missing PKCE verifier cookie")
        raise HTTPException(status_code=400, detail="Missing sign-in verification data")

    issuer = get_oidc_issuer_env()
    discovery = await _fetch_discovery(issuer)
    token_endpoint = discovery.get("token_endpoint")
    if not isinstance(token_endpoint, str) or not token_endpoint:
        raise HTTPException(
            status_code=502,
            detail="The identity provider did not expose a token endpoint",
        )

    token_data: dict[str, Any] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(request),
        "client_id": get_oidc_client_id_env(),
        "code_verifier": code_verifier,
    }
    client_secret = get_oidc_client_secret_env()
    if client_secret:
        token_data["client_secret"] = client_secret

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=False) as client:
            token_response = await client.post(
                token_endpoint,
                data=token_data,
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the identity provider",
        ) from exc

    try:
        token_payload = token_response.json()
    except ValueError:
        token_payload = {}
    if not token_response.is_success or not isinstance(token_payload, dict):
        detail = token_payload.get("error_description") or token_payload.get("error") or "Token exchange failed"
        logger.warning(
            "OIDC token exchange failed: status=%s body=%s",
            token_response.status_code,
            str(token_payload)[:500],
        )
        raise HTTPException(
            status_code=401 if token_response.status_code < 500 else 502,
            detail=str(detail),
        )

    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(status_code=502, detail="The identity provider did not return an access token")

    claims = verify_oidc_token(access_token)
    if claims is None:
        logger.warning("OIDC access token failed JWKS verification")
        raise HTTPException(status_code=401, detail="The identity provider token could not be verified")

    user, _is_admin = await resolve_oidc_user(session, claims)
    if user is None:
        logger.warning(
            "OIDC login denied: no local user mapped (subject=%r username=%r)",
            claims.subject, claims.username,
        )
        raise HTTPException(
            status_code=403,
            detail="This account is not allowed to sign in. Contact your administrator.",
        )

    token = await get_jwt_strategy().write_token(user)
    # The browser navigated here directly, so hand off to the app root once the
    # session cookie is set; AuthGate then confirms the session and proceeds.
    # Keep the redirect on the same origin the callback was served from so the
    # session cookie is always sent back to the app.
    app_origin = f"{request.url.scheme}://{request.url.netloc}"
    logger.info(
        "OIDC login succeeded for user=%r (origin=%s, secure_cookie=%s)",
        user.username, app_origin, _secure_request(request),
    )
    response = RedirectResponse(f"{app_origin}/", status_code=302)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=_secure_request(request),
        samesite="lax",
        path="/",
    )
    response.delete_cookie(_STATE_COOKIE, httponly=True, secure=_secure_request(request), samesite="lax", path="/")
    response.delete_cookie("presenton_oidc_pkce", httponly=True, secure=_secure_request(request), samesite="lax", path="/")
    return response
