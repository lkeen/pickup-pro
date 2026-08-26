"""Game listing, creation, roster management and nearby search."""

from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Court, Game, GamePlayer, PlayerRating, PlayerStats
from app.utils import haversine_distance

bp = Blueprint("games", __name__, url_prefix="/games")


@bp.route("")
@login_required
def index():
    court_id = request.args.get("court_id")
    date = request.args.get("date")

    query = Game.query
    if court_id:
        query = query.filter_by(court_id=court_id)
    if date:
        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d").date()
            query = query.filter(Game.time >= date_obj)
            query = query.filter(
                Game.time
                < datetime.combine(date_obj, datetime.min.time()) + timedelta(days=1)
            )
        except ValueError:
            pass

    games = query.order_by(Game.time).all()
    courts = Court.query.all()
    return render_template("games.html", games=games, courts=courts)


@bp.route("/nearby")
@login_required
def nearby():
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
            query = query.filter(
                Game.time
                < datetime.combine(date_obj, datetime.min.time()) + timedelta(days=1)
            )
        except ValueError:
            pass
    else:
        # Default: only show future games
        query = query.filter(Game.time >= datetime.now())

    games_with_courts = query.order_by(Game.time).all()

    # Calculate distance for each game and filter by radius
    nearby_games = []
    for game, court in games_with_courts:
        distance = haversine_distance(lat, lng, court.lat, court.lng)
        if distance <= radius:
            nearby_games.append(
                {
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
                    "host_id": game.host_id,
                }
            )

    # Sort by distance
    nearby_games.sort(key=lambda x: x["distance_km"])

    return jsonify({"games": nearby_games, "count": len(nearby_games)})


@bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
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
            max_players=max_players,
        )
        db.session.add(game)
        db.session.commit()
        flash("Game created successfully!")
        return redirect(url_for("games.index"))

    courts = Court.query.all()
    return render_template("create_game.html", courts=courts)


@bp.route("/<int:game_id>/join", methods=["POST"])
@login_required
def join(game_id):
    game = Game.query.get_or_404(game_id)

    if not game.can_join(current_user):
        flash("Cannot join this game (full or already joined).")
        return redirect(url_for("games.index"))

    game_player = GamePlayer(game_id=game_id, user_id=current_user.id)
    db.session.add(game_player)
    db.session.commit()
    flash("Successfully joined the game!")
    return redirect(url_for("games.index"))


@bp.route("/<int:game_id>/leave", methods=["POST"])
@login_required
def leave(game_id):
    game = Game.query.get_or_404(game_id)  # noqa: F841 - 404s on a missing game

    game_player = GamePlayer.query.filter_by(
        game_id=game_id, user_id=current_user.id
    ).first()

    if not game_player:
        flash("You are not in this game.")
        return redirect(url_for("games.index"))

    db.session.delete(game_player)
    db.session.commit()
    flash("Successfully left the game!")
    return redirect(url_for("games.index"))


@bp.route("/<int:game_id>")
@login_required
def detail(game_id):
    game = Game.query.get_or_404(game_id)
    is_rostered = current_user in game.players

    # Get current stats for this game
    player_stats = PlayerStats.query.filter_by(game_id=game_id).all()
    stats_dict = {stat.user_id: stat for stat in player_stats}

    # Get current ratings for this game (that current user has given)
    my_ratings = PlayerRating.query.filter_by(
        game_id=game_id, from_user_id=current_user.id
    ).all()
    ratings_dict = {rating.to_user_id: rating for rating in my_ratings}

    return render_template(
        "game_detail.html",
        game=game,
        is_rostered=is_rostered,
        stats_dict=stats_dict,
        ratings_dict=ratings_dict,
    )
