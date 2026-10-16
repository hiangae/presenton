# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- OIDC bearer-token authentication for the FastAPI backend. When `OIDC_ENABLED`
  is set, an `Authorization: Bearer <token>` header that is not a Presenton API
  key is verified against the configured issuer's JWKS and mapped to a local
  user — no separate API key issuance required.
  - New `api/v1/auth/oidc.py`: JWKS-based token verification (`verify_oidc_token`)
    and identity-to-user resolution with optional auto-provisioning
    (`resolve_oidc_user`). Verification is fail-closed (signature, issuer,
    audience, and JWKS fetch failures all reject the request).
  - New `models/sql/oidc_identity.py` (`oidc_identities` table): maps an external
    `(issuer, subject)` pair to a local `user_id`.
  - New alembic migration `a1b2c3d4e5f6_add_oidc_identities.py`.
  - Public `GET /api/v1/auth/oidc/status` endpoint reporting whether OIDC login
    is enabled.
  - New environment variables: `OIDC_ENABLED`, `OIDC_ISSUER`, `OIDC_AUDIENCE`,
    `OIDC_JWKS_URI`, `OIDC_USERNAME_CLAIM`, `OIDC_ADMIN_CLAIM`,
    `OIDC_ADMIN_VALUE`, `OIDC_USER_PROVISIONING` (documented in `docker-compose.yml`).
  - Unit tests in `tests/unit/test_oidc_auth.py` covering token verification,
    claim extraction, user provisioning, principal resolution, API-key
    precedence, and middleware admin-route handling.

### Changed
- `AuthPrincipal.method` now supports `"oidc"` alongside `"jwt"` and `"api_key"`.
- Admin-only routes accept verified OIDC principals (in addition to browser JWT
  sessions); API keys remain rejected from those routes.
- Internal session tokens are issued for OIDC principals so downstream cloud
  proxying works the same as for browser sessions.
- With OIDC enabled, an empty database no longer returns `428 setup required`;
  the first verified OIDC login provisions the bootstrap administrator.
