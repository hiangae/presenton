import asyncio
import uuid

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.requests import Request
from starlette.responses import Response

from api import middlewares
from api.middlewares import SessionAuthMiddleware
from api.v1.auth import oidc as oidc_module
from api.v1.auth import principal as principal_module
from api.v1.auth.oidc import OidcClaims, resolve_oidc_user, verify_oidc_token
from api.v1.auth.principal import AuthPrincipal, resolve_request_principal
from models.sql.oidc_identity import OidcIdentity
from models.sql.user import User


ISSUER = "https://idp.example.com"
JWKS_URI = "https://idp.example.com/.well-known/jwks.json"


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_pem


@pytest.fixture
def oidc_env(monkeypatch):
    monkeypatch.setattr(oidc_module, "get_oidc_issuer_env", lambda: ISSUER)
    monkeypatch.setattr(oidc_module, "get_oidc_jwks_uri_env", lambda: JWKS_URI)
    monkeypatch.setattr(oidc_module, "get_oidc_audience_env", lambda: "")
    monkeypatch.setattr(oidc_module, "get_oidc_username_claim_env", lambda: "preferred_username")
    monkeypatch.setattr(oidc_module, "get_oidc_admin_claim_env", lambda: "")
    monkeypatch.setattr(oidc_module, "get_oidc_admin_value_env", lambda: "")
    monkeypatch.setattr(oidc_module, "is_oidc_user_provisioning_enabled", lambda: True)
    return monkeypatch


def _install_fake_jwks(private_key):
    import base64

    kid = "test-key"
    numbers = private_key.public_key().public_numbers()

    def b64(value):
        return (
            base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8))
            .rstrip(b"=")
            .decode()
        )

    jwk = {
        "kty": "RSA",
        "alg": "RS256",
        "kid": kid,
        "n": b64(numbers.n),
        "e": b64(numbers.e),
    }
    signing_key = pyjwt.PyJWK(jwk, algorithm="RS256")
    oidc_module._JWKS_CLIENTS.clear()

    class FakeJwksClient:
        def get_signing_key_from_jwt(self, token):
            return signing_key

    oidc_module._JWKS_CLIENTS[(ISSUER, JWKS_URI)] = FakeJwksClient()
    return kid


def _make_token(private_key, **claims):
    kid = _install_fake_jwks(private_key)
    payload = {"iss": ISSUER, "sub": "user-123", "kid": kid, **claims}
    return pyjwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})


def test_verify_oidc_token_returns_claims(oidc_env, rsa_keypair):
    private_key, _ = rsa_keypair
    token = _make_token(
        private_key, preferred_username="alice", email="alice@example.com"
    )
    claims = verify_oidc_token(token)
    assert claims is not None
    assert claims.subject == "user-123"
    assert claims.username == "alice"
    assert claims.is_admin is False


def test_verify_oidc_token_rejects_wrong_issuer(oidc_env, rsa_keypair):
    private_key, _ = rsa_keypair
    kid = _install_fake_jwks(private_key)
    token = pyjwt.encode(
        {"iss": "https://evil.example.com", "sub": "user-123", "kid": kid},
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )
    assert verify_oidc_token(token) is None


def test_verify_oidc_token_rejects_missing_subject(oidc_env, rsa_keypair):
    private_key, _ = rsa_keypair
    kid = _install_fake_jwks(private_key)
    token = pyjwt.encode(
        {"iss": ISSUER, "preferred_username": "alice", "kid": kid},
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )
    assert verify_oidc_token(token) is None


def test_verify_oidc_token_admin_claim(oidc_env, rsa_keypair):
    private_key, _ = rsa_keypair
    oidc_env.setattr(oidc_module, "get_oidc_admin_claim_env", lambda: "roles")
    oidc_env.setattr(oidc_module, "get_oidc_admin_value_env", lambda: "admin")
    token = _make_token(private_key, roles="admin")
    claims = verify_oidc_token(token)
    assert claims is not None
    assert claims.is_admin is True


def test_verify_oidc_token_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.setattr(oidc_module, "get_oidc_issuer_env", lambda: "")
    monkeypatch.setattr(oidc_module, "get_oidc_jwks_uri_env", lambda: "")
    assert verify_oidc_token("anything") is None


class FakeSession:
    def __init__(self, identities=None, users=None, account_count=0):
        self._identities = identities or {}
        self._users = users or {}
        self._account_count = account_count
        self.added = []
        self.commit_count = 0

    async def scalar(self, query):
        if "count" in str(query):
            return self._account_count
        return self._identities.get((ISSUER, "user-123"))

    async def get(self, model, key):
        if model is User:
            return self._users.get(key)
        return None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commit_count += 1

    def refresh(self, obj):
        if isinstance(obj, User):
            obj.id = obj.id or uuid.uuid4()


def test_resolve_oidc_user_provisions_first_user_as_admin(oidc_env):
    session = FakeSession(account_count=0)
    claims = OidcClaims(subject="user-123", username="alice", is_admin=False)
    user, is_admin = asyncio.run(resolve_oidc_user(session, claims))
    assert user is not None
    assert user.username == "alice"
    assert user.is_superuser is True  # first user bootstraps admin
    assert is_admin is True
    assert any(isinstance(a, OidcIdentity) for a in session.added)


def test_resolve_oidc_user_maps_existing_identity(oidc_env):
    user_id = uuid.uuid4()
    existing_user = User(
        id=user_id,
        username="alice",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        auth_version=1,
    )
    identity = OidcIdentity(
        issuer=ISSUER, subject="user-123", user_id=user_id, username="alice"
    )
    session = FakeSession(
        identities={(ISSUER, "user-123"): identity}, users={user_id: existing_user}
    )
    claims = OidcClaims(subject="user-123", username="alice", is_admin=False)
    user, is_admin = asyncio.run(resolve_oidc_user(session, claims))
    assert user is existing_user
    assert is_admin is False
    assert session.added == []


def test_resolve_oidc_user_denies_when_provisioning_disabled(oidc_env):
    oidc_env.setattr(oidc_module, "is_oidc_user_provisioning_enabled", lambda: False)
    session = FakeSession(account_count=0)
    claims = OidcClaims(subject="user-123", username="alice", is_admin=False)
    user, is_admin = asyncio.run(resolve_oidc_user(session, claims))
    assert user is None
    assert is_admin is False


def _request(path, bearer_token):
    headers = [(b"authorization", f"Bearer {bearer_token}".encode())]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 5001),
        }
    )


def test_resolve_request_principal_uses_oidc_for_non_api_key(monkeypatch):
    monkeypatch.setattr(principal_module, "is_oidc_enabled", lambda: True)

    async def no_api_key(session, token):
        return None

    monkeypatch.setattr(principal_module, "verify_api_key", no_api_key)
    monkeypatch.setattr(
        principal_module,
        "verify_oidc_token",
        lambda token: OidcClaims("user-123", "alice", False),
    )
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        username="alice",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        auth_version=1,
    )

    async def fake_resolve(session, claims):
        return user, False

    monkeypatch.setattr(principal_module, "resolve_oidc_user", fake_resolve)

    class Session:
        async def get(self, model, key):
            return None

    principal, resolved = asyncio.run(
        resolve_request_principal(
            _request("/api/v1/ppt/template/init", "oidc-token"), Session()
        )
    )
    assert principal is not None
    assert principal.method == "oidc"
    assert principal.user_id == user_id
    assert resolved is user


def test_resolve_request_principal_api_key_takes_precedence(monkeypatch):
    monkeypatch.setattr(principal_module, "is_oidc_enabled", lambda: True)

    async def fake_verify_api_key(session, token):
        from services.api_keys import VerifiedApiKey

        user = User(
            id=uuid.uuid4(),
            username="keyuser",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            auth_version=1,
        )
        return VerifiedApiKey(api_key_id="abc", user=user)

    monkeypatch.setattr(principal_module, "verify_api_key", fake_verify_api_key)

    class Session:
        async def get(self, model, key):
            return None

    principal, _ = asyncio.run(
        resolve_request_principal(
            _request("/api/v1/ppt/template/init", "sk-presenton-abc.def"), Session()
        )
    )
    assert principal is not None
    assert principal.method == "api_key"


def test_middleware_allows_oidc_admin_on_admin_route(monkeypatch):
    class Session:
        async def scalar(self, _query):
            return 1

    class SessionContext:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, *_args):
            return None

    user_id = uuid.uuid4()

    async def resolve_principal(_request, _session):
        return (
            AuthPrincipal(
                user_id=user_id, username="admin", is_admin=True, method="oidc"
            ),
            object(),
        )

    async def call_next(request):
        assert request.state.auth_principal.method == "oidc"
        return Response("admin route reached", status_code=200)

    async def no_cloud_proxy(*_args, **_kwargs):
        return None

    class FakeStrategy:
        async def write_token(self, _user):
            return "internal-jwt"

    monkeypatch.setattr(middlewares, "is_disable_auth_enabled", lambda: False)
    monkeypatch.setattr(middlewares, "is_oidc_enabled", lambda: True)
    monkeypatch.setattr(middlewares, "async_session_maker", SessionContext)
    monkeypatch.setattr(middlewares, "resolve_request_principal", resolve_principal)
    monkeypatch.setattr(middlewares, "maybe_proxy_presenton_cloud_request", no_cloud_proxy)
    monkeypatch.setattr(middlewares, "get_jwt_strategy", lambda: FakeStrategy())

    request = _request("/api/v1/admin/provider-settings", "oidc-token")
    response = asyncio.run(SessionAuthMiddleware(app=None).dispatch(request, call_next))
    assert response.status_code == 200
    assert response.body == b"admin route reached"


def test_middleware_oidc_status_is_public():
    middleware = SessionAuthMiddleware(app=None)
    assert "/api/v1/auth/oidc/status" in middleware._PUBLIC_AUTH_PATHS
