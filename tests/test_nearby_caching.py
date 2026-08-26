"""Caching of the nearby search, and its invalidation.

The interesting property is not that repeated searches are fast -- it is that a
write makes them correct again immediately, rather than after the TTL.
"""

import pytest

from app.services.geo import nearby_cache_key, nearby_cache_tags
from app.services.geohash import cell_for, cells_covering, encode

ATHENS = (33.9519, -83.3576)


def _url(lat, lng, radius=10):
    return f"/api/v1/games/nearby?lat={lat}&lng={lng}&radius={radius}"


class TestKeyQuantisation:
    def test_searches_from_the_same_spot_share_a_key(self):
        """Raw geolocation coordinates never repeat. Without quantisation the
        hit rate would be zero."""
        a = nearby_cache_key(33.951900, -83.357600, 10.0, None)
        b = nearby_cache_key(33.951950, -83.357620, 10.0, None)
        assert a == b

    def test_searches_from_far_apart_do_not(self):
        a = nearby_cache_key(33.9519, -83.3576, 10.0, None)
        b = nearby_cache_key(40.7128, -74.0060, 10.0, None)
        assert a != b

    def test_radius_is_part_of_the_key(self):
        assert nearby_cache_key(*ATHENS, 10.0, None) != nearby_cache_key(*ATHENS, 25.0, None)

    def test_date_is_part_of_the_key(self):
        from datetime import date

        assert nearby_cache_key(*ATHENS, 10.0, None) != nearby_cache_key(
            *ATHENS, 10.0, date(2026, 7, 4)
        )


class TestTagCoverage:
    def test_a_court_inside_the_search_is_covered_by_a_tag(self):
        """Under-covering is a correctness bug: a cell missed when tagging is an
        entry that never gets invalidated."""
        tags = nearby_cache_tags(*ATHENS, 25.0)
        assert cell_for(*ATHENS) in tags

    @pytest.mark.parametrize("radius", [1, 5, 25, 100, 200])
    def test_coverage_grows_with_radius(self, radius):
        assert len(cells_covering(*ATHENS, radius)) >= 1

    def test_a_nearby_court_is_still_covered(self):
        """A court 20 km away can appear in a 25 km search, so its cell has to
        be tagged even though it may be a different cell."""
        tags = set(nearby_cache_tags(*ATHENS, 25.0))
        # ~20 km north
        assert cell_for(ATHENS[0] + 0.18, ATHENS[1]) in tags

    def test_coverage_survives_the_antimeridian(self):
        cells = cells_covering(0.0, 179.9, 50.0)
        assert cell_for(0.0, -179.9) in cells, "cells east of the date line were not covered"

    def test_coverage_survives_the_poles(self):
        assert cells_covering(89.9, 0.0, 100.0)


class TestEndpointCaching:
    def test_a_repeated_search_is_served_from_cache(
        self, db, login, user_factory, court_factory, game_factory, query_counter
    ):
        host = user_factory()
        court = court_factory(lat=ATHENS[0], lng=ATHENS[1], created_by=host.id)
        game_factory(court=court, host=host)
        client = login(host)

        first = client.get(_url(*ATHENS)).get_json()
        query_counter.reset()
        second = client.get(_url(*ATHENS)).get_json()

        assert first == second
        assert query_counter.count <= 2, (
            f"{query_counter.count} queries on a cache hit -- the search still ran"
        )

    def test_a_new_game_appears_immediately_rather_than_after_the_ttl(
        self, db, login, user_factory, court_factory, game_factory
    ):
        """The reason invalidation exists. With a TTL alone, a host would create
        a game and not find it for two minutes."""
        host = user_factory()
        court = court_factory(lat=ATHENS[0], lng=ATHENS[1], created_by=host.id)
        client = login(host)

        assert client.get(_url(*ATHENS)).get_json()["count"] == 0  # now cached

        client.post(
            "/games/create",
            data={"court_id": str(court.id), "time": "2099-07-04T18:00", "max_players": "10"},
        )

        assert client.get(_url(*ATHENS)).get_json()["count"] == 1

    def test_a_new_court_invalidates_searches_covering_it(
        self, db, login, user_factory, court_factory
    ):
        user = user_factory()
        client = login(user)
        client.get(_url(*ATHENS))  # cache a search with nothing in it

        client.post(
            "/courts/create",
            data={
                "name": "Brand New Court",
                "address": "1 New Street",
                "lat": str(ATHENS[0]),
                "lng": str(ATHENS[1]),
            },
        )
        # No games yet, so the count stays 0 -- but the entry must be gone.
        key = nearby_cache_key(*ATHENS, 10.0, None)
        from app.extensions import cache as flask_cache

        assert flask_cache.get(key) is None, "the cached search survived a court being created"

    def test_joining_a_game_invalidates_the_search(
        self, db, login, user_factory, court_factory, game_factory
    ):
        """The response reports current_players and spots_available, so a join
        makes a cached entry wrong."""
        host = user_factory()
        joiner = user_factory()
        court = court_factory(lat=ATHENS[0], lng=ATHENS[1], created_by=host.id)
        game = game_factory(court=court, host=host, players=[host])

        client = login(host)
        before = client.get(_url(*ATHENS)).get_json()["games"][0]
        assert before["current_players"] == 1

        joiner_client = login(joiner)
        joiner_client.post(f"/games/{game.id}/join")

        after = client.get(_url(*ATHENS)).get_json()["games"][0]
        assert after["current_players"] == 2, "cached search still reported a stale roster"

    def test_leaving_a_game_invalidates_the_search(
        self, db, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        joiner = user_factory()
        court = court_factory(lat=ATHENS[0], lng=ATHENS[1], created_by=host.id)
        game = game_factory(court=court, host=host, players=[host, joiner])

        client = login(host)
        assert client.get(_url(*ATHENS)).get_json()["games"][0]["current_players"] == 2

        joiner_client = login(joiner)
        joiner_client.post(f"/games/{game.id}/leave")

        assert client.get(_url(*ATHENS)).get_json()["games"][0]["current_players"] == 1

    def test_a_distant_write_does_not_invalidate_an_unrelated_search(
        self, db, login, user_factory, court_factory
    ):
        """Invalidation has to be targeted, or every write empties the cache and
        the cache stops being one."""
        user = user_factory()
        client = login(user)
        client.get(_url(*ATHENS))

        client.post(
            "/courts/create",
            data={
                "name": "Far Away Court",
                "address": "1 Distant Road",
                "lat": "40.7128",
                "lng": "-74.0060",
            },
        )

        from app.extensions import cache as flask_cache

        key = nearby_cache_key(*ATHENS, 10.0, None)
        assert flask_cache.get(key) is not None, (
            "a court 1200 km away invalidated an unrelated cached search"
        )


class TestGeohash:
    @pytest.mark.parametrize(
        "lat,lng,expected_prefix",
        [(33.9519, -83.3576, "dn"), (51.5074, -0.1278, "gcpv"), (35.6762, 139.6503, "xn")],
    )
    def test_encodes_to_the_known_cell(self, lat, lng, expected_prefix):
        assert encode(lat, lng).startswith(expected_prefix)

    def test_precision_controls_cell_size(self):
        assert len(encode(33.9519, -83.3576, precision=4)) == 4
        assert encode(33.9519, -83.3576, precision=9).startswith(
            encode(33.9519, -83.3576, precision=4)
        )
