# app/__init__.py
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import text
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db, migrate, login_mgr
from config import DevelopmentConfig
from app.models import User, Court, Game, GamePlayer  

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

    # Courts CRUD routes
    @app.route("/courts")
    @login_required
    def courts():
        courts = Court.query.all()
        return render_template("courts.html", courts=courts)

    @app.route("/courts/create", methods=["GET", "POST"])
    @login_required
    def create_court():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            address = request.form.get("address", "").strip()
            lat = request.form.get("lat")
            lng = request.form.get("lng")

            if not all([name, address, lat, lng]):
                flash("All fields are required.")
                return render_template("create_court.html")

            try:
                lat = float(lat)
                lng = float(lng)
            except ValueError:
                flash("Invalid coordinates.")
                return render_template("create_court.html")

            court = Court(
                name=name,
                address=address,
                lat=lat,
                lng=lng,
                created_by=current_user.id
            )
            db.session.add(court)
            db.session.commit()
            flash("Court created successfully!")
            return redirect(url_for("courts"))

        return render_template("create_court.html")

    # Games CRUD routes
    @app.route("/games")
    @login_required
    def games():
        court_id = request.args.get("court_id")
        date = request.args.get("date")

        query = Game.query
        if court_id:
            query = query.filter_by(court_id=court_id)
        if date:
            try:
                date_obj = datetime.strptime(date, "%Y-%m-%d").date()
                query = query.filter(Game.time >= date_obj)
                query = query.filter(Game.time < datetime.combine(date_obj, datetime.min.time()) + timedelta(days=1))
            except ValueError:
                pass

        games = query.order_by(Game.time).all()
        courts = Court.query.all()
        return render_template("games.html", games=games, courts=courts)

    @app.route("/games/create", methods=["GET", "POST"])
    @login_required
    def create_game():
        if request.method == "POST":
            court_id = request.form.get("court_id")
            time = request.form.get("time")
            max_players = request.form.get("max_players", 10)

            if not all([court_id, time]):
                flash("Court and time are required.")
                return render_template("create_game.html", courts=Court.query.all())

            try:
                time_obj = datetime.strptime(time, "%Y-%m-%dT%H:%M")
                max_players = int(max_players)
            except ValueError:
                flash("Invalid time or player count.")
                return render_template("create_game.html", courts=Court.query.all())

            game = Game(
                court_id=court_id,
                host_id=current_user.id,
                time=time_obj,
                max_players=max_players
            )
            db.session.add(game)
            db.session.commit()
            flash("Game created successfully!")
            return redirect(url_for("games"))

        courts = Court.query.all()
        return render_template("create_game.html", courts=courts)

    # Join/Leave game routes
    @app.route("/games/<int:game_id>/join", methods=["POST"])
    @login_required
    def join_game(game_id):
        game = Game.query.get_or_404(game_id)

        if not game.can_join(current_user):
            flash("Cannot join this game (full or already joined).")
            return redirect(url_for("games"))

        game_player = GamePlayer(game_id=game_id, user_id=current_user.id)
        db.session.add(game_player)
        db.session.commit()
        flash("Successfully joined the game!")
        return redirect(url_for("games"))

    @app.route("/games/<int:game_id>/leave", methods=["POST"])
    @login_required
    def leave_game(game_id):
        game = Game.query.get_or_404(game_id)

        game_player = GamePlayer.query.filter_by(
            game_id=game_id,
            user_id=current_user.id
        ).first()

        if not game_player:
            flash("You are not in this game.")
            return redirect(url_for("games"))

        db.session.delete(game_player)
        db.session.commit()
        flash("Successfully left the game!")
        return redirect(url_for("games"))

    # Ensure models are imported so Alembic sees them
    from app import models

    return app
