"""Application configuration.

One class per environment, selected at runtime by ``create_app``. Anything that
differs between a laptop, a test run and production belongs here rather than
being read from ``os.getenv`` at the point of use.
"""

import os

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
    # Tests run against a real PostgreSQL database, not SQLite: the spatial
    # queries this project is built around have no SQLite equivalent.
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL") or (
        f"{os.getenv('DATABASE_URL', '')}_test" if os.getenv("DATABASE_URL") else None
    )


class ProductionConfig(BaseConfig):
    DEBUG = False

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
