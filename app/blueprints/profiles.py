"""User profiles with lifetime stats and ratings."""

from flask import Blueprint, render_template
from flask_login import login_required

from app.extensions import db
from app.models import User
from app.services.aggregates import (
    chart_data,
    profile_summary,
    recent_games,
    recent_ratings,
)

bp = Blueprint("profiles", __name__, url_prefix="/users")


@bp.route("/<int:user_id>")
@login_required
def detail(user_id):
    user = db.get_or_404(User, user_id)
    games = recent_games(user_id)
    return render_template(
        "user_profile.html",
        user=user,
        summary=profile_summary(user_id),
        recent_games=games,
        recent_ratings=recent_ratings(user_id),
        chart_data=chart_data(user_id, games),
    )
