"""Timezone handling.

Everything is stored as an instant in UTC. Wall-clock times exist only at the
edges: a form submits one, a page renders one back.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.models import Game
from app.timeutils import to_local, to_utc, utcnow


def test_utcnow_is_timezone_aware():
    """datetime.now() returns naive local time and datetime.utcnow() returns a
    naive datetime holding UTC -- which looks local and is not."""
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_stored_timestamps_are_timezone_aware(db, user_factory):
    user = user_factory()
    db.session.refresh(user)
    assert user.created_at.tzinfo is not None


def test_every_timestamp_column_is_timestamptz(db):
    naive = db.session.execute(
        text(
            "SELECT table_name || '.' || column_name "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND data_type = 'timestamp without time zone'"
        )
    ).scalars().all()
    assert naive == [], f"still naive: {naive}"


class TestWallClockConversion:
    def test_a_submitted_time_is_interpreted_in_the_app_timezone(self, app):
        app.config["APP_TIMEZONE"] = "America/New_York"
        try:
            with app.app_context():
                # 18:00 on a summer date in New York is 22:00 UTC (EDT, UTC-4).
                stored = to_utc(datetime(2026, 7, 4, 18, 0))
                assert stored.hour == 22
                assert stored.utcoffset() == timedelta(0)
        finally:
            app.config["APP_TIMEZONE"] = "UTC"

    def test_a_stored_instant_renders_back_as_the_same_wall_clock(self, app):
        app.config["APP_TIMEZONE"] = "America/New_York"
        try:
            with app.app_context():
                original = datetime(2026, 7, 4, 18, 0)
                assert to_local(to_utc(original)).hour == 18
        finally:
            app.config["APP_TIMEZONE"] = "UTC"

    def test_conversion_respects_daylight_saving(self, app):
        """The offset is not a constant -- a fixed -5 would be an hour out for
        half the year."""
        app.config["APP_TIMEZONE"] = "America/New_York"
        try:
            with app.app_context():
                winter = to_utc(datetime(2026, 1, 15, 12, 0))  # EST, UTC-5
                summer = to_utc(datetime(2026, 7, 15, 12, 0))  # EDT, UTC-4
                assert winter.hour == 17
                assert summer.hour == 16
        finally:
            app.config["APP_TIMEZONE"] = "UTC"

    def test_an_unknown_timezone_falls_back_to_utc(self, app):
        app.config["APP_TIMEZONE"] = "Mars/Olympus_Mons"
        try:
            with app.app_context():
                assert to_utc(datetime(2026, 7, 4, 18, 0)).hour == 18
        finally:
            app.config["APP_TIMEZONE"] = "UTC"

    def test_an_already_aware_datetime_is_converted_not_relabelled(self, app):
        with app.app_context():
            from zoneinfo import ZoneInfo

            aware = datetime(2026, 7, 4, 18, 0, tzinfo=ZoneInfo("America/New_York"))
            assert to_utc(aware).hour == 22


class TestGameTimes:
    def test_a_created_game_stores_an_instant(self, db, login, user_factory, court_factory):
        user = user_factory()
        court = court_factory(created_by=user.id)
        client = login(user)

        response = client.post(
            "/games/create",
            data={"court_id": str(court.id), "time": "2099-07-04T18:00", "max_players": "10"},
        )
        assert response.status_code == 302

        game = db.session.query(Game).one()
        assert game.time.tzinfo is not None
        assert game.time.utcoffset() == timedelta(0)

    def test_comparisons_against_now_do_not_mix_naive_and_aware(
        self, db, login, user_factory, court_factory, game_factory
    ):
        """Comparing a naive datetime with an aware one raises TypeError in
        Python; in SQL it silently compares the wrong things."""
        user = user_factory()
        court = court_factory(lat=33.9519, lng=-83.3576, created_by=user.id)
        game_factory(court=court, host=user, when=utcnow() + timedelta(hours=1))
        game_factory(court=court, host=user, when=utcnow() - timedelta(hours=1))

        client = login(user)
        body = client.get("/api/v1/games/nearby?lat=33.9519&lng=-83.3576&radius=5").get_json()
        assert body["count"] == 1, "past game leaked into a future-games search"

    @pytest.mark.parametrize("tz", ["UTC", "America/New_York", "Asia/Tokyo"])
    def test_search_results_do_not_depend_on_the_server_timezone(
        self, db, app, login, user_factory, court_factory, game_factory, tz
    ):
        app.config["APP_TIMEZONE"] = tz
        try:
            user = user_factory()
            court = court_factory(lat=33.9519, lng=-83.3576, created_by=user.id)
            game_factory(court=court, host=user, when=utcnow() + timedelta(days=2))

            client = login(user)
            body = client.get(
                "/api/v1/games/nearby?lat=33.9519&lng=-83.3576&radius=5"
            ).get_json()
            assert body["count"] == 1
        finally:
            app.config["APP_TIMEZONE"] = "UTC"
