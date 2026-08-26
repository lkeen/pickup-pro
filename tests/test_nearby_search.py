"""Spatial search over the GiST-indexed geography column.

Replaces an implementation that loaded every future game into Python and
filtered with a Haversine loop. On 25,000 courts / 75,000 games that took
~2.2 s and pulled 75,000 rows into the application; ST_DWithin against
ix_courts_geog answers the same question in ~9 ms and returns 13.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.services.geo import InvalidSearch, validate_search
from app.utils import haversine_distance

ATHENS = (33.9519, -83.3576)
ATLANTA = (33.7490, -84.3880)  # ~98 km from Athens
NEW_YORK = (40.7128, -74.0060)

ENDPOINT = "/api/v1/games/nearby"


def _url(lat, lng, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{ENDPOINT}?lat={lat}&lng={lng}" + (f"&{query}" if query else "")


class TestValidation:
    def test_the_origin_is_a_valid_search(self):
        """lat=0/lng=0 is Null Island, not a missing value.

        The old guard was `if not lat or not lng`, which rejected the equator
        and the prime meridian outright.
        """
        lat, lng, radius, date = validate_search(0.0, 0.0, 10.0)
        assert (lat, lng) == (0.0, 0.0)

    def test_missing_coordinates_are_reported_separately(self):
        with pytest.raises(InvalidSearch, match="Latitude is required"):
            validate_search(None, -83.0, 10.0)
        with pytest.raises(InvalidSearch, match="Longitude is required"):
            validate_search(33.0, None, 10.0)

    @pytest.mark.parametrize("lat,lng", [(91, 0), (-91, 0), (0, 181), (0, -181)])
    def test_out_of_range_coordinates_are_rejected(self, lat, lng):
        with pytest.raises(InvalidSearch):
            validate_search(lat, lng, 10.0)

    @pytest.mark.parametrize("radius", [0, -1, 1000])
    def test_unusable_radii_are_rejected(self, radius):
        with pytest.raises(InvalidSearch):
            validate_search(*ATHENS, radius)

    def test_radius_defaults_when_omitted(self):
        _, _, radius, _ = validate_search(*ATHENS, None)
        assert radius == 10.0

    def test_a_malformed_date_is_rejected(self):
        with pytest.raises(InvalidSearch, match="YYYY-MM-DD"):
            validate_search(*ATHENS, 10.0, "not-a-date")


class TestEndpoint:
    def test_requires_login(self, client):
        assert client.get(_url(*ATHENS)).status_code == 302

    def test_the_origin_is_accepted_by_the_endpoint(self, login, user_factory):
        """Regression: this returned 400 'Latitude and longitude are required'."""
        client = login(user_factory())
        response = client.get(_url(0, 0))
        assert response.status_code == 200, response.get_json()

    def test_missing_coordinates_return_400(self, login, user_factory):
        client = login(user_factory())
        response = client.get(f"{ENDPOINT}?lng=-83.35")
        assert response.status_code == 400
        assert "Latitude is required" in response.get_json()["error"]

    def test_non_numeric_coordinates_return_400(self, login, user_factory):
        """`?lat=abc` used to parse to None and be indistinguishable from
        omitting it entirely."""
        client = login(user_factory())
        response = client.get(f"{ENDPOINT}?lat=abc&lng=xyz")
        assert response.status_code == 400

    def test_finds_a_game_inside_the_radius(self, login, user_factory, court_factory, game_factory):
        host = user_factory()
        court = court_factory(lat=ATHENS[0], lng=ATHENS[1], created_by=host.id)
        game_factory(court=court, host=host)

        client = login(host)
        body = client.get(_url(*ATHENS, radius=5)).get_json()
        assert body["count"] == 1
        assert body["games"][0]["court_name"] == court.name
        assert body["games"][0]["distance_km"] == pytest.approx(0, abs=0.01)

    def test_excludes_a_game_outside_the_radius(
        self, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        far = court_factory(name="Atlanta", lat=ATLANTA[0], lng=ATLANTA[1], created_by=host.id)
        game_factory(court=far, host=host)

        client = login(host)
        # Atlanta is ~98 km from Athens.
        assert client.get(_url(*ATHENS, radius=50)).get_json()["count"] == 0
        assert client.get(_url(*ATHENS, radius=150)).get_json()["count"] == 1

    def test_results_are_ordered_by_distance(
        self, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        near = court_factory(name="Near", lat=ATHENS[0], lng=ATHENS[1], created_by=host.id)
        far = court_factory(name="Far", lat=ATLANTA[0], lng=ATLANTA[1], created_by=host.id)
        game_factory(court=far, host=host)
        game_factory(court=near, host=host)

        client = login(host)
        games = client.get(_url(*ATHENS, radius=150)).get_json()["games"]
        assert [g["court_name"] for g in games] == ["Near", "Far"]
        assert games[0]["distance_km"] < games[1]["distance_km"]

    def test_reported_distance_matches_the_haversine_oracle(
        self, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        court = court_factory(lat=ATLANTA[0], lng=ATLANTA[1], created_by=host.id)
        game_factory(court=court, host=host)

        client = login(host)
        reported = client.get(_url(*ATHENS, radius=150)).get_json()["games"][0]["distance_km"]
        expected = haversine_distance(*ATHENS, *ATLANTA)
        assert reported == pytest.approx(expected, rel=0.005)

    def test_past_games_are_excluded_by_default(
        self, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        court = court_factory(lat=ATHENS[0], lng=ATHENS[1], created_by=host.id)
        game_factory(court=court, host=host, when=datetime.now() - timedelta(days=1))

        client = login(host)
        assert client.get(_url(*ATHENS, radius=5)).get_json()["count"] == 0

    def test_a_date_filter_selects_that_day_only(
        self, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        court = court_factory(lat=ATHENS[0], lng=ATHENS[1], created_by=host.id)
        target = datetime.now() + timedelta(days=3)
        game_factory(court=court, host=host, when=target)
        game_factory(court=court, host=host, when=target + timedelta(days=1))

        client = login(host)
        body = client.get(_url(*ATHENS, radius=5, date=target.strftime("%Y-%m-%d"))).get_json()
        assert body["count"] == 1

    def test_a_distant_search_finds_nothing(
        self, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        court = court_factory(lat=ATHENS[0], lng=ATHENS[1], created_by=host.id)
        game_factory(court=court, host=host)

        client = login(host)
        assert client.get(_url(*NEW_YORK, radius=50)).get_json()["count"] == 0


class TestQueryPlan:
    def test_the_gist_index_is_used(self, db, court_factory):
        """The whole point of the branch. If the planner stops choosing the
        index, this is a silent 200x regression that no correctness test would
        notice.
        """
        for i in range(50):
            court_factory(name=f"Court {i}", lat=33.0 + i * 0.01, lng=-83.0 - i * 0.01)
        db.session.execute(text("ANALYZE courts"))

        plan = "\n".join(
            db.session.execute(
                text(
                    "EXPLAIN SELECT id FROM courts WHERE ST_DWithin("
                    "geog, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :m)"
                ),
                {"lat": 33.0, "lng": -83.0, "m": 25000.0},
            ).scalars()
        )
        assert "ix_courts_geog" in plan, f"GiST index not used:\n{plan}"
        assert "Seq Scan" not in plan, f"fell back to a sequential scan:\n{plan}"

    def test_the_bounding_box_prefilter_is_what_the_index_serves(self, db, court_factory):
        """ST_DWithin is two stages: the index answers `geog && expanded_box`,
        then PostGIS refines the survivors with an exact spheroid distance."""
        for i in range(50):
            court_factory(name=f"Court {i}", lat=33.0 + i * 0.01, lng=-83.0 - i * 0.01)
        db.session.execute(text("ANALYZE courts"))

        plan = "\n".join(
            db.session.execute(
                text(
                    "EXPLAIN SELECT id FROM courts WHERE ST_DWithin("
                    "geog, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :m)"
                ),
                {"lat": 33.0, "lng": -83.0, "m": 5000.0},
            ).scalars()
        )
        assert "&&" in plan, f"no bounding-box operator in the index condition:\n{plan}"
        assert "st_dwithin" in plan.lower(), f"no exact refine step:\n{plan}"
