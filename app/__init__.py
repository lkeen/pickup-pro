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
    register_template_helpers(app)
    register_blueprints(app)
    register_health_check(app)

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


def register_template_helpers(app):
    """Make a CSRF field available to any template.

    The nav renders a logout form on every page, so requiring each view to pass
    a form object down would be a rule everyone forgets exactly once.
    """
    from flask_wtf.csrf import generate_csrf
    from markupsafe import Markup

    @app.template_global()
    def csrf_field():
        return Markup(
            f'<input type="hidden" name="csrf_token" value="{generate_csrf()}">'
        )

    from app.timeutils import to_local

    @app.template_filter("localtime")
    def localtime(value, fmt="%a %d %b, %H:%M"):
        """Render a stored UTC instant as wall-clock in APP_TIMEZONE.

        Templates were calling .strftime() directly on the column, which printed
        UTC and called it local.
        """
        if value is None:
            return ""
        return to_local(value).strftime(fmt)

    @app.template_filter("localdate")
    def localdate(value, fmt="%Y-%m-%d"):
        return localtime(value, fmt)


def register_blueprints(app):
    from app.blueprints import register_blueprints as _register
    from app.cli import bp as cli_bp

    _register(app)
    app.register_blueprint(cli_bp)


def register_health_check(app):
    """A liveness endpoint for the container runtime and the load balancer.

    Checks the database rather than only that Python is running: a process that
    cannot reach its database should not be sent traffic.
    """
    from sqlalchemy import text

    @app.route("/healthz")
    def healthz():
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            app.logger.exception("health check failed")
            return {"status": "unhealthy"}, 503
        return {"status": "ok"}
