"""The map-first home, the player's own games, and returning to the page a
roster change was made from."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from app.models import Court, GamePlayer
from app.timeutils import utcnow

ATHENS = (33.9519, -83.3576)


def _feed(client, query=""):
    response = client.get(f"/dashboard/feed{query}")
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_data(as_text=True)


class TestFeed:
    def test_it_requires_login(self, client):
        assert client.get("/dashboard/feed").status_code == 302

    def test_it_is_a_fragment_not_a_page(self, db, login, user_factory):
        body = _feed(login(user_factory()))
        assert "<html" not in body
        assert "Upcoming games" in body

    def test_unscoped_it_lists_upcoming_games_soonest_first(
        self, db, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()

        def at(name, lat, days):
            court = court_factory(name=name, lat=lat, created_by=host.id)
            return game_factory(court=court, host=host, when=utcnow() + timedelta(days=days))

        later = at("Later Court", 33.9, 3)
        sooner = at("Sooner Court", 34.0, 1)
        past = at("Past Court", 34.1, -1)

        body = _feed(login(user_factory()))
        assert body.index(f'href="/games/{sooner.id}"') < body.index(f'href="/games/{later.id}"')
        assert f'href="/games/{past.id}"' not in body

    def test_a_court_scope_shows_only_that_court(
        self, db, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        here = court_factory(name="Here Court", created_by=host.id)
        there = court_factory(name="There Court", lat=34.0, created_by=host.id)
        mine = game_factory(court=here, host=host)
        other = game_factory(court=there, host=host)

        body = _feed(login(user_factory()), f"?court={here.id}")
        assert "Here Court" in body
        assert f'href="/games/{mine.id}"' in body
        assert f'href="/games/{other.id}"' not in body
        assert f'href="/games/create?court_id={here.id}"' in body, "no way to host here"

    def test_an_empty_court_invites_a_host(self, db, login, user_factory, court_factory):
        court = court_factory()
        body = _feed(login(user_factory()), f"?court={court.id}")
        assert "No games here yet" in body
        assert f"court_id={court.id}" in body

    def test_an_unknown_court_falls_back_to_everything(self, db, login, user_factory):
        body = _feed(login(user_factory()), "?court=999999")
        assert "Upcoming games" in body

    def test_a_point_scope_lists_games_in_range_with_distance(
        self, db, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        near = court_factory(name="Near Court", lat=ATHENS[0], lng=ATHENS[1], created_by=host.id)
        # Atlanta: about 95 km away.
        far = court_factory(name="Far Court", lat=33.749, lng=-84.388, created_by=host.id)
        close_game = game_factory(court=near, host=host)
        far_game = game_factory(court=far, host=host)

        body = _feed(login(user_factory()), f"?lat={ATHENS[0]}&lng={ATHENS[1]}&radius=10")
        assert "Games nearby" in body
        assert "1 game within 10 km" in body
        assert f'href="/games/{close_game.id}"' in body
        assert f'href="/games/{far_game.id}"' not in body
        assert "0.0 km" in body

    def test_an_out_of_range_point_is_a_400(self, db, login, user_factory):
        response = login(user_factory()).get("/dashboard/feed?lat=91&lng=0")
        assert response.status_code == 400
        assert "Latitude" in response.get_data(as_text=True)

    def test_join_buttons_return_to_the_same_scope(
        self, db, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        court = court_factory(created_by=host.id)
        game_factory(court=court, host=host)
        body = _feed(login(user_factory()), f"?court={court.id}")
        assert f'name="next" value="/dashboard?court={court.id}"' in body


class TestHomePage:
    def test_it_renders_the_scope_in_the_url(
        self, db, login, user_factory, court_factory, game_factory
    ):
        """A reload, a shared link, or the redirect after joining lands on the
        same panel."""
        host = user_factory()
        court = court_factory(name="Bookmarked Court", created_by=host.id)
        game_factory(court=court, host=host)
        body = login(user_factory()).get(f"/dashboard?court={court.id}").get_data(as_text=True)
        assert '<h1 id="feed-title" class="feed__title">Bookmarked Court</h1>' in body
        assert f'"selected": {court.id}' in body

    def test_a_bad_point_in_the_url_still_shows_the_map(self, db, login, user_factory):
        response = login(user_factory()).get("/dashboard?lat=500&lng=0")
        assert response.status_code == 200
        assert "Upcoming games" in response.get_data(as_text=True)

    def test_the_radius_picker_reflects_a_point_search(self, db, login, user_factory):
        body = login(user_factory()).get(
            f"/dashboard?lat={ATHENS[0]}&lng={ATHENS[1]}&radius=25"
        ).get_data(as_text=True)
        assert '<option value="25" selected>' in body

    def test_the_radius_picker_shows_an_area_search_radius(self, db, login, user_factory):
        body = login(user_factory()).get(
            f"/dashboard?lat={ATHENS[0]}&lng={ATHENS[1]}&radius=12.3"
        ).get_data(as_text=True)
        selected = re.findall(r"<option[^>]*\bselected\b[^>]*>([^<]*)</option>", body)
        assert selected == ["within 12.3 km"]


class TestYourGames:
    def test_it_lists_hosted_and_joined_games_upcoming_first(
        self, db, login, user_factory, court_factory, game_factory
    ):
        me = user_factory()
        other = user_factory()
        hosting = game_factory(court=court_factory(name="Hosting Court", created_by=me.id),
                               host=me, when=utcnow() + timedelta(days=2))
        joined = game_factory(court=court_factory(name="Joined Court", lat=34.0, created_by=me.id),
                              host=other, players=[me], when=utcnow() + timedelta(days=1))
        played = game_factory(court=court_factory(name="Played Court", lat=34.1, created_by=me.id),
                              host=other, players=[me], when=utcnow() - timedelta(days=1))
        not_mine = game_factory(court=court_factory(name="Other Court", lat=34.2, created_by=me.id),
                                host=other, when=utcnow() - timedelta(days=2))

        body = login(me).get("/dashboard").get_data(as_text=True)
        mine = body[body.index('id="mine-title"'):body.index('id="feed-title"')]
        assert mine.index(f'href="/games/{joined.id}"') < mine.index(f'href="/games/{hosting.id}"')
        assert mine.index(f'href="/games/{hosting.id}"') < mine.index(f'href="/games/{played.id}"')
        assert f'href="/games/{not_mine.id}"' not in mine
        assert "Played" in mine
        assert 'href="/games/mine"' in mine

    def test_a_host_on_their_own_roster_is_listed_once(
        self, db, login, user_factory, game_factory
    ):
        """Hosting may add the host to the roster; the game must not show twice."""
        me = user_factory()
        game = game_factory(host=me, players=[me])
        body = login(me).get("/dashboard").get_data(as_text=True)
        mine = body[body.index('id="mine-title"'):body.index('id="feed-title"')]
        assert mine.count(f'href="/games/{game.id}"') == 1

    def test_with_no_games_it_points_to_finding_or_hosting_one(self, db, login, user_factory):
        body = login(user_factory()).get("/dashboard").get_data(as_text=True)
        mine = body[body.index('id="mine-title"'):body.index('id="feed-title"')]
        assert "No games yet" in mine
        assert "data-near-me" in mine
        assert 'href="/games/create"' in mine

    def test_it_only_opens_the_unscoped_panel(
        self, db, login, user_factory, court_factory
    ):
        court = court_factory()
        body = _feed(login(user_factory()), f"?court={court.id}")
        assert 'id="mine-title"' not in body


class TestMyGamesPage:
    def test_it_splits_upcoming_from_played(
        self, db, login, user_factory, court_factory, game_factory
    ):
        me = user_factory()
        other = user_factory()
        upcoming = game_factory(host=other, players=[me], when=utcnow() + timedelta(days=1))
        hosted = game_factory(host=me, when=utcnow() + timedelta(days=2))
        played = game_factory(host=other, players=[me], when=utcnow() - timedelta(days=1))
        not_mine = game_factory(host=other, when=utcnow() + timedelta(days=1))

        body = login(me).get("/games/mine").get_data(as_text=True)
        played_at = body.index('id="played-title"')
        assert 0 < body.index(f'href="/games/{upcoming.id}"') < played_at
        assert 0 < body.index(f'href="/games/{hosted.id}"') < played_at
        assert body.index(f'href="/games/{played.id}"') > played_at
        assert f'href="/games/{not_mine.id}"' not in body

    def test_played_games_page(self, db, login, user_factory, game_factory):
        from app.blueprints.games import PAGE_SIZE

        me = user_factory()
        for days in range(PAGE_SIZE + 2):
            game_factory(host=me, when=utcnow() - timedelta(days=days + 1))
        client = login(me)
        assert "Page 1 of 2" in client.get("/games/mine").get_data(as_text=True)
        assert "Page 2 of 2" in client.get("/games/mine?page=2").get_data(as_text=True)

    def test_an_empty_schedule_points_back_to_the_map(self, db, login, user_factory):
        body = login(user_factory()).get("/games/mine").get_data(as_text=True)
        assert "Nothing booked" in body
        assert 'href="/dashboard"' in body

    def test_it_requires_login(self, client):
        assert client.get("/games/mine").status_code == 302


class TestRosterRedirects:
    @pytest.mark.parametrize("action", ["join", "leave"])
    def test_it_returns_to_the_page_it_came_from(
        self, db, login, user_factory, game_factory, action
    ):
        me = user_factory()
        game = game_factory(players=[me] if action == "leave" else [])
        response = login(me).post(
            f"/games/{game.id}/{action}", data={"next": "/dashboard?court=3"}
        )
        assert response.status_code == 302
        assert response.headers["Location"] == "/dashboard?court=3"

    @pytest.mark.parametrize(
        "target",
        [
            "https://evil.example/",
            "//evil.example/",
            "/\\evil.example/",
            "/\t/evil.example/",
            "javascript:alert(1)",
            "dashboard",
            "",
        ],
    )
    def test_it_will_not_redirect_off_site(self, db, login, user_factory, game_factory, target):
        game = game_factory()
        response = login(user_factory()).post(f"/games/{game.id}/join", data={"next": target})
        assert response.status_code == 302
        assert response.headers["Location"] == "/games"

    def test_a_refused_join_also_returns(self, db, login, user_factory, game_factory):
        me = user_factory()
        game = game_factory(max_players=2, players=[user_factory(), user_factory()])
        response = login(me).post(f"/games/{game.id}/join", data={"next": f"/games/{game.id}"})
        assert response.headers["Location"] == f"/games/{game.id}"
        assert db.session.get(GamePlayer, (game.id, me.id)) is None


class TestGamePage:
    def test_a_visitor_can_join_from_the_game_page(self, db, login, user_factory, game_factory):
        game = game_factory()
        body = login(user_factory()).get(f"/games/{game.id}").get_data(as_text=True)
        assert f'action="/games/{game.id}/join"' in body
        assert f'name="next" value="/games/{game.id}"' in body

    def test_a_player_can_leave_from_the_game_page(self, db, login, user_factory, game_factory):
        me = user_factory()
        game = game_factory(players=[me])
        body = login(me).get(f"/games/{game.id}").get_data(as_text=True)
        assert f'action="/games/{game.id}/leave"' in body
        assert f'action="/games/{game.id}/join"' not in body

    def test_a_full_game_says_so(self, db, login, user_factory, game_factory):
        game = game_factory(max_players=2, players=[user_factory(), user_factory()])
        body = login(user_factory()).get(f"/games/{game.id}").get_data(as_text=True)
        assert "This game is full." in body
        assert f'action="/games/{game.id}/join"' not in body

    def test_the_host_is_marked_on_the_roster(self, db, login, user_factory, game_factory):
        host = user_factory(username="the-host")
        game = game_factory(host=host, players=[host])
        body = login(user_factory()).get(f"/games/{game.id}").get_data(as_text=True)
        roster = body[body.index('id="roster-title"'):]
        assert "the-host" in roster
        assert '<span class="tag">Host</span>' in roster


class TestHostAndCourtFlows:
    def test_hosting_from_a_court_preselects_it(self, db, login, user_factory, court_factory):
        court = court_factory()
        client = login(user_factory())
        body = client.get(f"/games/create?court_id={court.id}").get_data(as_text=True)
        assert f'<option value="{court.id}" selected>' in body

    def test_the_host_form_posts_back_to_itself(self, db, login, user_factory):
        """The submission path is unchanged: the form posts to /games/create."""
        body = login(user_factory()).get("/games/create").get_data(as_text=True)
        assert '<form method="POST" class="form-card">' in body
        for name in ("court_id", "time", "max_players"):
            assert f'name="{name}"' in body

    def test_a_new_court_opens_on_the_map(self, db, login, user_factory):
        client = login(user_factory())
        response = client.post(
            "/courts/create",
            data={"name": "Fresh Court", "address": "1 New St", "lat": "33.95", "lng": "-83.37"},
        )
        court = db.session.query(Court).filter_by(name="Fresh Court").one()
        assert response.status_code == 302
        assert response.headers["Location"] == f"/dashboard?court={court.id}"

    def test_the_courts_page_counts_upcoming_games(
        self, db, login, user_factory, court_factory, game_factory
    ):
        host = user_factory()
        court = court_factory(name="Counted Court", created_by=host.id)
        game_factory(court=court, host=host)
        game_factory(court=court, host=host)
        body = login(host).get("/courts").get_data(as_text=True)
        assert "2 upcoming" in body
        assert f'href="/dashboard?court={court.id}"' in body


class TestRelativeDays:
    @pytest.mark.parametrize(
        "offset,expected",
        [(0, "Today"), (1, "Tomorrow"), (-1, "Yesterday")],
    )
    def test_near_days_are_named(self, app, offset, expected):
        from app.timeutils import to_utc

        with app.test_request_context():
            noon = datetime.combine(
                utcnow().date() + timedelta(days=offset), datetime.min.time()
            ).replace(hour=12)
            assert app.jinja_env.filters["relday"](to_utc(noon)) == expected

    def test_other_days_are_short_dates(self, app):
        with app.test_request_context():
            value = datetime(2099, 7, 4, 12, 0, tzinfo=UTC)
            assert app.jinja_env.filters["relday"](value) == "Sat 4 Jul"


class TestSignedOutPage:
    def test_a_failed_sign_up_reopens_the_sign_up_tab(self, client):
        body = client.post(
            "/register", data={"username": "ab", "email": "x@example.test", "password": "short"}
        ).get_data(as_text=True)
        assert 'id="tab-register" class="auth-tabs__radio" checked' in body

    def test_logging_in_is_the_default_tab(self, client):
        body = client.get("/").get_data(as_text=True)
        assert 'id="tab-login" class="auth-tabs__radio" checked' in body


class TestLeaderboardTabs:
    def test_every_metric_is_one_click_away(self, db, login, user_factory):
        body = login(user_factory()).get("/leaderboard?metric=assists").get_data(as_text=True)
        for metric in ("points", "rebounds", "assists", "ppg"):
            assert f'href="/leaderboard?metric={metric}"' in body
        current = re.findall(r'<a href="/leaderboard\?metric=(\w+)"[^>]*aria-current="page"', body)
        assert current == ["assists"]
