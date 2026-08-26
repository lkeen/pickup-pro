"""Google sign-in.

Additive: password login still works. An account is identified by the provider's
stable subject claim rather than by email address, because people change their
email and the subject is what actually identifies them.

Deliberately not implemented: linking a Google identity to an existing password
account. If the address already belongs to an account, sign-in is refused with
an explanation rather than guessed at. Linking correctly means handling
unverified-email hijacking and unlink-last-credential cases, which is a larger
piece of work than it looks.
"""

import re

from flask import Blueprint, abort, current_app, flash, redirect, session, url_for
from flask_login import login_user

from app.extensions import db, limiter, oauth
from app.models import User

bp = Blueprint("oauth", __name__, url_prefix="/auth")

PROVIDER = "google"
GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"

_USERNAME_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def register_google(app):
    """Register the Google client, if it has been configured.

    Absent credentials is a normal state -- a fresh clone has none -- so this
    stays quiet and the sign-in button simply does not render.
    """
    if not (app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET")):
        return False

    oauth.register(
        name=PROVIDER,
        client_id=app.config["GOOGLE_CLIENT_ID"],
        client_secret=app.config["GOOGLE_CLIENT_SECRET"],
        server_metadata_url=GOOGLE_METADATA_URL,
        client_kwargs={"scope": "openid email profile"},
    )
    return True


def google_is_configured():
    return bool(current_app.config.get("GOOGLE_CLIENT_ID"))


@bp.route("/google")
@limiter.limit("20 per hour")
def start():
    if not google_is_configured():
        abort(404)
    return oauth.google.authorize_redirect(url_for("oauth.callback", _external=True))


@bp.route("/callback")
def callback():
    if not google_is_configured():
        abort(404)

    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        current_app.logger.warning("Google OAuth token exchange failed", exc_info=True)
        flash("Google sign-in failed. Please try again.")
        return redirect(url_for("auth.home"))

    claims = token.get("userinfo") or {}
    user, error = resolve_oauth_user(PROVIDER, claims)
    if error:
        flash(error)
        return redirect(url_for("auth.home"))

    # Same fresh-session rule as password login: never carry a pre-login session
    # into an authenticated one.
    session.clear()
    login_user(user)
    return redirect(url_for("auth.dashboard"))


def resolve_oauth_user(provider, claims):
    """Map provider claims onto a User row.

    Returns (user, None) or (None, error_message). Kept separate from the route
    so it can be tested without standing up an OAuth server.
    """
    subject = claims.get("sub")
    email = (claims.get("email") or "").strip().lower()

    if not subject or not email:
        return None, "Google did not return enough information to sign you in."

    # Google sets this false for addresses it has not confirmed. Trusting an
    # unverified address would let someone claim an account by asserting an
    # email they do not control.
    if not claims.get("email_verified"):
        return None, "Your Google account's email address is not verified."

    existing = User.query.filter_by(oauth_provider=provider, oauth_sub=subject).first()
    if existing:
        return existing, None

    if User.query.filter_by(email=email).first():
        return None, (
            "An account already exists for that email address. "
            "Sign in with your password instead."
        )

    user = User(
        username=_unique_username_from(email),
        email=email,
        email_verified=True,
        oauth_provider=provider,
        oauth_sub=subject,
    )
    db.session.add(user)
    db.session.commit()
    return user, None


def _unique_username_from(email):
    """Derive a username from an email local part, and make it unique."""
    base = _USERNAME_SAFE.sub("", email.split("@", 1)[0])[:56] or "player"
    if not User.query.filter_by(username=base).first():
        return base
    # Cheap and predictable. At this scale a collision loop is fine; a UUID
    # suffix would be uglier for no practical gain.
    suffix = 2
    while User.query.filter_by(username=f"{base}{suffix}").first():
        suffix += 1
    return f"{base}{suffix}"
