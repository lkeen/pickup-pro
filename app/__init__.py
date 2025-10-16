# app/__init__.py
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import text
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db, migrate, login_mgr

# Load environment variables first
load_dotenv()

from config import DevelopmentConfig
from app.models import User, Court, Game, GamePlayer, PlayerStats, PlayerRating
from app.utils import haversine_distance

def create_app():
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

    # Nearby games search endpoint
    @app.route("/games/nearby")
    @login_required
    def nearby_games():
        lat = request.args.get("lat", type=float)
        lng = request.args.get("lng", type=float)
        radius = request.args.get("radius", default=10, type=float)  # default 10km
        date = request.args.get("date")

        if not lat or not lng:
            return jsonify({"error": "Latitude and longitude are required"}), 400

        # Get all upcoming games with their court info
        query = db.session.query(Game, Court).join(Court, Game.court_id == Court.id)

        # Filter by date if provided
        if date:
            try:
                date_obj = datetime.strptime(date, "%Y-%m-%d").date()
                query = query.filter(Game.time >= date_obj)
                query = query.filter(Game.time < datetime.combine(date_obj, datetime.min.time()) + timedelta(days=1))
            except ValueError:
                pass
        else:
            # Default: only show future games
            query = query.filter(Game.time >= datetime.now())

        games_with_courts = query.order_by(Game.time).all()

        # Calculate distance for each game and filter by radius
        nearby = []
        for game, court in games_with_courts:
            distance = haversine_distance(lat, lng, court.lat, court.lng)
            if distance <= radius:
                nearby.append({
                    "id": game.id,
                    "court_id": court.id,
                    "court_name": court.name,
                    "court_address": court.address,
                    "court_lat": court.lat,
                    "court_lng": court.lng,
                    "time": game.time.isoformat(),
                    "max_players": game.max_players,
                    "current_players": game.current_players,
                    "spots_available": game.spots_available,
                    "distance_km": round(distance, 2),
                    "host_id": game.host_id
                })

        # Sort by distance
        nearby.sort(key=lambda x: x["distance_km"])

        return jsonify({"games": nearby, "count": len(nearby)})

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

    # Game details with stats and ratings
    @app.route("/games/<int:game_id>")
    @login_required
    def game_detail(game_id):
        game = Game.query.get_or_404(game_id)
        is_rostered = current_user in game.players

        # Get current stats for this game
        player_stats = PlayerStats.query.filter_by(game_id=game_id).all()
        stats_dict = {stat.user_id: stat for stat in player_stats}

        # Get current ratings for this game (that current user has given)
        my_ratings = PlayerRating.query.filter_by(
            game_id=game_id,
            from_user_id=current_user.id
        ).all()
        ratings_dict = {rating.to_user_id: rating for rating in my_ratings}

        return render_template("game_detail.html",
                             game=game,
                             is_rostered=is_rostered,
                             stats_dict=stats_dict,
                             ratings_dict=ratings_dict)

    # Submit/update stats for a player in a game
    @app.route("/games/<int:game_id>/stats", methods=["POST"])
    @login_required
    def submit_stats(game_id):
        game = Game.query.get_or_404(game_id)

        # Only rostered players can submit stats
        if current_user not in game.players:
            flash("Only rostered players can submit stats.")
            return redirect(url_for("game_detail", game_id=game_id))

        user_id = request.form.get("user_id")
        points = request.form.get("points", 0)
        rebounds = request.form.get("rebounds", 0)
        assists = request.form.get("assists", 0)

        try:
            user_id = int(user_id)
            points = int(points) if points else 0
            rebounds = int(rebounds) if rebounds else 0
            assists = int(assists) if assists else 0
        except ValueError:
            flash("Invalid stats values.")
            return redirect(url_for("game_detail", game_id=game_id))

        # Check if stats already exist
        existing_stats = PlayerStats.query.filter_by(
            game_id=game_id,
            user_id=user_id
        ).first()

        if existing_stats:
            existing_stats.points = points
            existing_stats.rebounds = rebounds
            existing_stats.assists = assists
            existing_stats.updated_at = datetime.now()
        else:
            new_stats = PlayerStats(
                game_id=game_id,
                user_id=user_id,
                points=points,
                rebounds=rebounds,
                assists=assists
            )
            db.session.add(new_stats)

        db.session.commit()
        flash("Stats updated successfully!")
        return redirect(url_for("game_detail", game_id=game_id))

    # Submit/update rating for a player in a game
    @app.route("/games/<int:game_id>/rate", methods=["POST"])
    @login_required
    def submit_rating(game_id):
        game = Game.query.get_or_404(game_id)

        # Only rostered players can rate
        if current_user not in game.players:
            flash("Only rostered players can rate others.")
            return redirect(url_for("game_detail", game_id=game_id))

        to_user_id = request.form.get("to_user_id")
        rating = request.form.get("rating")
        comment = request.form.get("comment", "").strip()

        try:
            to_user_id = int(to_user_id)
            rating = int(rating)
        except ValueError:
            flash("Invalid rating values.")
            return redirect(url_for("game_detail", game_id=game_id))

        # Prevent self-rating
        if to_user_id == current_user.id:
            flash("You cannot rate yourself.")
            return redirect(url_for("game_detail", game_id=game_id))

        # Validate rating range
        if rating < 1 or rating > 5:
            flash("Rating must be between 1 and 5.")
            return redirect(url_for("game_detail", game_id=game_id))

        # Check if rating already exists
        existing_rating = PlayerRating.query.filter_by(
            game_id=game_id,
            from_user_id=current_user.id,
            to_user_id=to_user_id
        ).first()

        if existing_rating:
            existing_rating.rating = rating
            existing_rating.comment = comment
        else:
            new_rating = PlayerRating(
                game_id=game_id,
                from_user_id=current_user.id,
                to_user_id=to_user_id,
                rating=rating,
                comment=comment
            )
            db.session.add(new_rating)

        db.session.commit()
        flash("Rating submitted successfully!")
        return redirect(url_for("game_detail", game_id=game_id))

    # User profile with lifetime stats and ratings
    @app.route("/users/<int:user_id>")
    @login_required
    def user_profile(user_id):
        user = User.query.get_or_404(user_id)

        # Calculate lifetime stats aggregations
        stats_query = db.session.query(
            db.func.count(PlayerStats.id).label('games_played'),
            db.func.sum(PlayerStats.points).label('total_points'),
            db.func.sum(PlayerStats.rebounds).label('total_rebounds'),
            db.func.sum(PlayerStats.assists).label('total_assists'),
            db.func.avg(PlayerStats.points).label('avg_points'),
            db.func.avg(PlayerStats.rebounds).label('avg_rebounds'),
            db.func.avg(PlayerStats.assists).label('avg_assists')
        ).filter(PlayerStats.user_id == user_id).first()

        # Calculate average rating received
        rating_query = db.session.query(
            db.func.count(PlayerRating.id).label('total_ratings'),
            db.func.avg(PlayerRating.rating).label('avg_rating')
        ).filter(PlayerRating.to_user_id == user_id).first()

        # Get recent games with stats
        recent_games = db.session.query(Game, PlayerStats).join(
            PlayerStats, PlayerStats.game_id == Game.id
        ).filter(PlayerStats.user_id == user_id).order_by(
            Game.time.desc()
        ).limit(10).all()

        # Get recent ratings received
        recent_ratings = db.session.query(PlayerRating, User).join(
            User, User.id == PlayerRating.from_user_id
        ).filter(PlayerRating.to_user_id == user_id).order_by(
            PlayerRating.created_at.desc()
        ).limit(10).all()

        return render_template("user_profile.html",
                             user=user,
                             stats=stats_query,
                             ratings=rating_query,
                             recent_games=recent_games,
                             recent_ratings=recent_ratings)

    # Ensure models are imported so Alembic sees them
    from app import models

    return app
