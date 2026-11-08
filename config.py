"""Per-environment configuration, selected at runtime by ``create_app``."""

import os
from datetime import timedelta

from dotenv import load_dotenv

# Loaded here rather than in the factory because the classes below read
# os.getenv at definition time, which happens on import.
load_dotenv()

PLACEHOLDER_SECRETS = frozenset(
    {
        "",
        "changeme",
        "dev-secret-key",
        "secret",
        "your-secret-key-here",
    }
)

DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _int_env(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


class ConfigError(RuntimeError):
    """Raised when the environment is not fit to boot the app."""


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        # Without pre-ping, a database restart surfaces as a 500 on the next
        # request that picks up a dead pooled connection.
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        # Sized per worker process: the ceiling is
        # (pool_size + max_overflow) x gunicorn workers, which has to stay under
        # the server's max_connections.
        "pool_size": _int_env("DB_POOL_SIZE", 5),
        "max_overflow": _int_env("DB_MAX_OVERFLOW", 5),
        "pool_timeout": 10,
    }

    SESSION_COOKIE_NAME = "pickup_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False
    REMEMBER_COOKIE_DURATION = timedelta(days=14)

    # The token is bound to the session, so its useful lifetime is the session's.
    # The one-hour default instead rejects a form left open over lunch.
    WTF_CSRF_TIME_LIMIT = None

    CACHE_TYPE = "RedisCache"
    CACHE_REDIS_URL = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
    CACHE_KEY_PREFIX = "pickup:"
    CACHE_DEFAULT_TIMEOUT = 120

    # Redis-backed, not in-memory: in-memory storage is per-process, so with
    # several workers the limiter only ever sees a fraction of the traffic.
    RATELIMIT_STORAGE_URI = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
    RATELIMIT_HEADERS_ENABLED = True
    # A ceiling for every route, so an expensive endpoint is never free. Routes
    # that need something tighter declare it themselves.
    RATELIMIT_DEFAULT = "300 per minute; 5000 per hour"

    # Number of reverse proxies in front of the app. Zero means the app is
    # exposed directly and client-supplied X-Forwarded-* headers are ignored.
    TRUSTED_PROXY_HOPS = _int_env("TRUSTED_PROXY_HOPS", 0)

    # Wall-clock times are interpreted and displayed in this zone; everything is
    # stored in UTC. One zone per deployment, which suits a single metro area.
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "UTC")

    REDIS_URL = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

    @classmethod
    def validate(cls):
        if not cls.SQLALCHEMY_DATABASE_URI:
            raise ConfigError("DATABASE_URL is not set.")


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = False
    # Off by default so tests exercise application logic rather than token
    # plumbing; the CSRF regression tests turn it back on explicitly.
    WTF_CSRF_ENABLED = False
    # Left enabled so Flask-Limiter still builds its storage backend. The
    # fixtures switch the limiter off at runtime instead, because shared limits
    # would make the suite order-dependent.
    RATELIMIT_ENABLED = True
    RATELIMIT_DEFAULT = None
    CACHE_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")
    RATELIMIT_STORAGE_URI = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")
    # A real PostgreSQL database: the spatial queries this app is built around
    # have no SQLite equivalent.
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL") or (
        f"{os.getenv('DATABASE_URL', '')}_test" if os.getenv("DATABASE_URL") else None
    )


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"
    HSTS_SECONDS = _int_env("HSTS_SECONDS", 31536000)
    TRUSTED_PROXY_HOPS = _int_env("TRUSTED_PROXY_HOPS", 1)

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
    name = (name or os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or DEFAULT_CONFIG).lower()
    try:
        return _CONFIGS[name]
    except KeyError:
        raise ConfigError(
            f"Unknown config {name!r}. Expected one of: {', '.join(sorted(_CONFIGS))}."
        ) from None
