"""The signed-in home: a map of every court and the games coming up on them.

The map is the page. Beside it a panel lists games in one of three scopes: all
upcoming, one court, or near a point. /dashboard/feed renders that panel alone
so the map can swap it without a reload, and the page renders the same panel
from the same query string. Every scope therefore has a URL that survives a
reload, the back button, and the redirect after joining or leaving a game.
"""

from flask import Blueprint, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.datastructures import MultiDict

from app.services import listings
from app.services.aggregates import all_courts_brief
from app.services.geo import InvalidSearch, validate_search

bp = Blueprint("home", __name__)

RADIUS_CHOICES_KM = (5, 10, 25, 50, 100)

# How much of the player's own schedule the panel shows before linking to the
# full "my games" page.
MY_GAMES_SHOWN = 3
MY_PLAYED_SHOWN = 2

# Five decimal places is about a metre: plenty for "near here", and it keeps
# the URL a person might share readable.
COORDINATE_PLACES = 5


@bp.route("/dashboard")
@login_required
def index():
    courts = all_courts_brief()
    try:
        panel = _panel(request.args, courts)
    except InvalidSearch:
        # A hand-edited or stale link. The map is still the right place to
        # land, so show everything rather than an error page.
        panel = _panel(MultiDict(), courts)

    counts = listings.upcoming_counts()
    map_data = {
        "courts": [dict(court, upcoming=counts.get(court["id"], 0)) for court in courts],
        "selected": panel["court"]["id"] if panel["court"] else None,
        "search": panel["search"],
    }
    return render_template(
        "dashboard.html", map_data=map_data, radius_choices=RADIUS_CHOICES_KM, **panel
    )


@bp.route("/dashboard/feed")
@login_required
def feed():
    """The panel alone, for the map to swap in place."""
    try:
        panel = _panel(request.args, all_courts_brief())
    except InvalidSearch as exc:
        return str(exc), 400, {"Content-Type": "text/plain; charset=utf-8"}
    return render_template("_feed.html", **panel)


def _panel(args, courts):
    """Resolve the query string to a scope and the games in it.

    ``court`` wins over a point; an unknown court falls back to everything.
    Raises InvalidSearch for a point that is out of range.
    """
    court_id = args.get("court", type=int)
    if court_id is not None:
        court = next((c for c in courts if c["id"] == court_id), None)
        if court is not None:
            return _scope(
                "court",
                listings.upcoming(court_id=court_id),
                url_for("home.index", court=court_id),
                court=court,
            )

    if "lat" in args or "lng" in args:
        lat, lng, radius_km, _date = validate_search(
            args.get("lat", type=float),
            args.get("lng", type=float),
            args.get("radius", type=float),
        )
        lat, lng = round(lat, COORDINATE_PLACES), round(lng, COORDINATE_PLACES)
        return _scope(
            "near",
            listings.near(lat, lng, radius_km),
            url_for("home.index", lat=lat, lng=lng, radius=f"{radius_km:g}"),
            search={"lat": lat, "lng": lng, "radius": radius_km},
        )

    # The unscoped panel opens with the player's own games: what they are
    # booked into, then what they last played.
    mine = {
        "upcoming": listings.my_upcoming(current_user.id),
        "played": listings.my_recent(current_user.id, limit=MY_PLAYED_SHOWN),
        "shown": MY_GAMES_SHOWN,
    }
    return _scope("all", listings.upcoming(), url_for("home.index"), mine=mine)


def _scope(mode, games, url, court=None, search=None, mine=None):
    return {
        "mode": mode,
        "games": games,
        "court": court,
        "search": search,
        "mine": mine,
        # Where join and leave send the player back to: this same panel.
        "panel_url": url,
    }
