# Pickup Pro

Find pickup basketball games near you, host a run, and track what happened.

Flask, PostgreSQL with PostGIS, and Redis. The parts worth reading are the
geospatial search, the cache invalidation, and the migrations.

## Running it

With Docker.

```bash
cp .env.example .env
# set SECRET_KEY: python -c 'import secrets; print(secrets.token_urlsafe(48))'
docker compose up -d
docker compose exec app flask seed
```

Open http://localhost:8000 and log in as `jordan` with the password
`pickup-demo-password`.

With the app on the host and the services in Docker.

```bash
cp .env.example .env
python -m venv venv && venv/bin/pip install -r requirements.txt -r requirements-dev.txt
docker compose up -d db redis
venv/bin/flask db upgrade && venv/bin/flask seed
venv/bin/python manage.py          # http://127.0.0.1:5000
```

Tests run against real PostgreSQL and Redis rather than SQLite, because the
spatial queries have no SQLite equivalent.

```bash
createdb pickup_pro_test
venv/bin/pytest --cov=app
```

Benchmark the search with `APP_ENV=testing python benchmarks/bench_nearby.py`.

Google sign-in is optional. Without `GOOGLE_CLIENT_ID` the button does not
render and `/auth/google` returns 404.

## Architecture

```
app/
  __init__.py       create_app, extensions, proxy, headers, error handlers
  extensions.py     db, migrate, login, csrf, limiter, cache, oauth
  models.py         User, Court, Game, GamePlayer, PlayerStats, PlayerRating
  forms.py          Flask-WTF forms
  security.py       authorization decorators
  timeutils.py      UTC in storage, APP_TIMEZONE at the edges
  logging.py        structlog, request ids, request timing
  cli.py            flask seed, flask cache-clear
  blueprints/       auth, oauth, courts, games, stats, profiles,
                    leaderboard, api
  services/         geo, caching, geohash, aggregates
  static/           css, js, vendored Leaflet and Chart.js
  templates/        base.html and 10 pages
migrations/         10 revisions, all reversible
tests/              286 tests
benchmarks/         bench_nearby.py
```

Blueprints handle HTTP. They parse input, check authorization, and render.
Services hold the logic worth testing on its own, meaning the spatial query
builder, the cache helper and its tag registry, and the aggregate queries.
Models are the schema. A blueprint can call a service, a service never imports a
blueprint.

| Route | |
|---|---|
| `GET /` `POST /login` `POST /register` `POST /logout` | password auth |
| `GET /auth/google` `GET /auth/callback` | Google OAuth |
| `GET /dashboard` | landing page |
| `GET /courts` `GET,POST /courts/create` | courts and the map |
| `GET /games` `GET,POST /games/create` `GET /games/<id>` | games |
| `POST /games/<id>/join` `/leave` | roster changes |
| `POST /games/<id>/stats` `/rate` | player-reported data |
| `GET /users/<id>` `GET /leaderboard` | profiles and rankings |
| `GET /api/v1/games/nearby` `GET /api/v1/courts` | JSON for the front end |
| `GET /healthz` | liveness, checks the database |

## Stack

Backend. Flask with an application factory and blueprints, SQLAlchemy 2.0,
Alembic through Flask-Migrate, Flask-Login, Authlib for Google OAuth, Flask-WTF,
Flask-Limiter, Flask-Caching, structlog, gunicorn.

Data. PostgreSQL 16 with PostGIS 3.4, Redis 7.

Frontend. Jinja templates and about 460 lines of hand-written CSS with no
framework and no build step. Leaflet and Chart.js are vendored, so the app does
not depend on a CDN.

Infrastructure. Docker Compose for the app, PostGIS, and Redis. A multi-stage
Dockerfile that runs as a non-root user. GitHub Actions runs lint, migrations
up, a drift check, migrations down, the tests, and the benchmark.

## Spatial search

Courts carry a `geography(Point,4326)` column that PostgreSQL generates.

```sql
geog geography(Point,4326)
  GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography) STORED
```

The application never writes it, so it cannot drift from `lat` and `lng`,
whether through the ORM, a bulk `COPY`, or someone in `psql`.

`ST_DWithin` against the GiST index works in two stages, and both show up in the
plan.

```
Bitmap Heap Scan on courts
  Filter: st_dwithin(geog, <point>, 25000, true)          <- exact spheroid refine
  Rows Removed by Filter: 2
  ->  Bitmap Index Scan on ix_courts_geog
        Index Cond: (geog && _st_expand(<point>, 25000))  <- bounding-box prefilter
```

The index gives a bounding box, then PostGIS measures only what survives it.
Writing `ST_Distance(...) <= r` instead would mean the same thing and could not
use the index, because a function result cannot be indexed against a bound
supplied at query time.

Measured at 25,000 courts and 75,000 games with a 25 km radius.

| | median | rows into Python |
|---|---:|---:|
| Python Haversine loop | 2113.5 ms | 75,000 |
| GiST and `ST_DWithin` | 1.7 ms | 9 |
| GiST and a Redis cache hit | 0.3 ms | 0 |

`haversine_distance` is still in the codebase. It is the oracle the spatial
tests check PostGIS against, not the query path.

## Caching

A TTL bounds how stale an entry can get, and guarantees every entry is stale for
up to that long. Host a game and it will not appear in search for two minutes.
Shortening the TTL gives that back but costs the hit rate. So entries expire on
time and are also deleted on write.

```
key   nearby:{geohash}:{radius}:{date}   -> SETEX 120s
tags  geo:{lat_cell}:{lng_cell}          -> deleted when a court, game, or
                                            roster in that area changes
```

Keys are geohashed. Raw coordinates from a browser never repeat, so keying on
them gives a hit rate of roughly zero.

Tags use a plain lat/lng grid rather than geohash neighbours. The risk is
asymmetric. Over-covering costs an extra invalidation, under-covering leaves an
entry that never gets invalidated. Enumerating grid cells over a bounding box is
exact by construction, while walking geohash neighbours is easy to get wrong at
cell edges and the antimeridian.

Invalidation stays narrow. A test checks that creating a court 1,200 km away
leaves an unrelated cached search intact. Profile aggregates are tagged per
user, so a stat write invalidates one player's totals. The court list and the
leaderboard have their own tags.

## Migrations

Ten revisions, and `flask db downgrade base` runs in CI on every push.

`CREATE INDEX CONCURRENTLY` runs inside `op.get_context().autocommit_block()`,
because Alembic wraps migrations in a transaction and `CONCURRENTLY` cannot run
in one. A plain `CREATE INDEX` would block writes to the table for its duration.
A failed concurrent build also leaves an invalid index that the planner ignores
and `IF NOT EXISTS` will not replace, so both index migrations clear that
leftover before rebuilding.

The `timestamptz` conversion passes an explicit `USING col AT TIME ZONE 'UTC'`.
Without it PostgreSQL assumes the server's zone, and the result depends on where
the migration ran.

One migration rewrites fabricated `{username}@example.com` addresses to the
reserved `.invalid` TLD. One downgrade refuses to run if any account
authenticates only through OAuth, rather than leaving rows nobody can log into.
A `plpgsql` trigger enforces roster capacity, which a `CHECK` constraint cannot
do because it cannot count sibling rows.

`flask db check` runs in CI, so the models and the migrations cannot silently
diverge.

## Security

Authorization lives in decorators, because being on a game's roster is not
permission to write data about other people on it.

```python
@bp.route("/<int:game_id>/stats", methods=["POST"])
@login_required
@require_roster                       # the caller is on this roster
@require_target_on_roster("user_id")  # so is the player being written about
def submit_stats(game_id): ...
```

`CSRFProtect` is applied app-wide rather than per form. Sessions are `HttpOnly`
and `SameSite=Lax`, `Secure` in production, and cleared and rotated on login.
Production refuses to boot on a placeholder `SECRET_KEY`. Rate limiting is
Redis-backed so it counts correctly across workers. `ProxyFix` trusts exactly as
many forwarded hops as are configured. Roster joins are serialized with
`SELECT ... FOR UPDATE` behind the capacity trigger.

The Content-Security-Policy sets no `unsafe-inline` for scripts or styles, so no
template can hold an executable inline `<script>`, a `style` attribute, or an
`onclick`. The modals read `data-*` attributes through a delegated listener, and
chart data sits in a `<script type="application/json">` block. A test walks
every template and fails on a reintroduced attribute.
