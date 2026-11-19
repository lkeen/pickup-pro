"""Cache-aside with tag-based invalidation.

A TTL bounds how stale an entry can get, but it also guarantees every entry *is*
stale for up to that long. Deleting on write is what makes a useful TTL
affordable.
"""

import pytest

from app.services import caching


@pytest.fixture()
def counted():
    """A producer that records how many times it actually ran."""

    class Producer:
        def __init__(self):
            self.calls = 0

        def __call__(self):
            self.calls += 1
            return {"n": self.calls}

    return Producer()


class TestKeys:
    def test_argument_order_does_not_change_the_key(self):
        assert caching.make_key("nearby", lat=1, lng=2) == caching.make_key("nearby", lng=2, lat=1)

    def test_different_arguments_give_different_keys(self):
        assert caching.make_key("nearby", lat=1) != caching.make_key("nearby", lat=2)

    def test_namespaces_are_separate(self):
        assert caching.make_key("a", x=1) != caching.make_key("b", x=1)

    def test_long_keys_are_hashed_to_a_sane_length(self):
        key = caching.make_key("nearby", blob="x" * 500)
        assert len(key) < 100

    def test_the_version_prefix_is_present(self):
        """Bumping CACHE_VERSION must retire every existing entry, which only
        works if the version is part of the key."""
        assert caching.make_key("nearby", lat=1).startswith(caching.CACHE_VERSION)


class TestCacheAside:
    def test_the_producer_runs_once_and_the_value_is_reused(self, cache, counted):
        key = caching.make_key("test", case="reuse")
        first = caching.get_or_set(key, counted, ttl=60)
        second = caching.get_or_set(key, counted, ttl=60)
        assert first == second == {"n": 1}
        assert counted.calls == 1

    def test_a_miss_is_recorded_then_a_hit(self, cache, counted):
        caching.stats.reset()
        key = caching.make_key("test", case="stats")
        caching.get_or_set(key, counted, ttl=60)
        caching.get_or_set(key, counted, ttl=60)
        assert caching.stats.as_dict() == {"hits": 1, "misses": 1, "hit_rate": 0.5}

    def test_falsy_values_are_still_cached(self, cache):
        """`if not cached` would recompute an empty result list every time --
        exactly the query you least want to repeat."""
        calls = {"n": 0}

        def produce_empty():
            calls["n"] += 1
            return {"games": [], "count": 0}

        key = caching.make_key("test", case="empty")
        caching.get_or_set(key, produce_empty, ttl=60)
        caching.get_or_set(key, produce_empty, ttl=60)
        assert calls["n"] == 1


class TestInvalidation:
    def test_invalidating_a_tag_drops_its_entries(self, cache, counted):
        key = caching.make_key("test", case="tagged")
        caching.get_or_set(key, counted, ttl=300, tags=("courts",))
        assert caching.get_or_set(key, counted, ttl=300, tags=("courts",)) == {"n": 1}

        assert caching.invalidate("courts") == 1
        assert caching.get_or_set(key, counted, ttl=300, tags=("courts",)) == {"n": 2}

    def test_one_tag_can_cover_many_entries(self, cache):
        for i in range(5):
            key = caching.make_key("test", case="multi", i=i)
            caching.get_or_set(key, lambda i=i: {"i": i}, ttl=300, tags=("courts",))
        assert caching.invalidate("courts") == 5

    def test_other_tags_are_untouched(self, cache, counted):
        mine = caching.make_key("test", case="mine")
        theirs = caching.make_key("test", case="theirs")
        caching.get_or_set(mine, counted, ttl=300, tags=("courts",))
        caching.get_or_set(theirs, counted, ttl=300, tags=("games",))

        caching.invalidate("courts")

        # theirs still cached: the producer does not run again.
        before = counted.calls
        caching.get_or_set(theirs, counted, ttl=300, tags=("games",))
        assert counted.calls == before

    def test_an_entry_can_carry_several_tags(self, cache, counted):
        key = caching.make_key("test", case="both")
        caching.get_or_set(key, counted, ttl=300, tags=("courts", "games"))
        # Invalidating either one should drop it.
        assert caching.invalidate("games") == 1

    def test_invalidating_an_unknown_tag_is_harmless(self, cache):
        assert caching.invalidate("nothing-uses-this") == 0

    def test_invalidate_with_no_tags_is_harmless(self, cache):
        assert caching.invalidate() == 0


class TestConfiguration:
    def test_tests_use_a_separate_redis_database(self, app):
        """A test run must not evict or read development cache entries."""
        assert app.config["CACHE_REDIS_URL"].endswith("/15")

    def test_the_rate_limiter_shares_the_redis_backend(self, app):
        assert app.config["RATELIMIT_STORAGE_URI"].startswith("redis://")
