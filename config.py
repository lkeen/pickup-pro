"""Application configuration.

One class per environment, selected at runtime by ``create_app``. Anything that
differs between a laptop, a test run and production belongs here rather than
being read from ``os.getenv`` at the point of use.
"""

import os
from datetime import timedelta

# Secrets that ship in example files and tutorials. If one of these ever reaches
# production it means the real key was never set, so treat it as unset.
PLACEHOLDER_SECRETS = frozenset(
    {
        "",
        "changeme",
        "dev-secret-key",
        "secret",
        "your-secret-key-here",
    }
)


class ConfigError(RuntimeError):
    """Raised when the environment is not fit to boot the app."""


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Recycle connections that the database closed underneath us; without this a
    # container restart surfaces as a 500 on the next request.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # --- Session cookie ---
    # A distinctive name keeps this app's cookie from colliding with another
    # Flask app on the same host during local development.
    SESSION_COOKIE_NAME = "pickup_session"
    # Not readable from JavaScript, so an XSS bug cannot lift the session.
    SESSION_COOKIE_HTTPONLY = True
    # Not sent on cross-site POSTs. Defence in depth behind the CSRF tokens:
    # Flask's default is None, which browsers treat as Lax anyway, but relying
    # on a browser default is not a decision.
    SESSION_COOKIE_SAMESITE = "Lax"
    # Overridden to True in production. Left False here so the cookie works over
    # plain HTTP on localhost.
    SESSION_COOKIE_SECURE = False
    # Flask's default is 31 days. A stolen cookie stays valid for that whole
    # window, which is far longer than this app needs.
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False
    REMEMBER_COOKIE_DURATION = timedelta(days=14)

    # --- Rate limiting ---
    # Redis-backed in a later branch; in-memory is per-process and therefore
    # wrong behind multiple workers, which is why this is explicit rather than
    # left to default.
    RATELIMIT_STORAGE_URI = "memory://"
    RATELIMIT_HEADERS_ENABLED = True

    # Wall-clock times (a game's start) are interpreted and displayed in this
    # zone. Everything is stored in UTC. Per-court timezones would be the fully
    # correct model; one configured zone is the honest simplification for an app
    # serving a single metro area.
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "UTC")

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

    @classmethod
    def validate(cls):
        """Fail fast on an unusable environment. Overridden where it matters."""
        if not cls.SQLALCHEMY_DATABASE_URI:
            raise ConfigError("DATABASE_URL is not set.")


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = False
    # Off by default so tests exercise application logic rather than token
    # plumbing. The CSRF regression tests turn it back on explicitly.
    WTF_CSRF_ENABLED = False
    # Left enabled so Flask-Limiter still builds its storage backend; the test
    # fixtures then switch the limiter off at runtime, because rate limits would
    # otherwise make the rest of the suite order-dependent and flaky.
    RATELIMIT_ENABLED = True
    # Tests run against a real PostgreSQL database, not SQLite: the spatial
    # queries this project is built around have no SQLite equivalent.
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL") or (
        f"{os.getenv('DATABASE_URL', '')}_test" if os.getenv("DATABASE_URL") else None
    )


class ProductionConfig(BaseConfig):
    DEBUG = False
    # HTTPS-only cookies. Without this the session cookie is sent over plain
    # HTTP and can be read off the wire.
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"

    @classmethod
    def validate(cls):
        super().validate()
        if not cls.SECRET_KEY or cls.SECRET_KEY.lower() in PLACEHOLDER_SECRETS:
            raise ConfigError(
                "SECRET_KEY is unset or still a placeholder. Session cookies are "
                "signed with it, so a known value lets anyone forge a login. "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
            )


_CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}

DEFAULT_CONFIG = "development"


def get_config(name=None):
    """Resolve a config class by name, falling back to the environment."""
    name = (name or os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or DEFAULT_CONFIG).lower()
    try:
        return _CONFIGS[name]
    except KeyError:
        raise ConfigError(
            f"Unknown config {name!r}. Expected one of: {', '.join(sorted(_CONFIGS))}."
        ) from None
