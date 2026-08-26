"""Post-game stat entry and player ratings.

Mounted under /games because these act on a game, but kept separate from the
games blueprint: they are the write path for player-reported data and have
different authorization requirements from ordinary roster management.
"""

from datetime import datetime

from flask import Blueprint, flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
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

    user_id = request.form.get("user_id")
    points = request.form.get("points", 0)
    rebounds = request.form.get("rebounds", 0)
    assists = request.form.get("assists", 0)

    try:
        user_id = int(user_id)
        points = int(points) if points else 0
        rebounds = int(rebounds) if rebounds else 0
        assists = int(assists) if assists else 0
    except (TypeError, ValueError):
        flash("Invalid stats values.")
        return redirect(url_for("games.detail", game_id=game_id))

    # Check if stats already exist
    existing_stats = PlayerStats.query.filter_by(
        game_id=game_id, user_id=user_id
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
            assists=assists,
        )
        db.session.add(new_stats)

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

    to_user_id = request.form.get("to_user_id")
    rating = request.form.get("rating")
    comment = request.form.get("comment", "").strip()

    try:
        to_user_id = int(to_user_id)
        rating = int(rating)
    except (TypeError, ValueError):
        flash("Invalid rating values.")
        return redirect(url_for("games.detail", game_id=game_id))

    # Prevent self-rating
    if to_user_id == current_user.id:
        flash("You cannot rate yourself.")
        return redirect(url_for("games.detail", game_id=game_id))

    # Validate rating range
    if rating < 1 or rating > 5:
        flash("Rating must be between 1 and 5.")
        return redirect(url_for("games.detail", game_id=game_id))

    # Check if rating already exists
    existing_rating = PlayerRating.query.filter_by(
        game_id=game_id, from_user_id=current_user.id, to_user_id=to_user_id
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
            comment=comment,
        )
        db.session.add(new_rating)

    db.session.commit()
    flash("Rating submitted successfully!")
    return redirect(url_for("games.detail", game_id=game_id))
