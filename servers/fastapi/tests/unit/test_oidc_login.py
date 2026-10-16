import asyncio
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from starlette.requests import Request

from api.v1.auth import oidc_login as login_module
from api.v1.auth.oidc import OidcClaims
from models.sql.user import User

ISSUER = "https://idp.example.com"
AUTHORIZE_ENDPOINT = f"{ISSUER}/authorize"
TOKEN_ENDPOINT = f"{ISSUER}/token"


@pytest.fixture
def login_env(monkeypatch):
    monkeypatch.setattr(login_module, "is_oidc_login_enabled", lambda: True)
    monkeypatch.setattr(login_module, "get_oidc_issuer_env", lambda: ISSUER)
    monkeypatch.setattr(login_module, "get_oidc_client_id_env", lambda: "client-1")
    monkeypatch.setattr(login_module, "get_oidc_client_secret_env", lambda: "")
    monkeypatch.setattr(login_module, "get_oidc_redirect_uri_env", lambda: "")
    monkeypatch.setattr(login_module, "get_oidc_scopes_env", lambda: "openid profile email")
    return monkeypatch


def _request(path, query=b"", cookies=None):
    headers = [(b"host", b"localhost:5001")]
    if cookies:
        joined = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers.append((b"cookie", joined.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "query_string": query,
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 5001),
        }
    )


def test_is_oidc_login_requires_client_id(monkeypatch):
    import utils.get_env as env

    monkeypatch.setattr(env, "is_oidc_enabled", lambda: True)
    monkeypatch.setattr(env, "get_oidc_client_id_env", lambda: "")
    assert login_module.is_oidc_login_enabled() is False


def test_login_redirects_to_authorize_with_pkce(login_env):
    async def fake_discovery(issuer):
        return {
            "authorization_endpoint": AUTHORIZE_ENDPOINT,
            "token_endpoint": TOKEN_ENDPOINT,
        }

    login_env.setattr(login_module, "_fetch_discovery", fake_discovery)

    response = asyncio.run(login_module.oidc_login_start(_request("/api/v1/auth/oidc/login")))
    assert response.status_code == 302

    location = response.headers["location"]
    parsed = urlparse(location)
    assert parsed.scheme == "https"
    assert parsed.path == "/authorize"
    params = parse_qs(parsed.query)
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["client-1"]
    assert params["redirect_uri"] == ["http://localhost:5001/api/v1/auth/oidc/callback"]
    assert params["scope"] == ["openid profile email"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"]
    assert params["state"]

    # The state and PKCE verifier are stored in httponly cookies.
    set_cookie = response.headers.getlist("set-cookie")
    assert any("presenton_oidc_state=" in c for c in set_cookie)
    assert any("presenton_oidc_pkce=" in c for c in set_cookie)


def test_login_disabled_returns_404(monkeypatch):
    monkeypatch.setattr(login_module, "is_oidc_login_enabled", lambda: False)
    with pytest.raises(Exception) as excinfo:
        asyncio.run(login_module.oidc_login_start(_request("/api/v1/auth/oidc/login")))
    assert excinfo.value.status_code == 404


def test_callback_rejects_state_mismatch(login_env):
    request = _request(
        "/api/v1/auth/oidc/callback",
        query=b"code=abc&state=attacker",
        cookies={"presenton_oidc_state": "expected", "presenton_oidc_pkce": "verifier"},
    )
    with pytest.raises(Exception) as excinfo:
        asyncio.run(login_module.oidc_login_callback(request, session=None))
    assert excinfo.value.status_code == 400


def test_callback_exchanges_code_and_sets_session(login_env):
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        username="alice",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        auth_version=1,
    )

    async def fake_discovery(issuer):
        return {"token_endpoint": TOKEN_ENDPOINT}

    class FakeResponse:
        status_code = 200
        is_success = True

        def json(self):
            return {"access_token": "oidc-access-token"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, data=None, headers=None):
            assert url == TOKEN_ENDPOINT
            assert data["grant_type"] == "authorization_code"
            assert data["code"] == "good-code"
            assert data["code_verifier"] == "verifier"
            assert "client_secret" not in data
            return FakeResponse()

    login_env.setattr(login_module, "_fetch_discovery", fake_discovery)
    login_env.setattr(httpx, "AsyncClient", FakeClient)
    login_env.setattr(
        login_module, "verify_oidc_token",
        lambda token: OidcClaims(subject="user-123", username="alice", is_admin=False),
    )

    async def fake_resolve(session, claims):
        return user, False

    login_env.setattr(login_module, "resolve_oidc_user", fake_resolve)

    class FakeStrategy:
        async def write_token(self, _user):
            return "session-jwt"

    login_env.setattr(login_module, "get_jwt_strategy", lambda: FakeStrategy())

    request = _request(
        "/api/v1/auth/oidc/callback",
        query=b"code=good-code&state=expected",
        cookies={"presenton_oidc_state": "expected", "presenton_oidc_pkce": "verifier"},
    )
    response = asyncio.run(login_module.oidc_login_callback(request, session=None))
    assert response.status_code == 302
    # Redirects to the app root on the same origin as the callback request.
    assert response.headers["location"] == "http://localhost:5001/"
    set_cookie = response.headers.getlist("set-cookie")
    assert any("presenton_session=session-jwt" in c for c in set_cookie)


def test_callback_denies_unmapped_identity(login_env):
    async def fake_discovery(issuer):
        return {"token_endpoint": TOKEN_ENDPOINT}

    class FakeResponse:
        status_code = 200
        is_success = True

        def json(self):
            return {"access_token": "oidc-access-token"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, data=None, headers=None):
            return FakeResponse()

    login_env.setattr(login_module, "_fetch_discovery", fake_discovery)
    login_env.setattr(httpx, "AsyncClient", FakeClient)
    login_env.setattr(
        login_module, "verify_oidc_token",
        lambda token: OidcClaims(subject="user-123", username="alice", is_admin=False),
    )

    async def fake_resolve(session, claims):
        return None, False

    login_env.setattr(login_module, "resolve_oidc_user", fake_resolve)

    request = _request(
        "/api/v1/auth/oidc/callback",
        query=b"code=good-code&state=expected",
        cookies={"presenton_oidc_state": "expected", "presenton_oidc_pkce": "verifier"},
    )
    with pytest.raises(Exception) as excinfo:
        asyncio.run(login_module.oidc_login_callback(request, session=None))
    assert excinfo.value.status_code == 403


def test_session_cookie_secure_override(monkeypatch):
    request = _request("/api/v1/auth/oidc/login")

    monkeypatch.setattr(login_module, "get_session_cookie_secure_override", lambda: False)
    assert login_module._secure_request(request) is False

    monkeypatch.setattr(login_module, "get_session_cookie_secure_override", lambda: True)
    assert login_module._secure_request(request) is True

    monkeypatch.setattr(login_module, "get_session_cookie_secure_override", lambda: None)
    # Without an override, plain http requests are not secure.
    assert login_module._secure_request(request) is False


def test_public_paths_include_oidc_login():
    from api.middlewares import SessionAuthMiddleware

    middleware = SessionAuthMiddleware(app=None)
    assert "/api/v1/auth/oidc/login" in middleware._PUBLIC_AUTH_PATHS
    assert "/api/v1/auth/oidc/callback" in middleware._PUBLIC_AUTH_PATHS


def test_auth_router_registers_oidc_login_paths():
    """Regression: the login router must not duplicate the /api/v1/auth prefix."""
    from api.v1.auth.router import API_V1_AUTH_ROUTER

    paths = set()
    for route in API_V1_AUTH_ROUTER.routes:
        # Included routers are wrapped (_IncludedRouter); resolve their
        # effective paths from the include prefix + original router routes.
        if type(route).__name__ == "_IncludedRouter":
            prefix = getattr(route.include_context, "prefix", "") or ""
            for sub in route.original_router.routes:
                paths.add(prefix + getattr(sub, "path", ""))
        else:
            paths.add(getattr(route, "path", ""))
    assert "/api/v1/auth/oidc/login" in paths
    assert "/api/v1/auth/oidc/callback" in paths
