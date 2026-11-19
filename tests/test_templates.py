"""Rendering safety and the shared layout.

The stat and rating buttons used to interpolate a username and a free-text
comment into an onclick attribute -- a JavaScript string literal inside an HTML
attribute. Jinja escapes for HTML, not for JS string context, so a comment with a
backslash in it broke the call.
"""

import re
from datetime import UTC

import pytest

from app.models import PlayerRating


class TestNoInlineHandlers:
    def test_the_game_page_has_no_onclick_attributes(
        self, db, login, user_factory, game_factory
    ):
        host = user_factory()
        game = game_factory(host=host, players=[host, user_factory()])
        client = login(host)
        body = client.get(f"/games/{game.id}").get_data(as_text=True)
        assert "onclick=" not in body

    @pytest.mark.parametrize(
        "comment",
        [
            r"back\slash",
            r"quote' and \' escaped",
            '</script><script>alert(1)</script>',
            'line\nbreak',
            '"double" quotes',
        ],
    )
    def test_hostile_comments_render_without_breaking_the_page(
        self, db, login, user_factory, game_factory, comment
    ):
        """Each of these previously corrupted the generated JavaScript."""
        host = user_factory()
        other = user_factory()
        game = game_factory(host=host, players=[host, other])
        db.session.add(
            PlayerRating(
                game_id=game.id,
                from_user_id=host.id,
                to_user_id=other.id,
                rating=3,
                comment=comment,
            )
        )
        db.session.commit()

        client = login(host)
        response = client.get(f"/games/{game.id}")
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        # The payload must not escape into executable context.
        assert "<script>alert(1)</script>" not in body
        assert "onclick=" not in body

    def test_a_hostile_username_is_escaped(self, db, login, user_factory, game_factory):
        host = user_factory()
        game = game_factory(host=host, players=[host])
        client = login(host)
        body = client.get(f"/games/{game.id}").get_data(as_text=True)
        assert "<script>" not in body.replace(
            '<script src="/static/js/modals.js" defer></script>', ""
        )


class TestLayout:
    def test_every_page_loads_the_stylesheet(self, db, login, user_factory):
        client = login(user_factory())
        for path in ["/dashboard", "/games", "/courts", "/leaderboard"]:
            body = client.get(path).get_data(as_text=True)
            assert "css/main.css" in body, f"{path} has no stylesheet"

    def test_the_page_title_is_specific(self, db, login, user_factory):
        client = login(user_factory())
        body = client.get("/games").get_data(as_text=True)
        assert "<title>Games - Pickup Pro</title>" in body
        assert "Flask Authentication" not in body

    def test_logout_in_the_nav_carries_a_csrf_token(self, db, login, user_factory):
        """The nav renders a logout form on every page, including ones whose
        view passes no form object."""
        client = login(user_factory())
        body = client.get("/games").get_data(as_text=True)
        assert 'name="csrf_token"' in body

    @pytest.mark.parametrize(
        "path,label",
        [("/dashboard", ">Map</a>"), ("/games/mine", ">My games</a>")],
    )
    def test_the_nav_marks_the_current_section(self, db, login, user_factory, path, label):
        client = login(user_factory())
        body = client.get(path).get_data(as_text=True)
        nav = body[body.index('<nav class="topnav"'):body.index("</nav>")]
        current = re.search(r'<a [^>]*aria-current="page"[^>]*>[^<]*</a>', nav)
        assert current, f"nothing in the nav is marked current on {path}"
        assert current.group(0).endswith(label)

    def test_secondary_pages_sit_in_the_account_menu(self, db, login, user_factory):
        """Leaderboard, profile and courts stay one tap away without crowding
        the bar."""
        user = user_factory()
        body = login(user).get("/dashboard").get_data(as_text=True)
        menu = body[body.index('<details class="menu">'):body.index("</details>")]
        for href in (f"/users/{user.id}", "/leaderboard", "/courts", "/courts/create", "/games"):
            assert f'href="{href}"' in menu, f"{href} is missing from the account menu"
        assert "Log out" in menu

    def test_hosting_is_one_tap_from_every_page(self, db, login, user_factory):
        client = login(user_factory())
        for path in ["/dashboard", "/games", "/games/mine", "/leaderboard", "/courts"]:
            body = client.get(path).get_data(as_text=True)
            topbar = body[body.index('<header class="topbar">'):body.index("</header>")]
            assert 'href="/games/create"' in topbar, f"no host button on {path}"

    def test_anonymous_pages_show_no_nav(self, client):
        body = client.get("/").get_data(as_text=True)
        assert "Log out" not in body


class TestLocalTimeFilter:
    def test_times_render_in_the_configured_zone(
        self, db, app, login, user_factory, court_factory, game_factory
    ):
        """Templates used to call .strftime() straight on the column, printing
        UTC and calling it local."""
        from datetime import datetime

        app.config["APP_TIMEZONE"] = "America/New_York"
        try:
            host = user_factory()
            court = court_factory(created_by=host.id)
            # 22:00 UTC on a summer date is 18:00 in New York.
            game_factory(
                court=court,
                host=host,
                when=datetime(2099, 7, 4, 22, 0, tzinfo=UTC),
            )
            client = login(host)
            body = client.get("/games").get_data(as_text=True)
            assert "18:00" in body
            assert "22:00" not in body
        finally:
            app.config["APP_TIMEZONE"] = "UTC"
