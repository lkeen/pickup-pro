"""User profiles with lifetime stats and ratings."""

from flask import Blueprint, render_template
from flask_login import login_required

from app.extensions import db
from app.models import Game, PlayerRating, PlayerStats, User

bp = Blueprint("profiles", __name__, url_prefix="/users")


@bp.route("/<int:user_id>")
@login_required
def detail(user_id):
    user = User.query.get_or_404(user_id)

    # Calculate lifetime stats aggregations
    stats_query = db.session.query(
        db.func.count(PlayerStats.id).label("games_played"),
        db.func.sum(PlayerStats.points).label("total_points"),
        db.func.sum(PlayerStats.rebounds).label("total_rebounds"),
        db.func.sum(PlayerStats.assists).label("total_assists"),
        db.func.avg(PlayerStats.points).label("avg_points"),
        db.func.avg(PlayerStats.rebounds).label("avg_rebounds"),
        db.func.avg(PlayerStats.assists).label("avg_assists"),
    ).filter(PlayerStats.user_id == user_id).first()

    # Calculate average rating received
    rating_query = db.session.query(
        db.func.count(PlayerRating.id).label("total_ratings"),
        db.func.avg(PlayerRating.rating).label("avg_rating"),
    ).filter(PlayerRating.to_user_id == user_id).first()

    # Get recent games with stats
    recent_games = (
        db.session.query(Game, PlayerStats)
        .join(PlayerStats, PlayerStats.game_id == Game.id)
        .filter(PlayerStats.user_id == user_id)
        .order_by(Game.time.desc())
        .limit(10)
        .all()
    )

    # Get recent ratings received
    recent_ratings = (
        db.session.query(PlayerRating, User)
        .join(User, User.id == PlayerRating.from_user_id)
        .filter(PlayerRating.to_user_id == user_id)
        .order_by(PlayerRating.created_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "user_profile.html",
        user=user,
        stats=stats_query,
        ratings=rating_query,
        recent_games=recent_games,
        recent_ratings=recent_ratings,
    )
