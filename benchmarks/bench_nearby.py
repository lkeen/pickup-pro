"""Benchmark the nearby-games search: sequential scan vs GiST vs GiST + cache.

Run against the test database, which it populates and then empties:

    APP_ENV=testing python benchmarks/bench_nearby.py --courts 25000 --games 75000

The three configurations answer the same question and must return the same
games; the script asserts that before reporting any timing, because a fast
wrong answer is not an optimisation.
"""

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Court, Game  # noqa: E402
from app.services import caching  # noqa: E402
from app.services.geo import (  # noqa: E402
    MAX_RESULTS,
    nearby_cache_key,
    nearby_cache_tags,
    nearby_games,
)
from app.utils import haversine_distance  # noqa: E402

# Athens, GA -- the middle of the seeded region.
LAT, LNG = 33.9519, -83.3576
RADIUS_KM = 25.0

TABLES = "users, courts, games, game_players, player_stats, player_ratings"


def seed(courts, games):
    db.session.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    db.session.execute(
        text(
            "INSERT INTO users (username, email, password_hash, email_verified) "
            "VALUES ('bench', 'bench@example.invalid', 'x', false)"
        )
    )
    # Scattered across the continental United States.
    db.session.execute(
        text(
            "INSERT INTO courts (name, address, lat, lng, created_by, created_at) "
            "SELECT 'Court ' || g, g || ' Test Street', "
            "       25 + random() * 24, -124 + random() * 57, 1, now() "
            "FROM generate_series(1, :n) g"
        ),
        {"n": courts},
    )
    db.session.execute(
        text(
            "INSERT INTO games (court_id, host_id, time, max_players, created_at) "
            "SELECT (random() * (:c - 1))::int + 1, 1, "
            "       now() + (random() * 30) * interval '1 day', 10, now() "
            "FROM generate_series(1, :n)"
        ),
        {"c": courts, "n": games},
    )
    db.session.execute(text("ANALYZE courts"))
    db.session.execute(text("ANALYZE games"))
    db.session.commit()


def python_loop():
    """What the original implementation did: fetch everything, filter in Python."""
    rows = (
        db.session.query(Game, Court)
        .join(Court, Game.court_id == Court.id)
        .filter(Game.time >= text("now()"))
        .all()
    )
    return sorted(
        game.id
        for game, court in rows
        if haversine_distance(LAT, LNG, court.lat, court.lng) <= RADIUS_KM
    )


def gist_query():
    return sorted(game.id for game, _court, _d in nearby_games(LAT, LNG, RADIUS_KM).all())


def cached_query():
    key = nearby_cache_key(LAT, LNG, RADIUS_KM, None)
    payload = caching.get_or_set(
        key,
        lambda: {"ids": gist_query()},
        ttl=120,
        tags=nearby_cache_tags(LAT, LNG, RADIUS_KM),
    )
    return payload["ids"]


def measure(fn, runs):
    fn()  # warm caches and connection pool
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples)


def explain():
    statement = (
        "EXPLAIN (ANALYZE, BUFFERS) SELECT c.id FROM courts c "
        "WHERE ST_DWithin(c.geog, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :m)"
    )
    return db.session.execute(
        text(statement), {"lat": LAT, "lng": LNG, "m": RADIUS_KM * 1000}
    ).scalars().all()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--courts", type=int, default=25_000)
    parser.add_argument("--games", type=int, default=75_000)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--keep", action="store_true", help="Leave the data in place.")
    args = parser.parse_args()

    app = create_app("testing")
    with app.app_context():
        uri = app.config["SQLALCHEMY_DATABASE_URI"] or ""
        if not uri.rsplit("/", 1)[-1].endswith("_test"):
            sys.exit(f"Refusing to run against a database not named *_test: {uri}")

        print(f"Seeding {args.courts:,} courts and {args.games:,} games…")
        seed(args.courts, args.games)
        caching.clear_all()

        # Correctness before speed.
        baseline = python_loop()
        indexed = gist_query()
        cached = cached_query()
        if len(indexed) >= MAX_RESULTS:
            sys.exit(
                f"The indexed search hit its {MAX_RESULTS}-row cap, so the three "
                f"implementations are no longer answering the same question. Use "
                f"fewer games, or a smaller radius, to compare them."
            )
        if not (baseline == indexed == cached):
            sys.exit(
                f"Implementations disagree: python={len(baseline)} "
                f"gist={len(indexed)} cached={len(cached)} -- aborting."
            )
        print(f"All three return the same {len(baseline)} games.\n")

        loop_ms = measure(python_loop, max(1, args.runs // 2))
        gist_ms = measure(gist_query, args.runs)
        cached_ms = measure(cached_query, args.runs * 4)

        print(f"{'':28} {'median':>10}  {'vs Python':>10}  {'rows to app':>12}")
        print("-" * 66)
        print(f"{'Python Haversine loop':28} {loop_ms:8.1f} ms  {'1x':>10}  {args.games:12,}")
        print(
            f"{'GiST + ST_DWithin':28} {gist_ms:8.1f} ms  "
            f"{loop_ms / gist_ms:9.0f}x  {len(indexed):12,}"
        )
        print(
            f"{'GiST + Redis (cache hit)':28} {cached_ms:8.1f} ms  "
            f"{loop_ms / cached_ms:9.0f}x  {0:12,}"
        )
        print("-" * 66)
        print(f"\nCache: {caching.stats.as_dict()}\n")

        print("Query plan for the indexed search:")
        for line in explain():
            print("  " + line)

        if not args.keep:
            db.session.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            db.session.commit()
            caching.clear_all()
            print("\nBenchmark data removed.")


if __name__ == "__main__":
    main()
