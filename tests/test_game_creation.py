"""Hosting a game through the form, as a signed-in user does it.

The bug these pin: a host in New York, with APP_TIMEZONE left at UTC, entered a
start one hour ahead of them. The server read that wall-clock time as UTC, which
put the game hours in the past. It was stored, the host was told "Game created
successfully!", and the redirect landed on a listing that only shows games from
now on. Nothing anywhere showed the game, so it looked like creation did nothing.

The time is now read in the zone the browser reports with the form, and pages
render times in the zone it reports in its cookie. APP_TIMEZONE is only the
fallback.

These go through the rendered form with CSRF enforced, the same path a browser
takes, rather than posting straight at the model.
"""

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import Game
from app.timeutils import TIMEZONE_COOKIE, resolve_timezone
from tests.conftest import csrf_token_from

NEW_YORK = "America/New_York"


@pytest.fixture()
def utc_server(app, monkeypatch):
    """The configuration the bug was reported under."""
    monkeypatch.setitem(app.config, "APP_TIMEZONE", "UTC")


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


def submit_game_form(client, court, wall_clock, browser_timezone=None):
    """Load the create page and submit its form, as a browser would.

    ``browser_timezone`` is what static/js/timezone.js puts in the hidden
    field; None is a browser that never ran it.
    """
    page = client.get("/games/create").get_data(as_text=True)
    assert 'name="timezone"' in page and "data-browser-timezone" in page
    data = {
        "csrf_token": csrf_token_from(page),
        "court_id": str(court.id),
        "time": wall_clock.strftime("%Y-%m-%dT%H:%M"),
        "max_players": "10",
    }
    if browser_timezone is not None:
        data["timezone"] = browser_timezone
    return client.post("/games/create", data=data)


def wall_clock_in(zone, offset):
    """What a person in ``zone`` would type for ``offset`` from now, to the minute."""
    local = (datetime.now(UTC) + offset).astimezone(ZoneInfo(zone))
    return local.replace(tzinfo=None, second=0, microsecond=0)


def field_error(body):
    match = re.search(r'<span class="field-error">([^<]*)</span>', body)
    assert match, "the form came back without saying what was wrong"
    return match.group(1)


def test_the_reported_case_creates_and_lists_the_game(db, utc_server, host_client, court_factory):
    """A New York browser, a UTC server, a start one hour ahead."""
    court = court_factory(name="Legion Field", created_by=host_client.user.id)
    typed = wall_clock_in(NEW_YORK, timedelta(hours=1))

    response = submit_game_form(host_client, court, typed, browser_timezone=NEW_YORK)

    assert response.status_code == 302
    game = db.session.query(Game).one()
    assert game.host_id == host_client.user.id
    assert game.time == typed.replace(tzinfo=ZoneInfo(NEW_YORK)).astimezone(UTC)

    # The redirect goes to the game itself, which shows it whatever the
    # listing's filters and pagination would do.
    assert response.headers["Location"].endswith(f"/games/{game.id}")
    host_client.set_cookie(TIMEZONE_COOKIE, NEW_YORK)
    detail = host_client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Game created successfully!" in detail
    assert "Legion Field" in detail
    # Shown back as the host typed it, in the host's zone.
    shown = typed.replace(tzinfo=ZoneInfo(NEW_YORK))
    assert f"{shown:%a %d %b, %H:%M %Z}" in detail

    link = f'href="/games/{game.id}"'
    assert link in host_client.get("/games").get_data(as_text=True)
    assert link in host_client.get(f"/games?court_id={court.id}").get_data(as_text=True)
    day = f"{typed:%Y-%m-%d}"
    assert link in host_client.get(f"/games?date={day}").get_data(as_text=True)


@pytest.mark.parametrize("browser_timezone", ["UTC", NEW_YORK, "Asia/Tokyo", "Pacific/Kiritimati"])
def test_a_time_an_hour_ahead_is_accepted_in_any_browser_zone(
    db, utc_server, host_client, court_factory, browser_timezone
):
    court = court_factory(created_by=host_client.user.id)
    typed = wall_clock_in(browser_timezone, timedelta(hours=1))

    response = submit_game_form(host_client, court, typed, browser_timezone=browser_timezone)

    assert response.status_code == 302
    game = db.session.query(Game).one()
    assert game.time == typed.replace(tzinfo=ZoneInfo(browser_timezone)).astimezone(UTC)


def test_a_start_that_has_already_passed_for_the_host_is_rejected_with_a_reason(
    db, utc_server, host_client, court_factory
):
    court = court_factory(created_by=host_client.user.id)
    typed = wall_clock_in(NEW_YORK, -timedelta(minutes=5))

    response = submit_game_form(host_client, court, typed, browser_timezone=NEW_YORK)

    assert response.status_code == 200
    assert db.session.query(Game).count() == 0
    body = response.get_data(as_text=True)
    error = field_error(body)
    assert "Pick a time in the future" in error
    assert f"Times are in {NEW_YORK}" in error
    # What the host typed is still there to correct, not cleared.
    assert f'value="{typed:%Y-%m-%dT%H:%M}"' in body


@pytest.mark.parametrize("browser_timezone", [None, "", "Mars/Olympus_Mons", "../../etc/passwd"])
def test_without_a_usable_browser_zone_the_time_is_read_in_app_timezone(
    db, utc_server, host_client, court_factory, browser_timezone
):
    """An hour ahead in New York is hours ago in UTC, so read in the fallback
    zone it is a past start, and the message says which zone was used."""
    court = court_factory(created_by=host_client.user.id)
    typed = wall_clock_in(NEW_YORK, timedelta(hours=1))

    response = submit_game_form(host_client, court, typed, browser_timezone=browser_timezone)

    assert response.status_code == 200
    assert db.session.query(Game).count() == 0
    assert "Times are in UTC" in field_error(response.get_data(as_text=True))


def test_times_are_labelled_with_app_timezone_until_the_browser_reports_its_own(
    db, utc_server, host_client, court_factory, game_factory
):
    court = court_factory(created_by=host_client.user.id)
    game = game_factory(
        court=court, host=host_client.user, when=datetime(2099, 7, 4, 22, 0, tzinfo=UTC)
    )

    assert "Sat 04 Jul, 22:00 UTC" in host_client.get(f"/games/{game.id}").get_data(as_text=True)

    host_client.set_cookie(TIMEZONE_COOKIE, NEW_YORK)
    assert "Sat 04 Jul, 18:00 EDT" in host_client.get(f"/games/{game.id}").get_data(as_text=True)

    host_client.set_cookie(TIMEZONE_COOKIE, "Not/A_Zone")
    assert "Sat 04 Jul, 22:00 UTC" in host_client.get(f"/games/{game.id}").get_data(as_text=True)


@pytest.mark.parametrize(
    "name",
    [None, "", "Mars/Olympus_Mons", "../../etc/passwd", "/etc/localtime", "America", "x" * 200],
)
def test_a_client_supplied_zone_name_that_is_not_a_zone_is_ignored(name):
    assert resolve_timezone(name) is None
