"""JSON API.

Versioned under /api/v1 and kept apart from the HTML blueprints: these responses
are consumed by the front-end's fetch calls, and their shape is a contract in a
way a rendered page is not.
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required
from sqlalchemy.orm import selectinload

from app.models import Game
from app.services import caching
from app.services.geo import (
    NEARBY_TTL_SECONDS,
    InvalidSearch,
    nearby_cache_key,
    nearby_cache_tags,
    nearby_games,
    serialize,
    validate_search,
)

bp = Blueprint("api", __name__, url_prefix="/api/v1")


@bp.route("/games/nearby")
@login_required
def games_nearby():
    try:
        lat, lng, radius_km, date = validate_search(
            request.args.get("lat", type=float),
            request.args.get("lng", type=float),
            request.args.get("radius", type=float),
            request.args.get("date"),
        )
    except InvalidSearch as exc:
        return jsonify({"error": str(exc)}), 400

    def compute():
        rows = (
            nearby_games(lat, lng, radius_km, date=date)
            # serialize() reads game.current_players, which counts the roster.
            # Without this the response costs one extra query per game returned.
            .options(selectinload(Game.players))
            .all()
        )
        return {
            "games": [serialize(game, court, distance_m) for game, court, distance_m in rows],
            "count": len(rows),
            "radius_km": radius_km,
        }

    payload = caching.get_or_set(
        nearby_cache_key(lat, lng, radius_km, date),
        compute,
        ttl=NEARBY_TTL_SECONDS,
        tags=nearby_cache_tags(lat, lng, radius_km),
    )
    return jsonify(payload)
