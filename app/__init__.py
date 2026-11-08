"""Application factory. Routes live in ``app.blueprints``."""

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app.extensions import cache, csrf, db, limiter, login_mgr, migrate, oauth
from config import get_config


def create_app(config_name=None):
    app = Flask(__name__)

    # Resolved and validated before anything else touches it, so a missing
    # DATABASE_URL or a placeholder SECRET_KEY fails at boot rather than on the
    # first request that happens to need it.
    config_class = get_config(config_name)
    config_class.validate()
    app.config.from_object(config_class)

    from app.logging import configure as configure_logging

    configure_logging(app)
    trust_proxy_headers(app)
    register_extensions(app)
    register_template_helpers(app)
    register_blueprints(app)
    register_health_check(app)
    register_security_headers(app)
    register_error_handlers(app)

    return app


def trust_proxy_headers(app):
    """Read the client's real address and scheme from X-Forwarded-* headers.

    Only as many hops as are configured are trusted; the rest of each header is
    discarded. Without this the app sees the proxy's address for every request,
    which keys the whole internet into one rate-limit bucket and makes
    ``url_for(_external=True)`` build http:// URLs behind a TLS terminator --
    the OAuth redirect URI among them.
    """
    hops = app.config.get("TRUSTED_PROXY_HOPS", 0)
    if hops > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops, x_prefix=hops
        )


def register_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    login_mgr.init_app(app)
    csrf.init_app(app)
    cache.init_app(app)
    limiter.init_app(app)
    oauth.init_app(app)

    from app.blueprints.oauth import register_google

    app.config["GOOGLE_OAUTH_READY"] = register_google(app)

    # Imported for the side effect of registering the models with SQLAlchemy's
    # metadata, which is what Alembic autogenerate reads.
    from app.models import User

    @login_mgr.user_loader
    def load_user(user_id: str):
        try:
            return db.session.get(User, int(user_id))
        except ValueError:
            return None

    login_mgr.login_view = "auth.home"
    # Ties the session to a hash of the client's address and user agent, so a
    # lifted cookie is less portable.
    login_mgr.session_protection = "strong"


def register_template_helpers(app):
    from flask_wtf.csrf import generate_csrf
    from markupsafe import Markup

    @app.template_global()
    def csrf_field():
        """A CSRF input for templates with no form object of their own."""
        return Markup(
            f'<input type="hidden" name="csrf_token" value="{generate_csrf()}">'
        )

    from app.timeutils import to_local

    @app.template_filter("localtime")
    def localtime(value, fmt="%a %d %b, %H:%M"):
        """Render a stored UTC instant as wall-clock in APP_TIMEZONE."""
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
    """Liveness for the container runtime and the load balancer.

    Checks the database, not just that Python is running: a process that cannot
    reach its database should not be sent traffic.
    """
    from sqlalchemy import text

    @app.route("/healthz")
    @limiter.exempt
    def healthz():
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            app.logger.exception("health check failed")
            return {"status": "unhealthy"}, 503
        return {"status": "ok"}


# Tiles come from OpenStreetMap; everything else is served from this origin.
# No 'unsafe-inline' anywhere, which is only possible because no template
# carries an inline script, style attribute or event handler.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: https://*.tile.openstreetmap.org; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # The map asks for the visitor's location; nothing else needs a device.
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def register_security_headers(app):
    hsts_seconds = app.config.get("HSTS_SECONDS")

    @app.after_request
    def _set_security_headers(response):
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if hsts_seconds:
            response.headers.setdefault(
                "Strict-Transport-Security", f"max-age={hsts_seconds}; includeSubDomains"
            )
        return response


def register_error_handlers(app):
    """Serve the app's own error pages, and JSON under /api.

    Werkzeug's default pages leak the server identity and look nothing like the
    app; a JSON client receiving an HTML error body cannot parse the reason.
    """
    from flask import jsonify, render_template, request
    from werkzeug.exceptions import HTTPException

    def wants_json():
        return request.path.startswith("/api/") or request.accept_mimetypes.best == (
            "application/json"
        )

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if wants_json():
            return jsonify({"error": error.description, "status": error.code}), error.code
        return (
            render_template("error.html", code=error.code, message=error.description),
            error.code,
        )

    @app.errorhandler(Exception)
    def _unexpected_error(error):
        app.logger.exception("unhandled exception", exc_info=error)
        db.session.rollback()
        message = "Something went wrong on our end."
        if wants_json():
            return jsonify({"error": message, "status": 500}), 500
        return render_template("error.html", code=500, message=message), 500
