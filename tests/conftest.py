"""Shared test fixtures.

Tests run against a real PostgreSQL database rather than SQLite. The queries
this project exists to demonstrate are PostgreSQL-specific, so testing against a
different engine would test something other than what ships.

The schema is built by running the Alembic migrations, not db.create_all(), so
every test run also proves the migration chain still applies cleanly.
"""

import os

import pytest
from flask_migrate import upgrade as alembic_upgrade
from sqlalchemy import text

from app import create_app
from app.extensions import db as _db
from app.models import Court, Game, GamePlayer, User


@pytest.fixture(scope="session")
def app():
    application = create_app("testing")

    uri = application.config["SQLALCHEMY_DATABASE_URI"]
    if not uri:
        pytest.skip("TEST_DATABASE_URL / DATABASE_URL is not configured")
    # Guard against a fat-fingered env var pointing tests at real data: the
    # fixtures below drop every table.
    if not uri.rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail(f"Refusing to run tests against a database not named *_test: {uri!r}")

    with application.app_context():
        _db.drop_all()
        _db.session.execute(text("DROP TABLE IF EXISTS alembic_version"))
        _db.session.commit()
        alembic_upgrade()
        yield application
        _db.session.remove()


@pytest.fixture()
def db(app):
    """Wrap each test in a transaction that is rolled back afterwards.

    Faster than recreating the schema per test, and guarantees isolation even
    when a test commits.
    """
    with app.app_context():
        connection = _db.engine.connect()
        transaction = connection.begin()
        _db.session.remove()
        _db.session.configure(bind=connection, join_transaction_mode="create_savepoint")

        yield _db

        _db.session.remove()
        transaction.rollback()
        connection.close()
        _db.session.configure(bind=_db.engine)


@pytest.fixture()
def client(app, db):
    return app.test_client()


@pytest.fixture()
def user_factory(db):
    """Create persisted users with predictable credentials."""
    created = []

    def _make(username=None, password="correct-horse-battery", **kwargs):
        username = username or f"player{len(created) + 1}"
        email = kwargs.pop("email", f"{username}@example.test")
        user = User(username=username, email=email, **kwargs)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        created.append(user)
        return user

    return _make


@pytest.fixture()
def court_factory(db, user_factory):
    def _make(name="Test Court", lat=33.9519, lng=-83.3576, created_by=None, **kwargs):
        court = Court(
            name=name,
            address=kwargs.pop("address", "1 Test Street"),
            lat=lat,
            lng=lng,
            created_by=created_by or user_factory().id,
            **kwargs,
        )
        db.session.add(court)
        db.session.flush()
        return court

    return _make


@pytest.fixture()
def game_factory(db, court_factory, user_factory):
    from datetime import datetime, timedelta

    def _make(court=None, host=None, when=None, max_players=10, players=()):
        host = host or user_factory()
        court = court or court_factory(created_by=host.id)
        game = Game(
            court_id=court.id,
            host_id=host.id,
            time=when or datetime.now() + timedelta(days=1),
            max_players=max_players,
        )
        db.session.add(game)
        db.session.flush()
        for player in players:
            db.session.add(GamePlayer(game_id=game.id, user_id=player.id))
        db.session.flush()
        return game

    return _make


@pytest.fixture()
def login(client):
    """Authenticate the test client as the given user."""

    def _login(user):
        with client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True
        return client

    return _login


@pytest.fixture(autouse=True)
def _quiet_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    os.environ.setdefault("APP_ENV", "testing")
