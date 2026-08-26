"""Spatial search.

The previous implementation loaded every future game and its court into Python,
computed a Haversine distance per row in a `for` loop, and discarded the ones
outside the radius. That is a sequential scan plus O(n) work in the application
for a question the database can answer with an index.

ST_DWithin on a GiST-indexed geography column is a two-stage operation, and both
stages are visible in the query plan: the index gives a bounding-box prefilter
(the && operator over the geography's cached bounding box), then PostGIS refines
the survivors with an exact spheroid distance. Nothing that fails the bounding
box is ever measured.
"""

from datetime import datetime, timedelta

from geoalchemy2 import Geography
from sqlalchemy import func

from app.extensions import db
from app.models import Court, Game

# Bounds for user-supplied search parameters.
MIN_LAT, MAX_LAT = -90.0, 90.0
MIN_LNG, MAX_LNG = -180.0, 180.0
MAX_RADIUS_KM = 200.0
DEFAULT_RADIUS_KM = 10.0

METRES_PER_KM = 1000.0


class InvalidSearch(ValueError):
    """A search the caller got wrong. Carries a message safe to show them."""


def validate_search(lat, lng, radius_km, date_str=None):
    """Normalise and range-check search parameters.

    Returns (lat, lng, radius_km, date) or raises InvalidSearch.
    """
    # `is None`, not falsiness. The previous guard was `if not lat or not lng`,
    # which rejected lat=0 and lng=0 -- the equator and the prime meridian are
    # real places, and Null Island is a real test case.
    if lat is None:
        raise InvalidSearch("Latitude is required.")
    if lng is None:
        raise InvalidSearch("Longitude is required.")

    if not MIN_LAT <= lat <= MAX_LAT:
        raise InvalidSearch(f"Latitude must be between {MIN_LAT} and {MAX_LAT}.")
    if not MIN_LNG <= lng <= MAX_LNG:
        raise InvalidSearch(f"Longitude must be between {MIN_LNG} and {MAX_LNG}.")

    if radius_km is None:
        radius_km = DEFAULT_RADIUS_KM
    if radius_km <= 0:
        raise InvalidSearch("Radius must be greater than zero.")
    if radius_km > MAX_RADIUS_KM:
        raise InvalidSearch(f"Radius must be {MAX_RADIUS_KM:g} km or less.")

    date = None
    if date_str:
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise InvalidSearch("Date must be in YYYY-MM-DD format.") from None

    return lat, lng, radius_km, date


def search_point(lat, lng):
    """A geography point for the given coordinates.

    Longitude first: ST_MakePoint takes (x, y).
    """
    return func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326).cast(Geography)


def nearby_games(lat, lng, radius_km, date=None, now=None):
    """Games at courts within radius_km, nearest first.

    Distance is computed once, in the database, and returned with each row --
    rather than filtering on it and then recomputing it to sort.
    """
    point = search_point(lat, lng)
    distance_m = func.ST_Distance(Court.geog, point).label("distance_m")

    query = (
        db.session.query(Game, Court, distance_m)
        .join(Court, Game.court_id == Court.id)
        # The indexable predicate. ST_DWithin(geography, geography, metres) is
        # what lets the planner use ix_courts_geog; writing
        # `ST_Distance(...) <= :r` instead would be equivalent in meaning and
        # force a sequential scan, because a function result cannot be indexed
        # against a bound at query time.
        .filter(func.ST_DWithin(Court.geog, point, radius_km * METRES_PER_KM))
    )

    if date is not None:
        start = datetime.combine(date, datetime.min.time())
        query = query.filter(Game.time >= start, Game.time < start + timedelta(days=1))
    else:
        query = query.filter(Game.time >= (now or datetime.now()))

    return query.order_by(distance_m, Game.time)


def serialize(game, court, distance_m):
    return {
        "id": game.id,
        "court_id": court.id,
        "court_name": court.name,
        "court_address": court.address,
        "court_lat": court.lat,
        "court_lng": court.lng,
        "time": game.time.isoformat(),
        "max_players": game.max_players,
        "current_players": game.current_players,
        "spots_available": game.spots_available,
        "distance_km": round(distance_m / METRES_PER_KM, 2),
        "host_id": game.host_id,
    }
