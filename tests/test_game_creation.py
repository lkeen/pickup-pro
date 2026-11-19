"""Hosting a game through the form, as a signed-in user does it.

The bug these pin: a host in New York, with APP_TIMEZONE left at UTC, entered a
start one hour ahead of them. The server read that wall-clock time as UTC, which
put the game hours in the past. It was stored, the host was told "Game created
successfully!", and the redirect landed on a listing that only shows games from
now on. Nothing anywhere showed the game, so it looked like creation did nothing.

These go through the rendered form with CSRF enforced, the same path a browser
takes, rather than posting straight at the model.
"""

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import Game
from tests.conftest import csrf_token_from


@pytest.fixture()
def host_client(csrf_client, user_factory):
    """A browser-like client, signed in through the real login form."""
    user = user_factory(username="host", password="long-enough-pw")
    token = csrf_token_from(csrf_client.get("/").get_data(as_text=True))
    response = csrf_client.post(
        "/login",
        data={"username": "host", "password": "long-enough-pw", "csrf_token": token},
    )
    assert response.status_code == 302
    csrf_client.user = user
    return csrf_client


def submit_game_form(client, court, wall_clock):
    """Load the create page and submit its form, as a browser would."""
    page = client.get("/games/create")
    assert page.status_code == 200
    return client.post(
        "/games/create",
        data={
            "csrf_token": csrf_token_from(page.get_data(as_text=True)),
            "court_id": str(court.id),
            "time": wall_clock.strftime("%Y-%m-%dT%H:%M"),
            "max_players": "10",
        },
    )


def wall_clock_in(zone, offset):
    """What a person in ``zone`` would type for ``offset`` from now."""
    return (datetime.now(UTC) + offset).astimezone(ZoneInfo(zone)).replace(tzinfo=None)


@pytest.mark.parametrize("app_timezone", ["UTC", "America/New_York", "Asia/Tokyo"])
def test_a_hosted_game_shows_up_where_the_host_looks(
    app, db, monkeypatch, host_client, court_factory, app_timezone
):
    monkeypatch.setitem(app.config, "APP_TIMEZONE", app_timezone)
    court = court_factory(name="Legion Field", created_by=host_client.user.id)

    response = submit_game_form(host_client, court, wall_clock_in(app_timezone, timedelta(hours=1)))

    assert response.status_code == 302
    game = db.session.query(Game).one()
    assert game.host_id == host_client.user.id
    # The redirect goes to the game itself, which shows it whatever the
    # listing's filters and pagination would do.
    assert response.headers["Location"].endswith(f"/games/{game.id}")
    detail = host_client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Game created successfully!" in detail
    assert "Legion Field" in detail

    link = f'href="/games/{game.id}"'
    assert link in host_client.get("/games").get_data(as_text=True)
    assert link in host_client.get(f"/games?court_id={court.id}").get_data(as_text=True)


def test_a_time_ahead_for_the_host_but_past_in_app_timezone_is_rejected_with_a_reason(
    app, db, monkeypatch, host_client, court_factory
):
    """The reported case. An hour ahead in New York is several hours ago in
    UTC, so it is never a valid start when the app runs in UTC."""
    monkeypatch.setitem(app.config, "APP_TIMEZONE", "UTC")
    court = court_factory(created_by=host_client.user.id)
    typed = wall_clock_in("America/New_York", timedelta(hours=1))

    response = submit_game_form(host_client, court, typed)

    assert response.status_code == 200
    assert db.session.query(Game).count() == 0
    body = response.get_data(as_text=True)
    error = re.search(r'<span class="field-error">([^<]*)</span>', body)
    assert error, "the form came back without saying what was wrong"
    assert "Pick a time in the future" in error.group(1)
    assert "Times are in UTC" in error.group(1)
    # What the host typed is still there to correct, not cleared.
    assert f'value="{typed:%Y-%m-%dT%H:%M}"' in body


def test_a_start_that_has_already_passed_is_rejected(
    app, db, monkeypatch, host_client, court_factory
):
    monkeypatch.setitem(app.config, "APP_TIMEZONE", "America/New_York")
    court = court_factory(created_by=host_client.user.id)

    response = submit_game_form(
        host_client, court, wall_clock_in("America/New_York", -timedelta(minutes=5))
    )

    assert response.status_code == 200
    assert "Times are in America/New_York" in response.get_data(as_text=True)
    assert db.session.query(Game).count() == 0
