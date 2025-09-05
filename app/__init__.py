# app/__init__.py
from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv
from sqlalchemy import text
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db, migrate, login_mgr
from config import DevelopmentConfig
from app.models import User  

def create_app():
    load_dotenv()

    app = Flask(__name__)
    app.config.from_object(DevelopmentConfig)

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_mgr.init_app(app)

    #Flask-Login wiring
    @login_mgr.user_loader
    def load_user(user_id: str):
        # Flask-Login passes a string; convert to int for PK lookup
        return User.query.get(int(user_id))

    login_mgr.login_view = "home"  # redirect here when @login_required fails

    #Routes
    @app.route("/")
    def home():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    @app.route("/login", methods=["POST"])
    def login():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("dashboard"))
        return render_template("index.html", error="Invalid credentials.")

    @app.route("/register", methods=["POST"])
    def register():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            return render_template("index.html", error="Username and password required.")
        if User.query.filter_by(username=username).first():
            return render_template("index.html", error="User already registered.")
        #add email field to the form later; using placeholder for now
        new_user = User(username=username, email=f"{username}@example.com")
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for("dashboard"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html", username=current_user.username)

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("home"))

    # Ensure models are imported so Alembic sees them
    from app import models

    return app
