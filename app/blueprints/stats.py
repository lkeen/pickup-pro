"""Post-game stat entry and player ratings.

Mounted under /games because these act on a game, but kept separate from the
games blueprint: they are the write path for player-reported data and have
different authorization requirements from ordinary roster management.
"""

from datetime import datetime

from flask import Blueprint, flash, g, redirect, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import RatingForm, StatsForm
from app.models import PlayerRating, PlayerStats
from app.security import forbid_self, require_roster, require_target_on_roster

bp = Blueprint("stats", __name__, url_prefix="/games")


@bp.route("/<int:game_id>/stats", methods=["POST"])
@login_required
@require_roster
@require_target_on_roster("user_id")
def submit_stats(game_id):
    form = StatsForm()
    if not form.validate_on_submit():
        flash("Invalid stats values.")
        return redirect(url_for("games.detail", game_id=game_id))

    # g.target_user_id is set by require_target_on_roster, which has already
    # confirmed the player is on this roster.
    existing = PlayerStats.query.filter_by(
        game_id=game_id, user_id=g.target_user_id
    ).first()

    if existing:
        existing.points = form.points.data
        existing.rebounds = form.rebounds.data
        existing.assists = form.assists.data
        existing.updated_at = datetime.now()
    else:
        db.session.add(
            PlayerStats(
                game_id=game_id,
                user_id=g.target_user_id,
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
@require_roster
@require_target_on_roster("to_user_id")
@forbid_self("to_user_id")
def submit_rating(game_id):
    form = RatingForm()
    if not form.validate_on_submit():
        flash("Invalid rating values.")
        return redirect(url_for("games.detail", game_id=game_id))

    existing = PlayerRating.query.filter_by(
        game_id=game_id, from_user_id=current_user.id, to_user_id=g.target_user_id
    ).first()

    if existing:
        existing.rating = form.rating.data
        existing.comment = form.comment.data
    else:
        db.session.add(
            PlayerRating(
                game_id=game_id,
                from_user_id=current_user.id,
                to_user_id=g.target_user_id,
                rating=form.rating.data,
                comment=form.comment.data,
            )
        )

    db.session.commit()
    flash("Rating submitted successfully!")
    return redirect(url_for("games.detail", game_id=game_id))
