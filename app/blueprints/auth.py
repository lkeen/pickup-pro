"""Password authentication and the logged-in landing page."""

from flask import Blueprint, redirect, render_template, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, limiter
from app.forms import ConfirmForm, LoginForm, RegisterForm
from app.models import User

bp = Blueprint("auth", __name__)

# Compared against when the username does not exist, so a failed login costs
# the same whether or not the account is real. Without it, response time tells
# an attacker which usernames are worth guessing passwords for.
_DUMMY_HASH = generate_password_hash("password-that-is-never-valid")


def _render_landing(login_form=None, register_form=None, error=None):
    return render_template(
        "index.html",
        login_form=login_form or LoginForm(),
        register_form=register_form or RegisterForm(),
        error=error,
    )


def _find_by_username(username):
    return db.session.scalar(db.select(User).filter_by(username=username))


@bp.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    return _render_landing()


# Both limits apply: the burst limit stops rapid guessing, the hourly limit
# stops a slow grind.
@bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def login():
    form = LoginForm()
    if not form.validate_on_submit():
        return _render_landing(login_form=form, error="Username and password are required.")

    user = _find_by_username(form.username.data.strip())
    if user is None:
        check_password_hash(_DUMMY_HASH, form.password.data)
    elif user.check_password(form.password.data):
        _start_authenticated_session(user)
        return redirect(url_for("auth.dashboard"))

    # Identical whether the username exists or the password is wrong, so the
    # response cannot be used to enumerate accounts.
    return _render_landing(login_form=form, error="Invalid credentials.")


@bp.route("/register", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def register():
    form = RegisterForm()
    if not form.validate_on_submit():
        return _render_landing(register_form=form, error=_first_error(form))

    username = form.username.data.strip()
    email = form.email.data.strip().lower()
    if _find_by_username(username):
        return _render_landing(register_form=form, error="User already registered.")
    if db.session.scalar(db.select(User).filter_by(email=email)):
        return _render_landing(register_form=form, error="That email is already registered.")

    new_user = User(username=username, email=email)
    new_user.set_password(form.password.data)
    db.session.add(new_user)
    try:
        db.session.commit()
    except IntegrityError:
        # Two registrations for the same name can both pass the checks above
        # and race to the insert. The unique constraints settle it; the loser
        # gets the same message it would have got a moment earlier.
        db.session.rollback()
        return _render_landing(register_form=form, error="Those details are already registered.")

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
    # POST, not GET: a GET logout can be fired by any page embedding
    # <img src="/logout">.
    if not ConfirmForm().validate_on_submit():
        return redirect(url_for("auth.dashboard"))
    logout_user()
    return redirect(url_for("auth.home"))


def _start_authenticated_session(user):
    """Log the user in on a fresh session.

    Clearing first means the identifier the user carried while anonymous is not
    the one that ends up authenticated, so an attacker who fixed a victim's
    cookie beforehand does not inherit the login. Marking it permanent is what
    makes PERMANENT_SESSION_LIFETIME apply at all -- a non-permanent session
    cookie has no expiry and lives as long as the browser does.
    """
    session.clear()
    session.permanent = True
    login_user(user)


def _first_error(form):
    for field_errors in form.errors.values():
        if field_errors:
            return field_errors[0]
    return None
