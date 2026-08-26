"""Game listing, creation, roster management and nearby search."""

from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import ConfirmForm, GameForm, RatingForm, StatsForm
from app.models import Court, Game, GamePlayer, PlayerRating, PlayerStats

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
    return render_template(
        "games.html", games=games, courts=courts, confirm_form=ConfirmForm()
    )


@bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    form = GameForm().set_court_choices(Court.query.all())
    if form.validate_on_submit():
        game = Game(
            court_id=form.court_id.data,
            host_id=current_user.id,
            time=form.time.data,
            max_players=form.max_players.data,
        )
        db.session.add(game)
        db.session.commit()
        flash("Game created successfully!")
        return redirect(url_for("games.index"))

    return render_template("create_game.html", form=form)


@bp.route("/<int:game_id>/join", methods=["POST"])
@login_required
def join(game_id):
    game = Game.query.get_or_404(game_id)

    if not ConfirmForm().validate_on_submit():
        flash("Could not verify that request. Please try again.")
        return redirect(url_for("games.index"))

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
    Game.query.get_or_404(game_id)  # 404s on a missing game

    if not ConfirmForm().validate_on_submit():
        flash("Could not verify that request. Please try again.")
        return redirect(url_for("games.index"))

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
        stats_form=StatsForm(),
        rating_form=RatingForm(),
        confirm_form=ConfirmForm(),
    )
