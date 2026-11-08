"""Game listing, creation, roster management and detail."""

from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.forms import ConfirmForm, GameForm, RatingForm, StatsForm
from app.models import Court, Game, GamePlayer, PlayerRating, PlayerStats
from app.services.aggregates import all_courts_brief
from app.services.geo import invalidate_area
from app.timeutils import to_utc, utcnow

bp = Blueprint("games", __name__, url_prefix="/games")

PAGE_SIZE = 20


@bp.route("")
@login_required
def index():
    court_id = request.args.get("court_id", type=int)
    date = _parse_date(request.args.get("date"))

    # Without these the template triggers a query per row for each of
    # game.court, game.host, game.players and game.can_join(). joinedload for
    # the many-to-one sides, selectinload for the roster -- joining that would
    # multiply the result set by the number of players.
    query = db.select(Game).options(
        joinedload(Game.court),
        joinedload(Game.host),
        selectinload(Game.players),
    )
    if court_id is not None:
        query = query.filter(Game.court_id == court_id)
    if date is not None:
        start = to_utc(datetime.combine(date, datetime.min.time()))
        query = query.filter(Game.time >= start, Game.time < start + timedelta(days=1))
    else:
        # Default to what people come here for. Without a bound the listing
        # grows without limit and page one is the oldest game ever played.
        query = query.filter(Game.time >= utcnow())

    pagination = db.paginate(
        query.order_by(Game.time),
        page=request.args.get("page", 1, type=int),
        per_page=PAGE_SIZE,
        error_out=False,
    )

    return render_template(
        "games.html",
        games=pagination.items,
        pagination=pagination,
        # Carried into the pager links so paging does not drop the filters.
        filters={key: value for key, value in request.args.items() if key != "page"},
        courts=all_courts_brief(),
        confirm_form=ConfirmForm(),
    )


@bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    form = GameForm().set_court_choices(all_courts_brief())
    if form.validate_on_submit():
        game = Game(
            court_id=form.court_id.data,
            host_id=current_user.id,
            time=to_utc(form.time.data),
            max_players=form.max_players.data,
        )
        db.session.add(game)
        db.session.commit()
        _invalidate_searches_for(game)
        flash("Game created successfully!")
        return redirect(url_for("games.index"))

    return render_template("create_game.html", form=form)


@bp.route("/<int:game_id>/join", methods=["POST"])
@login_required
def join(game_id):
    if not ConfirmForm().validate_on_submit():
        flash("Could not verify that request. Please try again.")
        return redirect(url_for("games.index"))

    # Lock the game row for the rest of the transaction. Two requests racing for
    # the last slot queue here instead of both reading "one slot left" and both
    # inserting.
    game = db.session.scalar(db.select(Game).where(Game.id == game_id).with_for_update())
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
        # A trigger enforces capacity as well. Reaching this means the lock was
        # bypassed by some other write path: the constraint is the backstop, not
        # the primary mechanism.
        db.session.rollback()
        flash("Cannot join this game (full or already joined).")
        return redirect(url_for("games.index"))

    _invalidate_searches_for(game)
    flash("Successfully joined the game!")
    return redirect(url_for("games.index"))


@bp.route("/<int:game_id>/leave", methods=["POST"])
@login_required
def leave(game_id):
    game = db.get_or_404(Game, game_id)

    if not ConfirmForm().validate_on_submit():
        flash("Could not verify that request. Please try again.")
        return redirect(url_for("games.index"))

    membership = db.session.get(GamePlayer, (game_id, current_user.id))
    if membership is None:
        flash("You are not in this game.")
        return redirect(url_for("games.index"))

    db.session.delete(membership)
    db.session.commit()
    _invalidate_searches_for(game)
    flash("Successfully left the game!")
    return redirect(url_for("games.index"))


@bp.route("/<int:game_id>")
@login_required
def detail(game_id):
    game = db.session.scalar(
        db.select(Game)
        .where(Game.id == game_id)
        .options(joinedload(Game.court), joinedload(Game.host), selectinload(Game.players))
    )
    if game is None:
        abort(404)

    stats = db.session.scalars(
        db.select(PlayerStats).filter_by(game_id=game_id)
    ).all()
    my_ratings = db.session.scalars(
        db.select(PlayerRating).filter_by(game_id=game_id, from_user_id=current_user.id)
    ).all()

    return render_template(
        "game_detail.html",
        game=game,
        is_rostered=current_user in game.players,
        stats_dict={stat.user_id: stat for stat in stats},
        ratings_dict={rating.to_user_id: rating for rating in my_ratings},
        stats_form=StatsForm(),
        rating_form=RatingForm(),
        confirm_form=ConfirmForm(),
    )


def _parse_date(raw):
    if not raw:
        return None
    try:
        # Naive on purpose: a calendar date has no timezone until it is anchored
        # to one, which to_utc does for it.
        return datetime.strptime(raw, "%Y-%m-%d").date()  # noqa: DTZ007
    except ValueError:
        return None


def _invalidate_searches_for(game):
    """Drop cached nearby searches that could have included this game.

    A nearby result carries current_players and spots_available, so a roster
    change makes every cached search covering that court wrong.
    """
    if game is None:
        return
    court = game.court or db.session.get(Court, game.court_id)
    if court is not None:
        invalidate_area(court.lat, court.lng)
