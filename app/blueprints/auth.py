"""Authentication and the logged-in landing page."""

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import User

bp = Blueprint("auth", __name__)


@bp.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    return render_template("index.html")


@bp.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        login_user(user)
        return redirect(url_for("auth.dashboard"))
    return render_template("index.html", error="Invalid credentials.")


@bp.route("/register", methods=["POST"])
def register():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not username or not password:
        return render_template("index.html", error="Username and password required.")
    if User.query.filter_by(username=username).first():
        return render_template("index.html", error="User already registered.")
    # add email field to the form later; using placeholder for now
    new_user = User(username=username, email=f"{username}@example.com")
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user)
    return redirect(url_for("auth.dashboard"))


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", username=current_user.username)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.home"))
