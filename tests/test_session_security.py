"""Session cookie hardening, rate limiting and session fixation."""

import pytest

from config import DevelopmentConfig, ProductionConfig


class TestCookieFlags:
    def test_session_cookie_is_not_readable_from_javascript(self):
        assert DevelopmentConfig.SESSION_COOKIE_HTTPONLY is True
        assert ProductionConfig.SESSION_COOKIE_HTTPONLY is True

    def test_session_cookie_is_https_only_in_production(self):
        assert ProductionConfig.SESSION_COOKIE_SECURE is True
        assert ProductionConfig.REMEMBER_COOKIE_SECURE is True

    def test_session_cookie_is_not_sent_cross_site(self):
        assert DevelopmentConfig.SESSION_COOKIE_SAMESITE == "Lax"

    def test_session_lifetime_is_shorter_than_the_flask_default(self):
        # Flask's default is 31 days.
        assert DevelopmentConfig.PERMANENT_SESSION_LIFETIME.days <= 7

    def test_the_flags_actually_reach_the_response(self, client, user_factory):
        user = user_factory(username="cookieuser")
        response = client.post(
            "/login", data={"username": "cookieuser", "password": user._test_password}
        )
        set_cookie = response.headers.get("Set-Cookie", "")
        assert "HttpOnly" in set_cookie
        assert "SameSite=Lax" in set_cookie


class TestSessionFixation:
    def test_the_session_cookie_changes_on_login(self, client, user_factory):
        """An attacker who fixes a victim's pre-login session must not inherit it."""
        user = user_factory(username="fixation")

        client.get("/")  # establishes an anonymous session
        with client.session_transaction() as session:
            session["planted"] = "attacker-controlled"

        client.post("/login", data={"username": "fixation", "password": user._test_password})

        with client.session_transaction() as session:
            assert "planted" not in session, "pre-login session data survived login"
            assert session.get("_user_id") == str(user.id)


class TestRateLimiting:
    @pytest.fixture()
    def limited(self, app, db):
        """Turn the limiter on for one test.

        It is off for the rest of the suite: shared counters would make every
        other test order-dependent.
        """
        from app.extensions import limiter

        limiter.enabled = True
        limiter.reset()
        try:
            yield app.test_client()
        finally:
            limiter.reset()
            limiter.enabled = False

    def test_repeated_failed_logins_are_throttled(self, limited, user_factory):
        user_factory(username="target")

        statuses = [
            limited.post("/login", data={"username": "target", "password": "wrong"}).status_code
            for _ in range(15)
        ]
        assert 429 in statuses, "brute-force attempts were never rate limited"
        # The limit is 10/minute, so the first 10 should get through.
        assert statuses[:10] == [200] * 10

    def test_registration_is_throttled(self, limited):
        statuses = [
            limited.post(
                "/register", data={"username": f"spam{i}", "password": "long-enough-pw"}
            ).status_code
            for i in range(10)
        ]
        assert 429 in statuses

    def test_reading_pages_is_not_throttled(self, limited, user_factory):
        user = user_factory(username="reader")
        limited.post("/login", data={"username": "reader", "password": user._test_password})
        statuses = [limited.get("/games").status_code for _ in range(30)]
        assert 429 not in statuses, "ordinary browsing hit a rate limit"
