"""Application factory.

Routes live in ``app.blueprints``; this module only wires the app together.
"""

from dotenv import load_dotenv
from flask import Flask

# Environment must be loaded before config is imported: config reads os.getenv
# at class-definition time.
load_dotenv()

from app.extensions import cache, csrf, db, limiter, login_mgr, migrate, oauth  # noqa: E402
from config import get_config  # noqa: E402


def create_app(config_name=None):
    app = Flask(__name__)

    # Resolve and validate configuration before anything else touches it, so a
    # missing DATABASE_URL or a placeholder SECRET_KEY fails at boot rather than
    # on the first request that happens to need it.
    config_class = get_config(config_name)
    config_class.validate()
    app.config.from_object(config_class)

    register_extensions(app)
    register_blueprints(app)

    return app


def register_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    login_mgr.init_app(app)
    # Protects every POST/PUT/PATCH/DELETE app-wide, not only routes that
    # happen to remember to validate a form.
    csrf.init_app(app)
    cache.init_app(app)
    limiter.init_app(app)
    oauth.init_app(app)

    from app.blueprints.oauth import register_google

    # Absent Google credentials is a normal state for a fresh clone: the
    # sign-in button simply does not render.
    app.config["GOOGLE_OAUTH_READY"] = register_google(app)

    # Imported for the side effect of registering the models with SQLAlchemy's
    # metadata, which is what Alembic autogenerate reads.
    from app.models import User

    @login_mgr.user_loader
    def load_user(user_id: str):
        # Flask-Login passes a string; convert to int for PK lookup
        return db.session.get(User, int(user_id))

    # Where @login_required sends anonymous users.
    login_mgr.login_view = "auth.home"
    # "strong" ties the session to a hash of the client's IP and user agent
    # and drops it when they change, so a lifted cookie is less portable.
    login_mgr.session_protection = "strong"


def register_blueprints(app):
    from app.blueprints import register_blueprints as _register

    _register(app)
