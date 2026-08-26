"""Post-game stat entry and player ratings.

Mounted under /games because these act on a game, but kept separate from the
games blueprint: they are the write path for player-reported data and have
different authorization requirements from ordinary roster management.
"""

from datetime import datetime

from flask import Blueprint, flash, redirect, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import RatingForm, StatsForm
from app.models import Game, PlayerRating, PlayerStats

bp = Blueprint("stats", __name__, url_prefix="/games")


@bp.route("/<int:game_id>/stats", methods=["POST"])
@login_required
def submit_stats(game_id):
    game = Game.query.get_or_404(game_id)

    # Only rostered players can submit stats
    if current_user not in game.players:
        flash("Only rostered players can submit stats.")
        return redirect(url_for("games.detail", game_id=game_id))

    form = StatsForm()
    if not form.validate_on_submit():
        flash("Invalid stats values.")
        return redirect(url_for("games.detail", game_id=game_id))

    # Check if stats already exist
    existing_stats = PlayerStats.query.filter_by(
        game_id=game_id, user_id=form.user_id.data
    ).first()

    if existing_stats:
        existing_stats.points = form.points.data
        existing_stats.rebounds = form.rebounds.data
        existing_stats.assists = form.assists.data
        existing_stats.updated_at = datetime.now()
    else:
        db.session.add(
            PlayerStats(
                game_id=game_id,
                user_id=form.user_id.data,
                points=form.points.data,
                rebounds=form.rebounds.data,
                assists=form.assists.data,
            )
        )

    db.session.commit()
    flash("Stats updated successfully!")
    return redirect(url_for("games.detail", game_id=game_id))


@bp.route("/<int:game_id>/rate", methods=["POST"])
@login_required
def submit_rating(game_id):
    game = Game.query.get_or_404(game_id)

    # Only rostered players can rate
    if current_user not in game.players:
        flash("Only rostered players can rate others.")
        return redirect(url_for("games.detail", game_id=game_id))

    form = RatingForm()
    if not form.validate_on_submit():
        flash("Invalid rating values.")
        return redirect(url_for("games.detail", game_id=game_id))

    # Prevent self-rating
    if form.to_user_id.data == current_user.id:
        flash("You cannot rate yourself.")
        return redirect(url_for("games.detail", game_id=game_id))

    # Check if rating already exists
    existing_rating = PlayerRating.query.filter_by(
        game_id=game_id, from_user_id=current_user.id, to_user_id=form.to_user_id.data
    ).first()

    if existing_rating:
        existing_rating.rating = form.rating.data
        existing_rating.comment = form.comment.data
    else:
        db.session.add(
            PlayerRating(
                game_id=game_id,
                from_user_id=current_user.id,
                to_user_id=form.to_user_id.data,
                rating=form.rating.data,
                comment=form.comment.data,
            )
        )

    db.session.commit()
    flash("Rating submitted successfully!")
    return redirect(url_for("games.detail", game_id=game_id))
