# 🏀 Pickup Pro

Find pickup basketball games near you, host a run, and track what happened.

A Flask application over PostgreSQL + PostGIS and Redis: geospatial search on a
GiST index, a cache that invalidates on write rather than only on a timer, and
reversible Alembic migrations.

---

## Running it

**Docker — everything:**

```bash
cp .env.example .env
# set SECRET_KEY: python -c 'import secrets; print(secrets.token_urlsafe(48))'
docker compose up -d
docker compose exec app flask seed
```

Then <http://localhost:8000>, logging in as `jordan` / `pickup-demo-password`.

**Locally — app on the host, services in Docker:**

```bash
cp .env.example .env
python -m venv venv && venv/bin/pip install -r requirements.txt -r requirements-dev.txt
docker compose up -d db redis
venv/bin/flask db upgrade && venv/bin/flask seed
venv/bin/python manage.py          # http://127.0.0.1:5000
```

**Tests** (real PostgreSQL and Redis, not SQLite — the spatial queries have no
SQLite equivalent):

```bash
createdb pickup_pro_test
venv/bin/pytest --cov=app
```

**Benchmark:** `APP_ENV=testing python benchmarks/bench_nearby.py`

Google sign-in is optional. Without `GOOGLE_CLIENT_ID` the button does not
render and `/auth/google` returns 404.

---

## Architecture

```
app/
  __init__.py       create_app() — config, extensions, proxy, headers, errors
  extensions.py     db · migrate · login · csrf · limiter · cache · oauth
  models.py         User · Court · Game · GamePlayer · PlayerStats · PlayerRating
  forms.py          Flask-WTF — CSRF tokens and input validation
  security.py       @require_roster · @require_target_on_roster · @forbid_self
  timeutils.py      UTC in storage, APP_TIMEZONE at the edges
  logging.py        structlog, request ids, request timing
  cli.py            flask seed · flask cache-clear
  blueprints/       auth · oauth · courts · games · stats · profiles
                    leaderboard · api
  services/         geo (spatial) · caching · geohash · aggregates
  static/           css/main.css · js/ · vendor/ (Leaflet, Chart.js)
  templates/        base.html + 10 pages
migrations/         10 revisions, all reversible
tests/              286 tests
benchmarks/         bench_nearby.py
```

Three layers, in one direction. **Blueprints** handle HTTP: parse, authorize,
render, redirect. **Services** hold the logic worth testing on its own — the
spatial query builder, the cache-aside helper and its tag registry, the
aggregate queries. **Models** are the schema. A blueprint may call a service; a
service never imports a blueprint.

| | |
|---|---|
| `GET /` `POST /login` `POST /register` `POST /logout` | password auth |
| `GET /auth/google` `GET /auth/callback` | Google OAuth |
| `GET /dashboard` | landing page |
| `GET /courts` `GET,POST /courts/create` | courts, with the Leaflet map |
| `GET /games` `GET,POST /games/create` `GET /games/<id>` | games |
| `POST /games/<id>/join` `/leave` | roster, locked and capacity-checked |
| `POST /games/<id>/stats` `/rate` | player-reported data |
| `GET /users/<id>` `GET /leaderboard` | profiles and rankings |
| `GET /api/v1/games/nearby` `GET /api/v1/courts` | JSON for the front end |
| `GET /healthz` | liveness, checks the database |

A request runs `ProxyFix` → CSRF → `@login_required` → authorization decorator
→ form validation → service → PostgreSQL/Redis, and picks up the security
headers and a timing log line on the way back out.

---

## Stack

**Backend** — Flask (application factory, blueprints), SQLAlchemy 2.0, Alembic
via Flask-Migrate, Flask-Login + Authlib (Google OAuth), Flask-WTF,
Flask-Limiter, Flask-Caching, structlog, gunicorn.

**Data** — PostgreSQL 16 + PostGIS 3.4, Redis 7.

**Frontend** — Jinja templates, a hand-written design system (~460 lines of CSS,
no framework, no build step), Leaflet, Chart.js. Both libraries are vendored, so
the app depends on no CDN staying up.

**Infrastructure** — Docker Compose (app, PostGIS, Redis), multi-stage
Dockerfile running as a non-root user, GitHub Actions (lint → migrations up →
drift check → migrations down → tests → benchmark), `fly.toml` for deployment.

---

## Worth a closer look

### Spatial search on a GiST index

Courts carry a `geography(Point,4326)` column that PostgreSQL **generates**:

```sql
geog geography(Point,4326)
  GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography) STORED
```

The application never writes it, so it cannot drift from `lat`/`lng` — not
through the ORM, not through a bulk `COPY`, not through someone in `psql`.

`ST_DWithin` against the GiST index is a two-stage operation, and both stages
appear in the plan:

```
Bitmap Heap Scan on courts
  Filter: st_dwithin(geog, <point>, 25000, true)          <- exact spheroid refine
  Rows Removed by Filter: 2
  ->  Bitmap Index Scan on ix_courts_geog
        Index Cond: (geog && _st_expand(<point>, 25000))  <- bounding-box prefilter
```

Nothing that fails the bounding box is ever measured. Written as
`ST_DWithin(geog, point, metres)` deliberately: `ST_Distance(...) <= r` means the
same thing and **cannot** use the index, because a function result cannot be
indexed against a bound supplied at query time.

Measured at 25,000 courts and 75,000 games, 25 km radius:

| | median | rows into Python |
|---|---:|---:|
| Python Haversine loop (the original) | 2113.5 ms | 75,000 |
| GiST + `ST_DWithin` | **1.7 ms** | 9 |
| GiST + Redis cache hit | **0.3 ms** | 0 |

`haversine_distance()` remains in the codebase as the independent oracle the
database is tested against, rather than as the query engine.

### A cache that invalidates, not just expires

A TTL bounds how stale an entry can get and guarantees every entry *is* stale
for up to that long — host a game, then fail to find it in search for two
minutes. Shortening the TTL throws away the hit rate. So entries expire on time
**and** are deleted on write:

```
key   nearby:{geohash}:{radius}:{date}   → SETEX 120s
tags  geo:{lat_cell}:{lng_cell}          → deleted when a court, game or
                                           roster in that area changes
```

- **Keys are geohashed.** Raw coordinates from a browser's geolocation never
  repeat, so keying on them gives a hit rate of roughly zero.
- **Tags are a lat/lng grid, not geohash neighbours.** The risk is asymmetric:
  over-covering costs one extra invalidation, under-covering leaves an entry
  that never gets invalidated. Enumerating grid cells over a bounding box is
  exact by construction; walking geohash neighbours is easy to get wrong at
  cell edges and the antimeridian.
- **Invalidation is targeted.** A test asserts that creating a court 1,200 km
  away leaves an unrelated cached search intact.

Profile aggregates are tagged per user, so a stat write invalidates exactly that
player's totals; the court list and leaderboard carry their own tags.

### Migrations that reverse

Ten revisions, and `flask db downgrade base` runs in CI on every push.

- **`CREATE INDEX CONCURRENTLY`** inside `op.get_context().autocommit_block()` —
  Alembic wraps migrations in a transaction and `CONCURRENTLY` cannot run in
  one. A plain `CREATE INDEX` would block every write to the table meanwhile.
  A failed concurrent build also leaves an *invalid* index that the planner
  ignores and `IF NOT EXISTS` will not replace, so both index migrations clear
  that leftover before rebuilding.
- **`timestamptz` conversion** with an explicit `USING col AT TIME ZONE 'UTC'`.
  Without `USING`, PostgreSQL assumes the *server's* zone and the result depends
  on where the migration ran.
- **A data migration** rewriting fabricated `{username}@example.com` addresses
  to the reserved `.invalid` TLD.
- **A downgrade that refuses to run** if any account authenticates only through
  OAuth, rather than leaving rows nobody can log into.
- **A `plpgsql` trigger** enforcing roster capacity, which a `CHECK` constraint
  cannot do because it cannot count sibling rows.

`flask db check` also runs in CI, so the models and migrations cannot silently
diverge.

### Security

Authorization lives in decorators, because membership of a game's roster is not
permission to write data about *other* people on it:

```python
@bp.route("/<int:game_id>/stats", methods=["POST"])
@login_required
@require_roster                       # the caller is on this roster
@require_target_on_roster("user_id")  # so is the player being written about
def submit_stats(game_id): ...
```

Beyond that: `CSRFProtect` app-wide rather than per-form; sessions `HttpOnly`,
`SameSite=Lax`, `Secure` in production, cleared and rotated on login; a
`SECRET_KEY` production refuses to boot without; Redis-backed rate limiting so
it counts correctly across workers; `ProxyFix` for exactly as many forwarded
hops as are configured; roster joins serialized with `SELECT … FOR UPDATE`
behind a database trigger.

The Content-Security-Policy carries no `unsafe-inline` for scripts *or* styles,
so no template may hold an executable inline `<script>`, a `style` attribute or
an `onclick`: the modals read `data-*` attributes through a delegated listener,
and chart data rides in a `<script type="application/json">` data block. A test
walks every template and fails on a reintroduced attribute.
