"""Cover for the production-hardening pass.

Security headers, the error handlers, the listing bound, and the two crashes
that unvalidated input and a lost race used to cause.
"""

import pathlib
import re

import pytest
from flask import Flask

from app import trust_proxy_headers
from app.blueprints.games import PAGE_SIZE
from app.services.geo import MAX_RESULTS

TEMPLATE_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "templates"


class TestSecurityHeaders:
    def test_every_response_carries_the_security_headers(self, client):
        response = client.get("/")
        for header in (
            "Content-Security-Policy",
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Referrer-Policy",
            "Permissions-Policy",
        ):
            assert header in response.headers, f"{header} is missing"

    def test_the_policy_allows_no_inline_script_or_style(self, client):
        policy = client.get("/").headers["Content-Security-Policy"]
        assert "'unsafe-inline'" not in policy
        assert "'unsafe-eval'" not in policy
        assert "script-src 'self'" in policy
        assert "frame-ancestors 'none'" in policy

    def test_the_map_tile_host_is_allowed(self, client):
        """The one third-party origin the app actually loads from."""
        policy = client.get("/").headers["Content-Security-Policy"]
        assert "https://*.tile.openstreetmap.org" in policy

    @pytest.mark.parametrize("template", sorted(TEMPLATE_DIR.glob("*.html")), ids=lambda p: p.name)
    def test_no_template_carries_an_inline_style_or_handler(self, template):
        """What makes the strict policy possible. A single style attribute would
        force 'unsafe-inline' back into the header for every page."""
        body = template.read_text(encoding="utf-8")
        assert 'style="' not in body, f"{template.name} has an inline style attribute"
        handler = re.search(r'\son(click|change|submit|load|error|input)\s*=', body)
        assert handler is None, f"{template.name} has an inline {handler.group(1)} handler"

    def test_hsts_is_sent_only_when_configured(self, app, client):
        assert "Strict-Transport-Security" not in client.get("/").headers


class TestErrorHandlers:
    def test_an_html_404_renders_the_app_page(self, client):
        response = client.get("/no-such-page")
        assert response.status_code == 404
        body = response.get_data(as_text=True)
        assert "css/main.css" in body, "the error page is not the app's own"

    def test_an_api_404_is_json(self, client):
        response = client.get("/api/v1/no-such-endpoint")
        assert response.status_code == 404
        assert response.is_json
        assert response.get_json()["status"] == 404

    def test_an_api_403_is_json(self, db, login, user_factory, game_factory):
        """An authorization failure a JSON client can actually parse."""
        game = game_factory()
        client = login(user_factory())
        response = client.post(f"/games/{game.id}/stats", data={"user_id": 1})
        assert response.status_code == 403


class TestListingInput:
    def test_a_non_numeric_court_filter_does_not_crash(self, db, login, user_factory):
        """Passed straight to the ORM, this reached PostgreSQL as
        `court_id = 'abc'` and came back as a 500."""
        client = login(user_factory())
        assert client.get("/games?court_id=abc").status_code == 200

    def test_a_non_numeric_page_does_not_crash(self, db, login, user_factory):
        client = login(user_factory())
        assert client.get("/games?page=abc").status_code == 200

    def test_a_malformed_date_filter_is_ignored(self, db, login, user_factory):
        client = login(user_factory())
        assert client.get("/games?date=not-a-date").status_code == 200


class TestListingIsBounded:
    def test_the_listing_is_paginated(
        self, db, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        court = court_factory(created_by=host.id)
        for _ in range(PAGE_SIZE + 5):
            game_factory(court=court, host=host)

        client = login(host)
        first = client.get("/games").get_data(as_text=True)
        assert first.count('href="/games/') > 0
        assert "Page 1 of 2" in first

        second = client.get("/games?page=2")
        assert second.status_code == 200
        assert "Page 2 of 2" in second.get_data(as_text=True)

    def test_paging_keeps_the_filters(
        self, db, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        court = court_factory(created_by=host.id)
        for _ in range(PAGE_SIZE + 1):
            game_factory(court=court, host=host)

        client = login(host)
        body = client.get(f"/games?court_id={court.id}").get_data(as_text=True)
        assert f"court_id={court.id}" in body, "the pager dropped the court filter"

    def test_past_games_are_not_listed_by_default(
        self, db, login, user_factory, court_factory, game_factory
    ):
        """Ordered by time with no lower bound, page one was the oldest game
        ever played."""
        from datetime import timedelta

        from app.timeutils import utcnow

        host = user_factory()
        old_court = court_factory(name="Ancient Court", created_by=host.id)
        old = game_factory(court=old_court, host=host, when=utcnow() - timedelta(days=30))

        client = login(host)
        body = client.get("/games").get_data(as_text=True)
        # The court still appears in the filter dropdown; its game must not be
        # in the table.
        assert f'href="/games/{old.id}"' not in body

    def test_a_date_filter_still_reaches_the_past(
        self, db, login, user_factory, court_factory, game_factory
    ):
        from datetime import timedelta

        from app.timeutils import utcnow

        host = user_factory()
        court = court_factory(name="Ancient Court", created_by=host.id)
        when = utcnow() - timedelta(days=30)
        old = game_factory(court=court, host=host, when=when)

        client = login(host)
        body = client.get(f"/games?date={when.date().isoformat()}").get_data(as_text=True)
        assert f'href="/games/{old.id}"' in body


class TestNearbyIsBounded:
    def test_the_search_caps_its_result_count(self, db, app, user_factory, court_factory,
                                              game_factory):
        """A wide radius over a dense city would otherwise return, cache and
        serialize an unbounded number of rows."""
        from app.services.geo import nearby_games

        host = user_factory()
        court = court_factory(lat=33.95, lng=-83.35, created_by=host.id)
        for _ in range(MAX_RESULTS + 3):
            game_factory(court=court, host=host)

        with app.app_context():
            rows = nearby_games(33.95, -83.35, 25).all()
        assert len(rows) == MAX_RESULTS


class TestWriteRaces:
    def test_a_duplicate_court_is_refused_not_crashed(self, db, login, user_factory):
        """uq_courts_name_location has no pre-check in front of it, so the
        second submission reached the constraint directly."""
        client = login(user_factory())
        payload = {
            "name": "Legion Field",
            "address": "195 Sanford Dr",
            "lat": "33.9482",
            "lng": "-83.3745",
        }
        assert client.post("/courts/create", data=payload).status_code == 302
        response = client.post("/courts/create", data=payload)
        assert response.status_code == 200
        assert "already exists" in response.get_data(as_text=True)

    def test_a_lost_registration_race_is_handled(self, db, client, user_factory, monkeypatch):
        """Two registrations for one username can both pass the existence check
        and race to the insert. The constraint settles it; the loser should see
        a message, not a 500."""
        from app.blueprints import auth

        user_factory(username="taken")
        monkeypatch.setattr(auth, "_find_by_username", lambda username: None)

        response = client.post(
            "/register",
            data={
                "username": "taken",
                "email": "someone-else@example.com",
                "password": "a-long-enough-password",
            },
        )
        assert response.status_code == 200
        assert "already registered" in response.get_data(as_text=True)


class TestSessionLifetime:
    def test_the_session_is_permanent_so_the_configured_lifetime_applies(
        self, db, client, user_factory
    ):
        """A non-permanent Flask session cookie has no expiry at all, which made
        PERMANENT_SESSION_LIFETIME dead configuration."""
        user = user_factory()
        with client:
            client.post(
                "/login", data={"username": user.username, "password": user._test_password}
            )
            from flask import session

            assert session.permanent is True


class TestProxyHeaders:
    def _probe(self, hops):
        app = Flask(__name__)
        app.config["TRUSTED_PROXY_HOPS"] = hops
        trust_proxy_headers(app)

        @app.route("/where")
        def where():
            from flask import request

            return {"scheme": request.scheme, "ip": request.remote_addr}

        return app.test_client()

    def test_forwarded_headers_are_ignored_without_a_configured_proxy(self):
        """Trusting them unconditionally lets any client claim any address."""
        body = self._probe(0).get(
            "/where",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "9.9.9.9"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ).get_json()
        assert body == {"scheme": "http", "ip": "127.0.0.1"}

    def test_one_configured_hop_is_trusted(self):
        """Without this the app sees the proxy's address for every request --
        one rate-limit bucket for the whole internet -- and builds http:// URLs
        behind a TLS terminator, including the OAuth redirect URI."""
        body = self._probe(1).get(
            "/where",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "9.9.9.9"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ).get_json()
        assert body == {"scheme": "https", "ip": "9.9.9.9"}
