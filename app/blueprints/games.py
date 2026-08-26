"""Game listing, creation, roster management and nearby search."""

from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.forms import ConfirmForm, GameForm, RatingForm, StatsForm
from app.models import Court, Game, GamePlayer, PlayerRating, PlayerStats
from app.timeutils import to_utc

bp = Blueprint("games", __name__, url_prefix="/games")


@bp.route("")
@login_required
def index():
    court_id = request.args.get("court_id")
    date = request.args.get("date")

    # Without these the template triggers a query per row for each of
    # game.court, game.host, game.players and game.can_join() -- roughly 4N
    # extra round trips to render N rows.
    #
    # joinedload for the many-to-one sides (one row each, cheap to widen the
    # join); selectinload for the roster, where a join would multiply the
    # result set by the number of players.
    query = Game.query.options(
        joinedload(Game.court),
        joinedload(Game.host),
        selectinload(Game.players),
    )
    if court_id:
        query = query.filter_by(court_id=court_id)
    if date:
        try:
            # Deliberately naive: a calendar date has no timezone until it is
            # anchored to one, which to_utc does on the next line.
            date_obj = datetime.strptime(date, "%Y-%m-%d").date()  # noqa: DTZ007
            start = to_utc(datetime.combine(date_obj, datetime.min.time()))
            query = query.filter(Game.time >= start, Game.time < start + timedelta(days=1))
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
            time=to_utc(form.time.data),
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
    if not ConfirmForm().validate_on_submit():
        flash("Could not verify that request. Please try again.")
        return redirect(url_for("games.index"))

    # Lock the game row for the rest of the transaction. Two requests racing to
    # take the last slot now queue here instead of both reading "one slot left"
    # and both inserting.
    game = db.session.execute(
        db.select(Game).where(Game.id == game_id).with_for_update()
    ).scalar_one_or_none()
    if game is None:
        abort(404)

    if not game.can_join(current_user):
        db.session.rollback()
        flash("Cannot join this game (full or already joined).")
        return redirect(url_for("games.index"))

    db.session.add(GamePlayer(game_id=game_id, user_id=current_user.id))
    try:
        db.session.commit()
    except IntegrityError:
        # The database enforces capacity too, via a trigger. Reaching this means
        # the lock above was bypassed by some other write path -- the constraint
        # is the backstop, not the primary mechanism.
        db.session.rollback()
        flash("Cannot join this game (full or already joined).")
        return redirect(url_for("games.index"))

    flash("Successfully joined the game!")
    return redirect(url_for("games.index"))


@bp.route("/<int:game_id>/leave", methods=["POST"])
@login_required
def leave(game_id):
    db.get_or_404(Game, game_id)  # 404s on a missing game

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
    game = db.get_or_404(Game, game_id)
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
