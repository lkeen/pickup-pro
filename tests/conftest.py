"""Shared test fixtures.

Tests run against a real PostgreSQL database rather than SQLite. The queries
this project exists to demonstrate are PostgreSQL-specific, so testing against a
different engine would test something other than what ships.

The schema is built by running the Alembic migrations, not db.create_all(), so
every test run also proves the migration chain still applies cleanly.
"""

import os
import re

import pytest
from flask_migrate import upgrade as alembic_upgrade
from sqlalchemy import text

from app import create_app
from app.extensions import db as _db
from app.models import Court, Game, GamePlayer, User

DEFAULT_PASSWORD = "correct-horse-battery"


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

    # Storage is configured, but the limiter is off unless a test asks for it.
    from app.extensions import limiter

    limiter.enabled = False

    with application.app_context():
        _db.drop_all()
        _db.session.execute(text("DROP TABLE IF EXISTS alembic_version"))
        _db.session.commit()
        alembic_upgrade()
        yield application
        _db.session.remove()


def _truncate_all_tables():
    """Empty every model table, resetting identity sequences."""
    tables = ", ".join(f'"{table.name}"' for table in _db.metadata.sorted_tables)
    if not tables:
        return
    _db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    _db.session.commit()


@pytest.fixture()
def db(app):
    """Give each test an empty database.

    The obvious approach -- wrap the test in a transaction and roll it back --
    does not work here. Flask-SQLAlchemy 3.1 scopes its session to the app
    context, so the session inside a test-client request is a *different*
    session on a *different* connection from the one the fixture set up. Any
    commit made by a view would escape the fixture's transaction and leak into
    the next test, which is exactly what happened: rows survived the rollback
    and later tests failed on duplicate usernames.

    Truncating afterwards is less clever but actually isolates. It also means
    fixtures must commit rather than flush, since the data has to be visible to
    a request running on another connection.
    """
    with app.app_context():
        _truncate_all_tables()
        yield _db
        _db.session.rollback()
        _truncate_all_tables()
        _db.session.remove()


@pytest.fixture()
def client(app, db):
    return app.test_client()


@pytest.fixture()
def user_factory(db):
    """Create persisted users with predictable credentials."""
    created = []

    def _make(username=None, password=DEFAULT_PASSWORD, **kwargs):
        username = username or f"player{len(created) + 1}"
        email = kwargs.pop("email", f"{username}@example.test")
        user = User(username=username, email=email, **kwargs)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        # Not a column: the login fixture needs the plaintext to authenticate
        # through the real endpoint.
        user._test_password = password
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
        db.session.commit()
        return court

    return _make


@pytest.fixture()
def game_factory(db, court_factory, user_factory):
    from datetime import timedelta

    from app.timeutils import utcnow

    def _make(court=None, host=None, when=None, max_players=10, players=()):
        host = host or user_factory()
        court = court or court_factory(created_by=host.id)
        game = Game(
            court_id=court.id,
            host_id=host.id,
            time=when or utcnow() + timedelta(days=1),
            max_players=max_players,
        )
        db.session.add(game)
        db.session.commit()
        for player in players:
            db.session.add(GamePlayer(game_id=game.id, user_id=player.id))
        db.session.commit()
        return game

    return _make


@pytest.fixture()
def csrf_client(app, db):
    """A client with CSRF enforcement switched on.

    TestingConfig disables CSRF so the rest of the suite can exercise
    application logic without threading tokens through every request. These
    tests are specifically about the tokens, so they turn it back on.
    """
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        yield app.test_client()
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def csrf_token_from(html):
    """Pull the CSRF token out of a rendered page."""
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match, "no csrf_token field found in the rendered page"
    return match.group(1)


@pytest.fixture()
def query_counter(app):
    """Count SELECT statements issued during a block.

    Used to pin N+1 behaviour: the assertion that matters is that the count does
    not grow with the number of rows, not that it equals any particular number.
    """
    from sqlalchemy import event

    class Counter:
        def __init__(self):
            self.count = 0

        def reset(self):
            self.count = 0

    counter = Counter()

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            counter.count += 1

    with app.app_context():
        engine = _db.engine
    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)


@pytest.fixture()
def login(client):
    """Authenticate the test client by actually logging in.

    Writing _user_id into the session directly is tempting and does not work:
    Flask-Login runs with session_protection="strong", which drops any session
    whose client-identifier hash it did not set itself. Going through the real
    endpoint also means these tests exercise the login path rather than a
    fixture's impression of it.
    """

    def _login(user):
        response = client.post(
            "/login",
            data={
                "username": user.username,
                "password": getattr(user, "_test_password", DEFAULT_PASSWORD),
            },
        )
        assert response.status_code == 302, "login fixture failed to authenticate"
        return client

    return _login


@pytest.fixture(autouse=True)
def _quiet_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    os.environ.setdefault("APP_ENV", "testing")
