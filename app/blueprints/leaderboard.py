"""Leaderboards.

The most expensive read in the app: a group-by across every stat row, ordered.
It is also the one nobody minds being a few minutes out of date, which makes it
the natural thing to cache.
"""

from flask import Blueprint, render_template, request
from flask_login import login_required

from app.services.aggregates import METRICS, leaderboard, rating_leaderboard

bp = Blueprint("leaderboard", __name__, url_prefix="/leaderboard")


@bp.route("")
@login_required
def index():
    metric = request.args.get("metric", "points")
    if metric not in METRICS:
        metric = "points"

    return render_template(
        "leaderboard.html",
        metric=metric,
        metric_label=METRICS[metric][1],
        metrics={key: label for key, (_expr, label) in METRICS.items()},
        rows=leaderboard(metric),
        rated=rating_leaderboard(),
    )
