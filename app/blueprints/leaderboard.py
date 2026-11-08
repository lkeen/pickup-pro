"""Leaderboards.

The most expensive read in the app -- a group-by across every stat row -- and
the one nobody minds being a few minutes out of date, which makes it the natural
thing to cache.
"""

from flask import Blueprint, render_template, request
from flask_login import login_required

from app.services.aggregates import DEFAULT_METRIC, METRICS, leaderboard, rating_leaderboard

bp = Blueprint("leaderboard", __name__, url_prefix="/leaderboard")


@bp.route("")
@login_required
def index():
    metric = request.args.get("metric", DEFAULT_METRIC)
    if metric not in METRICS:
        metric = DEFAULT_METRIC

    return render_template(
        "leaderboard.html",
        metric=metric,
        metric_label=METRICS[metric][1],
        metrics={key: label for key, (_expr, label) in METRICS.items()},
        rows=leaderboard(metric),
        rated=rating_leaderboard(),
    )
