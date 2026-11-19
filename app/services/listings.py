"""Game listings for the map home and the "my games" page.

The map's side panel lists games in one of three scopes: everything coming up,
one court, or near a point. All three render the same rows, so the queries live
here rather than in each view.
"""

from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import Game, GamePlayer
from app.services.geo import METRES_PER_KM, nearby_games
from app.timeutils import utcnow

# The panel is a glance, not a listing. Past this many rows the games page,
# with its filters and pager, is the better tool.
FEED_LIMIT = 30

# Nobody has this many games booked. The bound keeps the page finite anyway.
MY_UPCOMING_LIMIT = 50


def _row_options(query):
    """Load what a listing row renders: the court, the host and the roster.

    Without these every row costs a query each for game.court, game.host and
    the roster count.
    """
    return query.options(
        joinedload(Game.court),
        joinedload(Game.host),
        selectinload(Game.players),
    )


def upcoming(court_id=None, limit=FEED_LIMIT, now=None):
    """Games that have not started yet, soonest first.

    Returns (game, None) pairs, the same shape as near(), so a template renders
    either without caring which scope it is showing.
    """
    query = db.select(Game).where(Game.time >= (now or utcnow()))
    if court_id is not None:
        query = query.where(Game.court_id == court_id)
    games = db.session.scalars(_row_options(query).order_by(Game.time).limit(limit)).all()
    return [(game, None) for game in games]


def near(lat, lng, radius_km, limit=FEED_LIMIT, now=None):
    """Upcoming games within radius_km of a point, nearest first.

    The same indexed ST_DWithin query as the JSON search. Returns
    (game, distance_km) pairs.
    """
    rows = (
        nearby_games(lat, lng, radius_km, now=now)
        # The query already selects each game's court, which puts it in the
        # identity map, so game.court resolves without another round trip.
        .options(joinedload(Game.host), selectinload(Game.players))
        .limit(limit)
        .all()
    )
    return [(game, distance_m / METRES_PER_KM) for game, _court, distance_m in rows]


def upcoming_counts(now=None):
    """Upcoming games per court id, for sizing the map's markers.

    Not cached: one grouped scan over the time index, and a count that has to
    move the moment someone hosts a game.
    """
    rows = db.session.execute(
        db.select(Game.court_id, db.func.count(Game.id))
        .where(Game.time >= (now or utcnow()))
        .group_by(Game.court_id)
    ).all()
    return {court_id: count for court_id, count in rows}


def _involving(user_id):
    """Games the user hosts or is on the roster of.

    A host is not added to their own roster, so membership alone would leave
    out the games they are running.
    """
    rostered = db.select(GamePlayer.game_id).where(GamePlayer.user_id == user_id)
    return db.or_(Game.host_id == user_id, Game.id.in_(rostered))


def my_upcoming(user_id, now=None, limit=MY_UPCOMING_LIMIT):
    query = db.select(Game).where(_involving(user_id), Game.time >= (now or utcnow()))
    return db.session.scalars(_row_options(query).order_by(Game.time).limit(limit)).all()


def my_past_query(user_id, now=None):
    """A select of the user's finished games, most recent first, for paging."""
    query = db.select(Game).where(_involving(user_id), Game.time < (now or utcnow()))
    return _row_options(query).order_by(Game.time.desc())


def my_recent(user_id, limit=3, now=None):
    """The user's last few finished games, most recent first."""
    return db.session.scalars(my_past_query(user_id, now=now).limit(limit)).all()
