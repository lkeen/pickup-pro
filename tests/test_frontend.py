"""Front-end wiring: the map endpoint, and the data the charts read."""

import json
import re

import pytest

from app.models import PlayerRating, PlayerStats
from app.services.aggregates import chart_data


class TestCourtsApi:
    def test_it_requires_login(self, client):
        assert client.get("/api/v1/courts").status_code == 302

    def test_it_returns_coordinates_for_every_court(
        self, db, login, user_factory, court_factory
    ):
        user = user_factory()
        court_factory(name="Legion Field", lat=33.9519, lng=-83.3576, created_by=user.id)
        client = login(user)

        body = client.get("/api/v1/courts").get_json()
        assert body["count"] == 1
        court = body["courts"][0]
        assert court["lat"] == 33.9519
        assert court["lng"] == -83.3576
        assert court["name"] == "Legion Field"

    def test_it_is_served_from_the_cached_list(
        self, db, login, user_factory, court_factory, query_counter
    ):
        user = user_factory()
        court_factory(created_by=user.id)
        client = login(user)

        client.get("/api/v1/courts")
        query_counter.reset()
        client.get("/api/v1/courts")
        assert query_counter.count <= 1, "the court list was re-queried on a cache hit"


class TestMapPage:
    @pytest.mark.parametrize("path", ["/dashboard", "/courts/create"])
    def test_map_pages_load_leaflet_locally(self, db, login, user_factory, path):
        """Vendored, not from a CDN: the app works offline and does not depend
        on a third party staying up."""
        client = login(user_factory())
        body = client.get(path).get_data(as_text=True)
        assert "/static/vendor/leaflet.js" in body
        assert "/static/vendor/leaflet.css" in body
        assert "unpkg.com" not in body
        assert "cdn.jsdelivr.net" not in body

    def test_the_game_page_loads_leaflet_locally(self, db, login, user_factory, game_factory):
        host = user_factory()
        game = game_factory(host=host)
        body = login(host).get(f"/games/{game.id}").get_data(as_text=True)
        assert "/static/vendor/leaflet.js" in body
        assert "/static/vendor/leaflet.css" in body

    def test_the_map_is_the_home_page(self, db, login, user_factory):
        client = login(user_factory())
        body = client.get("/dashboard").get_data(as_text=True)
        assert 'id="court-map"' in body
        assert 'data-map="home"' in body
        assert 'id="nearby-search"' in body
        assert 'id="feed"' in body

    def test_the_map_data_counts_upcoming_games_per_court(
        self, db, login, user_factory, court_factory, game_factory
    ):
        """The markers show where games are, so a past game must not count."""
        from datetime import timedelta

        from app.timeutils import utcnow

        host = user_factory()
        busy = court_factory(name="Busy", created_by=host.id)
        quiet = court_factory(name="Quiet", lat=34.0, created_by=host.id)
        game_factory(court=busy, host=host)
        game_factory(court=busy, host=host)
        game_factory(court=quiet, host=host, when=utcnow() - timedelta(days=1))

        body = login(host).get("/dashboard").get_data(as_text=True)
        match = re.search(
            r'<script type="application/json" id="map-data">(.*?)</script>', body, re.S
        )
        assert match, "map payload not found"
        courts = {court["name"]: court for court in json.loads(match.group(1))["courts"]}
        assert courts["Busy"]["upcoming"] == 2
        assert courts["Quiet"]["upcoming"] == 0
        assert {"lat", "lng", "address", "id"} <= set(courts["Busy"])

    def test_the_game_page_maps_its_court(
        self, db, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        court = court_factory(lat=33.9519, lng=-83.3576, created_by=host.id)
        game = game_factory(court=court, host=host)
        body = login(host).get(f"/games/{game.id}").get_data(as_text=True)
        assert 'data-map="point"' in body
        assert 'data-lat="33.9519"' in body
        assert 'data-lng="-83.3576"' in body

    def test_the_court_form_has_a_pin_picker(self, db, login, user_factory):
        body = login(user_factory()).get("/courts/create").get_data(as_text=True)
        assert 'data-map="picker"' in body
        assert 'data-lat-input="lat"' in body
        assert 'data-lng-input="lng"' in body


class TestChartData:
    def test_it_is_chronological(self, db, user_factory, game_factory):
        """The tables list newest first; a trend line has to read left to right."""
        from datetime import timedelta

        from app.timeutils import utcnow

        player = user_factory()
        for offset, points in [(3, 10), (2, 20), (1, 30)]:
            game = game_factory(
                host=player, players=[player], when=utcnow() - timedelta(days=offset)
            )
            db.session.add(PlayerStats(game_id=game.id, user_id=player.id, points=points))
        db.session.commit()

        series = chart_data(player.id)["games"]
        assert [g["points"] for g in series] == [10, 20, 30]

    def test_rating_distribution_has_a_bucket_per_score(self, db, user_factory, game_factory):
        target = user_factory()
        raters = [user_factory() for _ in range(3)]
        game = game_factory(host=target, players=[target, *raters])
        for rater, score in zip(raters, [5, 5, 3], strict=True):
            db.session.add(
                PlayerRating(
                    game_id=game.id, from_user_id=rater.id, to_user_id=target.id, rating=score
                )
            )
        db.session.commit()

        assert chart_data(target.id)["ratings"] == [0, 0, 1, 0, 2]

    def test_an_empty_profile_produces_empty_series(self, db, user_factory):
        assert chart_data(user_factory().id) == {"games": [], "ratings": [0, 0, 0, 0, 0]}

    def test_charts_are_not_loaded_without_enough_data(self, db, login, user_factory):
        """Two points is the minimum for a trend to mean anything; below that,
        do not ship 200 KB of charting library."""
        user = user_factory()
        client = login(user)
        body = client.get(f"/users/{user.id}").get_data(as_text=True)
        assert "chart.umd.js" not in body

    def test_charts_load_once_there_is_a_trend(self, db, login, user_factory, game_factory):
        from datetime import timedelta

        from app.timeutils import utcnow

        player = user_factory()
        for offset in (2, 1):
            game = game_factory(
                host=player, players=[player], when=utcnow() - timedelta(days=offset)
            )
            db.session.add(PlayerStats(game_id=game.id, user_id=player.id, points=10))
        db.session.commit()

        client = login(player)
        body = client.get(f"/users/{player.id}").get_data(as_text=True)
        assert "chart.umd.js" in body
        assert 'id="stat-trend"' in body

    def test_the_embedded_payload_is_valid_json(self, db, login, user_factory, game_factory):
        from datetime import timedelta

        from app.timeutils import utcnow

        player = user_factory()
        for offset in (2, 1):
            game = game_factory(
                host=player, players=[player], when=utcnow() - timedelta(days=offset)
            )
            db.session.add(PlayerStats(game_id=game.id, user_id=player.id, points=7))
        db.session.commit()

        client = login(player)
        body = client.get(f"/users/{player.id}").get_data(as_text=True)
        match = re.search(
            r'<script type="application/json" id="profile-chart-data">(.*?)</script>',
            body,
            re.S,
        )
        assert match, "chart payload not found"
        parsed = json.loads(match.group(1))
        assert len(parsed["games"]) == 2


class TestVendoredAssets:
    @pytest.mark.parametrize(
        "path", ["vendor/leaflet.js", "vendor/leaflet.css", "vendor/chart.umd.js",
                 "js/map.js", "js/charts.js", "js/modals.js", "js/ui.js", "css/main.css"]
    )
    def test_static_assets_are_served(self, client, app, path):
        response = client.get(f"/static/{path}")
        assert response.status_code == 200, f"{path} is missing"
        assert len(response.get_data()) > 0
