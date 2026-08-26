# 🏀 Pickup Pro

Find pickup basketball near you, host a run, and keep the stats.

A Flask application built around three problems worth solving properly: **spatial
search that uses an index**, **a cache that invalidates instead of just
expiring**, and **schema migrations that survive being reversed**.

```
docker compose up -d          # Postgres + PostGIS, Redis, the app
docker compose exec app flask seed
open http://localhost:8000    # log in as `jordan` / `pickup-demo-password`
```

---

## What's interesting here

### 1. Spatial search: GiST-indexed bounding box, then exact refine

Courts carry a `geography(Point,4326)` column. It is **generated**, not
maintained by the application:

```sql
geog geography(Point,4326)
  GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography) STORED
```

The application never writes it, so it cannot drift out of sync with `lat`/`lng`
— not through the ORM, not through a bulk `COPY`, not through someone in `psql`.
A direct `UPDATE` is rejected by PostgreSQL.

The search is `ST_DWithin` against a GiST index, which is a two-stage operation.
Both stages show up in the plan:

```
Bitmap Heap Scan on courts
  Filter: st_dwithin(geog, <point>, 25000, true)          <- exact spheroid refine
  Rows Removed by Filter: 2
  ->  Bitmap Index Scan on ix_courts_geog
        Index Cond: (geog && _st_expand(<point>, 25000))  <- bounding-box prefilter
```

25,000 courts reduce to 5 bounding-box candidates, of which 3 survive the exact
distance. Nothing that fails the box is ever measured.

Written as `ST_DWithin(geog, point, metres)` deliberately: `ST_Distance(...) <= r`
means the same thing and **cannot** use the index, because a function result
cannot be indexed against a bound supplied at query time.

`haversine_distance()` is still in the codebase. It is no longer the query
engine — it is the independent oracle the database is tested against. Two
implementations that agree is much better evidence than one that looks right.

**Reproduce it:** `APP_ENV=testing python benchmarks/bench_nearby.py`

| | median | rows into Python |
|---|---:|---:|
| Python Haversine loop (the original) | 2113.5 ms | 75,000 |
| GiST + `ST_DWithin` | **1.7 ms** | 9 |
| GiST + Redis cache hit | **0.3 ms** | 0 |

The benchmark asserts all three return the same games before reporting any
timing. A fast wrong answer is not an optimisation.

### 2. Caching: cache-aside with explicit invalidation

A TTL is the easy half. It bounds how stale an entry can get — and guarantees
every entry *is* stale for up to that long. Host a game, then fail to find it in
search for two minutes. Shortening the TTL to fix that throws away the hit rate
the cache existed for.

So entries expire on time **and** are deleted on write:

```
key   nearby:{geohash}:{radius}:{date}      → SETEX 120s
tags  geo:{lat_cell}:{lng_cell}             → deleted when a court, game or
                                               roster in that area changes
```

Three details that make it work:

- **Keys are geohashed.** Coordinates from a browser's geolocation never repeat,
  so keying on them gives a hit rate of roughly zero — a cache that stores
  everything and returns nothing.
- **Tags are a lat/lng grid, not geohash neighbours.** The risk is asymmetric:
  over-covering costs one extra invalidation, under-covering leaves an entry
  that never gets invalidated. Enumerating grid cells over a bounding box is
  obviously exact; walking geohash neighbours is easy to get subtly wrong at
  cell edges and the antimeridian.
- **Invalidation is targeted.** A test asserts that creating a court 1,200 km
  away leaves an unrelated cached search intact. A cache that empties itself on
  every write is not a cache.

Also cached, each with a different invalidation story: profile aggregates
(tagged per user), the court list (rarely changes, boring, correct), and the
leaderboard.

### 3. Migrations that reverse

Ten migrations, and `flask db downgrade base` runs in CI on every push.

- **`CREATE INDEX CONCURRENTLY`** inside `op.get_context().autocommit_block()` —
  Alembic wraps migrations in a transaction, and `CONCURRENTLY` cannot run in
  one. The point is the lock: a plain `CREATE INDEX` blocks every write to the
  table until it finishes.
- **A data migration** rewriting fabricated `{username}@example.com` addresses
  to `.invalid`, which RFC 2606 reserves and which can never resolve.
- **`timestamptz` conversion** with an explicit `USING col AT TIME ZONE 'UTC'`.
  Without `USING`, PostgreSQL assumes the *server's* timezone, so the result
  depends on where the migration happened to run.
- **A downgrade that refuses to run** if any account authenticates only through
  OAuth, rather than silently producing rows nobody can log into.
- **A `plpgsql` trigger** enforcing roster capacity — a `CHECK` constraint cannot
  count sibling rows.

The first migration this project shipped could not be reversed at all:
`create_foreign_key(None, ...)` then `drop_constraint(None, ...)`, which Alembic
cannot compile. CI would have caught it on day one.

---

## Bugs this fixed

Every one of these was in the repository, and each has a regression test.

| | |
|---|---|
| **Broken access control** | Any rostered player could write stats for, or rate, *any user in the database* — `user_id` came straight from a hidden form field and only the caller was checked against the roster. |
| **No CSRF anywhere** | `POST /login` with no token returned `200`. `/logout` was a `GET`, firable from `<img src="/logout">`. |
| **Guessable signing key** | `SECRET_KEY` resolved to the literal `your-secret-key-here`. |
| **Null Island rejected** | `if not lat or not lng` rejected `lat=0`/`lng=0` — the equator and the prime meridian. |
| **Roster race** | Check-then-act on join. Two threads racing for the last slot put **3 players in a 2-player game**; reproduced, then fixed with `SELECT … FOR UPDATE` plus a trigger. |
| **7 unindexed foreign keys** | PostgreSQL indexes primary keys and unique constraints, not foreign keys. |
| **N+1 on the game listing** | 20 games cost 25 queries. Now 4. |
| **Naive timestamps** | Every column `TIMESTAMP WITHOUT TIME ZONE`, written with `datetime.now()` — local time, from a zone nobody recorded. |
| **XSS-adjacent escaping** | Usernames and comments interpolated into `onclick="..."`. Jinja escapes for HTML, not for JavaScript string context. |
| **`requirements.txt` was UTF-16** | `pip install -r` could not parse it. It also pinned `PyMySQL` for a PostgreSQL project. |

---

## Stack

**Backend** — Flask (application factory, blueprints), SQLAlchemy 2.0,
Alembic via Flask-Migrate, Flask-Login + Authlib (Google OAuth), Flask-WTF,
Flask-Limiter, gunicorn.

**Data** — PostgreSQL 16 + PostGIS 3.4, Redis 7.

**Frontend** — Jinja templates, a hand-written design system (~400 lines of CSS,
no framework, no build step), Leaflet, Chart.js. Both libraries are vendored, so
the app works offline and depends on no CDN staying up.

**Testing** — 250+ pytest tests against real PostgreSQL and Redis. Not SQLite:
the queries this project exists to demonstrate have no SQLite equivalent.
GitHub Actions runs lint, migrations up, drift check, migrations *down*, then
the suite.

```
app/
  blueprints/   auth · oauth · courts · games · stats · profiles · leaderboard · api
  services/     geo (spatial) · caching · geohash · aggregates
  security.py   @require_roster · @require_target_on_roster · @forbid_self
  static/       css/main.css · js/ · vendor/
benchmarks/     bench_nearby.py
migrations/     10 revisions, all reversible
```

---

## Running it

**Docker (everything):**

```bash
cp .env.example .env
# set SECRET_KEY: python -c 'import secrets; print(secrets.token_urlsafe(48))'
docker compose up -d
docker compose exec app flask seed
```

**Locally (app on the host, services in Docker):**

```bash
cp .env.example .env
python -m venv venv && venv/bin/pip install -r requirements.txt -r requirements-dev.txt
docker compose up -d db redis
venv/bin/flask db upgrade && venv/bin/flask seed
venv/bin/python manage.py
```

**Tests:**

```bash
createdb pickup_pro_test
venv/bin/pytest --cov=app
```

Google sign-in is optional. Without `GOOGLE_CLIENT_ID` the button does not
render and `/auth/google` returns 404.

---

## Known limitations

Stated rather than hidden.

- **One timezone for the whole app.** A game's start is wall-clock at the court;
  per-court zones are derivable from the coordinates PostGIS already holds, but
  `APP_TIMEZONE` is the honest simplification for an app serving one metro area.
- **No account linking.** If a Google address already belongs to a password
  account, sign-in is refused with an explanation rather than guessed at. Doing
  it properly means handling unverified-email hijacking and
  unlink-last-credential.
- **Geohash key quantisation moves the search centre** by up to a few tens of
  metres. That is the trade for a cache that hits.
- **Email addresses are unverified** for password sign-ups; `email_verified` is
  only ever true for an address an identity provider vouched for.
- **Not deployed.** `fly.toml` and the steps are in the repository; running them
  needs an account.
