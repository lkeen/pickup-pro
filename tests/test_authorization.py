"""Authorization on the stats and ratings write path.

Regression cover for a broken-access-control bug: submit_stats read user_id
straight from the form and checked only that the *caller* was rostered, never
the target. Any rostered player could write stats for, or rate, any user in the
database. Same shape in submit_rating via to_user_id.
"""

from app.models import PlayerRating, PlayerStats


def _stats_payload(user_id, points=99):
    return {"user_id": str(user_id), "points": str(points), "rebounds": "0", "assists": "0"}


def _rating_payload(user_id, rating=1):
    return {"to_user_id": str(user_id), "rating": str(rating), "comment": "x"}


class TestStatsAuthorization:
    def test_a_rostered_player_can_write_their_own_stats(
        self, db, login, user_factory, game_factory
    ):
        player = user_factory()
        game = game_factory(host=player, players=[player])
        client = login(player)

        response = client.post(f"/games/{game.id}/stats", data=_stats_payload(player.id, 21))
        assert response.status_code == 302
        assert db.session.query(PlayerStats).one().points == 21

    def test_a_rostered_player_can_write_a_teammates_stats(
        self, db, login, user_factory, game_factory
    ):
        a, b = user_factory(), user_factory()
        game = game_factory(host=a, players=[a, b])
        client = login(a)

        response = client.post(f"/games/{game.id}/stats", data=_stats_payload(b.id, 12))
        assert response.status_code == 302
        assert db.session.query(PlayerStats).one().user_id == b.id

    def test_cannot_write_stats_for_someone_not_on_the_roster(
        self, db, login, user_factory, game_factory
    ):
        """The bug: outsider was never checked against the roster."""
        player = user_factory()
        outsider = user_factory()
        game = game_factory(host=player, players=[player])
        client = login(player)

        response = client.post(f"/games/{game.id}/stats", data=_stats_payload(outsider.id))
        assert response.status_code == 403
        assert db.session.query(PlayerStats).count() == 0

    def test_cannot_write_stats_for_a_user_who_does_not_exist(
        self, db, login, user_factory, game_factory
    ):
        player = user_factory()
        game = game_factory(host=player, players=[player])
        client = login(player)

        response = client.post(f"/games/{game.id}/stats", data=_stats_payload(999999))
        assert response.status_code == 403
        assert db.session.query(PlayerStats).count() == 0

    def test_a_non_rostered_caller_is_refused(self, db, login, user_factory, game_factory):
        host = user_factory()
        outsider = user_factory()
        game = game_factory(host=host, players=[host])
        client = login(outsider)

        response = client.post(f"/games/{game.id}/stats", data=_stats_payload(host.id))
        assert response.status_code == 403
        assert db.session.query(PlayerStats).count() == 0

    def test_a_garbage_user_id_is_a_400_not_a_500(self, login, user_factory, game_factory):
        player = user_factory()
        game = game_factory(host=player, players=[player])
        client = login(player)

        response = client.post(
            f"/games/{game.id}/stats",
            data={"user_id": "not-a-number", "points": "1", "rebounds": "0", "assists": "0"},
        )
        assert response.status_code == 400

    def test_anonymous_callers_are_redirected(self, client, user_factory, game_factory):
        host = user_factory()
        game = game_factory(host=host, players=[host])
        response = client.post(f"/games/{game.id}/stats", data=_stats_payload(host.id))
        assert response.status_code == 302

    def test_a_missing_game_is_404(self, login, user_factory):
        client = login(user_factory())
        assert client.post("/games/999999/stats", data=_stats_payload(1)).status_code == 404


class TestRatingAuthorization:
    def test_a_rostered_player_can_rate_a_teammate(
        self, db, login, user_factory, game_factory
    ):
        a, b = user_factory(), user_factory()
        game = game_factory(host=a, players=[a, b])
        client = login(a)

        response = client.post(f"/games/{game.id}/rate", data=_rating_payload(b.id, 4))
        assert response.status_code == 302
        assert db.session.query(PlayerRating).one().rating == 4

    def test_cannot_rate_someone_not_on_the_roster(
        self, db, login, user_factory, game_factory
    ):
        a, b = user_factory(), user_factory()
        outsider = user_factory()
        game = game_factory(host=a, players=[a, b])
        client = login(a)

        response = client.post(f"/games/{game.id}/rate", data=_rating_payload(outsider.id))
        assert response.status_code == 403
        assert db.session.query(PlayerRating).count() == 0

    def test_cannot_rate_yourself(self, db, login, user_factory, game_factory):
        a, b = user_factory(), user_factory()
        game = game_factory(host=a, players=[a, b])
        client = login(a)

        response = client.post(f"/games/{game.id}/rate", data=_rating_payload(a.id))
        assert response.status_code == 403
        assert db.session.query(PlayerRating).count() == 0

    def test_ratings_outside_one_to_five_are_rejected(
        self, db, login, user_factory, game_factory
    ):
        a, b = user_factory(), user_factory()
        game = game_factory(host=a, players=[a, b])
        client = login(a)

        for bad in ("0", "6", "-1", "99"):
            response = client.post(f"/games/{game.id}/rate", data=_rating_payload(b.id, bad))
            assert response.status_code == 302, f"rating={bad} was not rejected"
        assert db.session.query(PlayerRating).count() == 0
