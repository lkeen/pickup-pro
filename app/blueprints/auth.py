"""Authentication and the logged-in landing page."""

from flask import Blueprint, redirect, render_template, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db, limiter
from app.forms import ConfirmForm, LoginForm, RegisterForm
from app.models import User

bp = Blueprint("auth", __name__)


def _render_landing(login_form=None, register_form=None, error=None):
    return render_template(
        "index.html",
        login_form=login_form or LoginForm(),
        register_form=register_form or RegisterForm(),
        error=error,
    )


@bp.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    return _render_landing()


# Both limits apply: a burst limit stops rapid guessing, and an hourly limit
# stops a slow grind. Counted per client address.
@bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def login():
    form = LoginForm()
    if not form.validate_on_submit():
        return _render_landing(login_form=form, error="Username and password are required.")

    user = User.query.filter_by(username=form.username.data.strip()).first()
    if user and user.check_password(form.password.data):
        _start_authenticated_session(user)
        return redirect(url_for("auth.dashboard"))

    # Deliberately identical whether the username exists or the password is
    # wrong, so the response cannot be used to enumerate accounts.
    return _render_landing(login_form=form, error="Invalid credentials.")


@bp.route("/register", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def register():
    form = RegisterForm()
    if not form.validate_on_submit():
        return _render_landing(register_form=form, error=_first_error(form))

    username = form.username.data.strip()
    email = form.email.data.strip().lower()
    if User.query.filter_by(username=username).first():
        return _render_landing(register_form=form, error="User already registered.")
    if User.query.filter_by(email=email).first():
        return _render_landing(register_form=form, error="That email is already registered.")

    new_user = User(username=username, email=email)
    new_user.set_password(form.password.data)
    db.session.add(new_user)
    db.session.commit()
    _start_authenticated_session(new_user)
    return redirect(url_for("auth.dashboard"))


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html", username=current_user.username, logout_form=ConfirmForm()
    )


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    # POST, not GET: a GET logout can be fired by any third-party page embedding
    # <img src="/logout">.
    if not ConfirmForm().validate_on_submit():
        return redirect(url_for("auth.dashboard"))
    logout_user()
    return redirect(url_for("auth.home"))


def _start_authenticated_session(user):
    """Log the user in on a fresh session.

    Clearing first means the session identifier the user carried while
    anonymous is not the one that ends up authenticated, so an attacker who
    fixed a victim's session cookie beforehand does not inherit the login.
    """
    session.clear()
    login_user(user)


def _first_error(form):
    for field_errors in form.errors.values():
        if field_errors:
            return field_errors[0]
    return None
