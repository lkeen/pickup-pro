"""Derived statistics: profile totals and leaderboards.

These are the queries that get slower as the app succeeds. A profile's lifetime
totals scan every stat row that player has produced, and they were recomputed on
every page view even though they change only when that player records a stat.

Cached with a tag per user, so a stat write invalidates exactly that player's
totals and nothing else.
"""

from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Court, Game, PlayerRating, PlayerStats, User
from app.services import caching

PROFILE_TTL_SECONDS = 300
COURTS_TTL_SECONDS = 600
LEADERBOARD_TTL_SECONDS = 300

COURTS_TAG = "courts:list"
LEADERBOARD_TAG = "leaderboard"


def user_tag(user_id):
    return f"user:{user_id}"


def profile_summary(user_id):
    """Lifetime totals and averages, plus the rating summary.

    Plain dicts rather than SQLAlchemy Rows: a cached value has to survive a
    round trip through Redis.
    """

    def compute():
        stats = db.session.execute(
            db.select(
                db.func.count(PlayerStats.id).label("games_played"),
                db.func.sum(PlayerStats.points).label("total_points"),
                db.func.sum(PlayerStats.rebounds).label("total_rebounds"),
                db.func.sum(PlayerStats.assists).label("total_assists"),
                db.func.avg(PlayerStats.points).label("avg_points"),
                db.func.avg(PlayerStats.rebounds).label("avg_rebounds"),
                db.func.avg(PlayerStats.assists).label("avg_assists"),
            ).where(PlayerStats.user_id == user_id)
        ).one()

        ratings = db.session.execute(
            db.select(
                db.func.count(PlayerRating.id).label("total_ratings"),
                db.func.avg(PlayerRating.rating).label("avg_rating"),
            ).where(PlayerRating.to_user_id == user_id)
        ).one()

        return {
            "games_played": stats.games_played or 0,
            "total_points": int(stats.total_points or 0),
            "total_rebounds": int(stats.total_rebounds or 0),
            "total_assists": int(stats.total_assists or 0),
            "avg_points": float(stats.avg_points or 0),
            "avg_rebounds": float(stats.avg_rebounds or 0),
            "avg_assists": float(stats.avg_assists or 0),
            "total_ratings": ratings.total_ratings or 0,
            "avg_rating": float(ratings.avg_rating) if ratings.avg_rating is not None else None,
        }

    return caching.get_or_set(
        caching.make_key("profile", user=user_id),
        compute,
        ttl=PROFILE_TTL_SECONDS,
        tags=(user_tag(user_id),),
    )


def recent_games(user_id, limit=10):
    """The player's last games with their stat line.

    Not cached: a small indexed query that changes on the same events as the
    summary, so caching it would only add an invalidation path.
    """
    return db.session.execute(
        db.select(Game, PlayerStats)
        .join(PlayerStats, PlayerStats.game_id == Game.id)
        .where(PlayerStats.user_id == user_id)
        # The profile table reads game.court.name per row.
        .options(joinedload(Game.court))
        .order_by(Game.time.desc())
        .limit(limit)
    ).all()


def recent_ratings(user_id, limit=10):
    return db.session.execute(
        db.select(PlayerRating, User)
        .join(User, User.id == PlayerRating.from_user_id)
        .where(PlayerRating.to_user_id == user_id)
        .order_by(PlayerRating.created_at.desc())
        .limit(limit)
    ).all()


def invalidate_user(user_id):
    """Called whenever a stat or rating for this player changes."""
    return caching.invalidate(user_tag(user_id), LEADERBOARD_TAG)


def all_courts_brief():
    """Every court, as plain dicts.

    Read by the courts page, the games page, the game-creation form and the
    map. Small and rarely changed.
    """

    def compute():
        return [
            {
                "id": court.id,
                "name": court.name,
                "address": court.address,
                "lat": court.lat,
                "lng": court.lng,
            }
            for court in db.session.scalars(db.select(Court).order_by(Court.name))
        ]

    return caching.get_or_set(
        caching.make_key("courts", scope="all"),
        compute,
        ttl=COURTS_TTL_SECONDS,
        tags=(COURTS_TAG,),
    )


def invalidate_courts():
    return caching.invalidate(COURTS_TAG)


METRICS = {
    "points": (db.func.sum(PlayerStats.points), "Total points"),
    "rebounds": (db.func.sum(PlayerStats.rebounds), "Total rebounds"),
    "assists": (db.func.sum(PlayerStats.assists), "Total assists"),
    "ppg": (db.func.avg(PlayerStats.points), "Points per game"),
}

DEFAULT_METRIC = "points"

# A single good game should not top a season, so averages only count once a
# player has enough games for the average to mean anything.
MIN_GAMES_FOR_AVERAGE = 3


def leaderboard(metric=DEFAULT_METRIC, limit=10):
    if metric not in METRICS:
        metric = DEFAULT_METRIC

    def compute():
        expression, _label = METRICS[metric]
        query = (
            db.select(
                User.id,
                User.username,
                expression.label("value"),
                db.func.count(PlayerStats.id).label("games"),
            )
            .join(PlayerStats, PlayerStats.user_id == User.id)
            .group_by(User.id, User.username)
        )
        if metric == "ppg":
            query = query.having(db.func.count(PlayerStats.id) >= MIN_GAMES_FOR_AVERAGE)

        rows = db.session.execute(query.order_by(db.desc("value")).limit(limit)).all()
        return [
            {
                "user_id": row.id,
                "username": row.username,
                "value": round(float(row.value or 0), 1),
                "games": row.games,
            }
            for row in rows
        ]

    return caching.get_or_set(
        caching.make_key("leaderboard", metric=metric, limit=limit),
        compute,
        ttl=LEADERBOARD_TTL_SECONDS,
        tags=(LEADERBOARD_TAG,),
    )


def rating_leaderboard(limit=10):
    def compute():
        rows = db.session.execute(
            db.select(
                User.id,
                User.username,
                db.func.avg(PlayerRating.rating).label("value"),
                db.func.count(PlayerRating.id).label("ratings"),
            )
            .join(PlayerRating, PlayerRating.to_user_id == User.id)
            .group_by(User.id, User.username)
            .having(db.func.count(PlayerRating.id) >= MIN_GAMES_FOR_AVERAGE)
            .order_by(db.desc("value"))
            .limit(limit)
        ).all()
        return [
            {
                "user_id": row.id,
                "username": row.username,
                "value": round(float(row.value), 2),
                "ratings": row.ratings,
            }
            for row in rows
        ]

    return caching.get_or_set(
        caching.make_key("leaderboard", metric="rating", limit=limit),
        compute,
        ttl=LEADERBOARD_TTL_SECONDS,
        tags=(LEADERBOARD_TAG,),
    )


def chart_data(user_id, games=None):
    """Series for the profile charts.

    Built from the rows the tables already render -- reversed, because a table
    shows newest first and a trend line reads left to right.
    """
    if games is None:
        games = recent_games(user_id)

    series = [
        {
            "date": game.time.strftime("%d %b"),
            "points": stat.points or 0,
            "rebounds": stat.rebounds or 0,
            "assists": stat.assists or 0,
        }
        for game, stat in reversed(games)
    ]

    counts = dict(
        db.session.execute(
            db.select(PlayerRating.rating, db.func.count(PlayerRating.id))
            .where(PlayerRating.to_user_id == user_id)
            .group_by(PlayerRating.rating)
        ).all()
    )
    return {"games": series, "ratings": [counts.get(score, 0) for score in range(1, 6)]}
