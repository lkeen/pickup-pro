"""Cached profile aggregates, the court list, and leaderboards."""

import pytest

from app.extensions import cache as flask_cache
from app.models import PlayerStats
from app.services import caching
from app.services.aggregates import (
    MIN_GAMES_FOR_AVERAGE,
    all_courts_brief,
    leaderboard,
    profile_summary,
    rating_leaderboard,
)


def _record(db, game, user, points=10, rebounds=5, assists=2):
    db.session.add(
        PlayerStats(
            game_id=game.id, user_id=user.id, points=points, rebounds=rebounds, assists=assists
        )
    )
    db.session.commit()


class TestProfileSummary:
    def test_totals_and_averages(self, db, user_factory, game_factory):
        player = user_factory()
        for points in (10, 20, 30):
            game = game_factory(host=player, players=[player])
            _record(db, game, player, points=points)
            caching.invalidate(f"user:{player.id}")

        summary = profile_summary(player.id)
        assert summary["games_played"] == 3
        assert summary["total_points"] == 60
        assert summary["avg_points"] == pytest.approx(20.0)

    def test_an_empty_profile_returns_zeroes_not_none(self, db, user_factory):
        """The template formats these; None would raise rather than render."""
        summary = profile_summary(user_factory().id)
        assert summary["games_played"] == 0
        assert summary["total_points"] == 0
        assert summary["avg_points"] == 0.0
        assert summary["avg_rating"] is None

    def test_the_summary_is_cached(self, db, user_factory, query_counter):
        player = user_factory()
        profile_summary(player.id)
        query_counter.reset()
        profile_summary(player.id)
        assert query_counter.count == 0, "the aggregation ran again on a cache hit"

    def test_a_stat_write_refreshes_the_profile_immediately(
        self, db, login, user_factory, game_factory
    ):
        player = user_factory()
        teammate = user_factory()
        game = game_factory(host=player, players=[player, teammate])

        client = login(player)
        assert client.get(f"/users/{teammate.id}").status_code == 200  # caches the summary

        client.post(
            f"/games/{game.id}/stats",
            data={"user_id": str(teammate.id), "points": "31", "rebounds": "0", "assists": "0"},
        )

        assert profile_summary(teammate.id)["total_points"] == 31

    def test_one_players_write_does_not_disturb_another(self, db, user_factory, game_factory):
        """Tagged per user: invalidation has to be narrow or the cache is
        pointless."""
        a, b = user_factory(), user_factory()
        game = game_factory(host=a, players=[a, b])
        _record(db, game, a, points=10)
        _record(db, game, b, points=20)

        profile_summary(a.id)
        profile_summary(b.id)
        caching.invalidate(f"user:{a.id}")

        assert flask_cache.get(caching.make_key("profile", user=b.id)) is not None


class TestCourtList:
    def test_the_list_is_cached(self, db, court_factory, query_counter):
        court_factory(name="One")
        all_courts_brief()
        query_counter.reset()
        all_courts_brief()
        assert query_counter.count == 0

    def test_creating_a_court_invalidates_the_list(self, db, login, user_factory):
        user = user_factory()
        client = login(user)
        assert len(all_courts_brief()) == 0

        client.post(
            "/courts/create",
            data={"name": "Fresh Court", "address": "1 St", "lat": "33.9", "lng": "-83.3"},
        )
        assert [c["name"] for c in all_courts_brief()] == ["Fresh Court"]


class TestLeaderboard:
    def test_ranks_by_the_requested_metric(self, db, user_factory, game_factory):
        low, high = user_factory(), user_factory()
        game = game_factory(host=low, players=[low, high])
        _record(db, game, low, points=5, assists=20)
        _record(db, game, high, points=40, assists=1)
        caching.invalidate("leaderboard")

        assert leaderboard("points")[0]["username"] == high.username
        caching.invalidate("leaderboard")
        assert leaderboard("assists")[0]["username"] == low.username

    def test_an_unknown_metric_falls_back_rather_than_erroring(self, db):
        assert leaderboard("'; DROP TABLE users; --") == leaderboard("points")

    def test_averages_require_a_minimum_number_of_games(self, db, user_factory, game_factory):
        """One good game should not top a season."""
        flash, steady = user_factory(), user_factory()

        game = game_factory(host=flash, players=[flash])
        _record(db, game, flash, points=50)

        for _ in range(MIN_GAMES_FOR_AVERAGE):
            g = game_factory(host=steady, players=[steady])
            _record(db, g, steady, points=20)

        caching.invalidate("leaderboard")
        names = [row["username"] for row in leaderboard("ppg")]
        assert flash.username not in names, "a single game qualified for a per-game average"
        assert steady.username in names

    def test_the_leaderboard_is_cached(self, db, query_counter):
        leaderboard("points")
        query_counter.reset()
        leaderboard("points")
        assert query_counter.count == 0

    def test_a_stat_write_invalidates_the_leaderboard(
        self, db, login, user_factory, game_factory
    ):
        a, b = user_factory(), user_factory()
        game = game_factory(host=a, players=[a, b])
        assert leaderboard("points") == []  # cached empty

        client = login(a)
        client.post(
            f"/games/{game.id}/stats",
            data={"user_id": str(b.id), "points": "42", "rebounds": "0", "assists": "0"},
        )
        assert leaderboard("points")[0]["value"] == 42

    def test_rating_leaderboard_requires_a_minimum_number_of_ratings(
        self, db, user_factory, game_factory
    ):
        target = user_factory()
        raters = [user_factory() for _ in range(MIN_GAMES_FOR_AVERAGE)]
        game = game_factory(host=target, players=[target, *raters])

        from app.models import PlayerRating

        db.session.add(
            PlayerRating(
                game_id=game.id, from_user_id=raters[0].id, to_user_id=target.id, rating=5
            )
        )
        db.session.commit()
        caching.invalidate("leaderboard")
        assert rating_leaderboard() == [], "one rating was enough to rank"


class TestLeaderboardPage:
    def test_it_renders(self, db, login, user_factory):
        client = login(user_factory())
        response = client.get("/leaderboard")
        assert response.status_code == 200
        assert "Leaderboard" in response.get_data(as_text=True)

    def test_it_requires_login(self, client):
        assert client.get("/leaderboard").status_code == 302

    def test_an_unknown_metric_in_the_url_is_ignored(self, db, login, user_factory):
        client = login(user_factory())
        assert client.get("/leaderboard?metric=nonsense").status_code == 200
