"""End-to-end smoke tests: every page renders and auth is actually enforced.

The value here is regression cover for the blueprint split -- a broken url_for
is a runtime error that only surfaces when a template is rendered.
"""

import pytest

# Every GET route, and whether it needs a logged-in user.
PAGES = [
    ("/", False),
    ("/dashboard", True),
    ("/courts", True),
    ("/courts/create", True),
    ("/games", True),
    ("/games/create", True),
]


@pytest.mark.parametrize("path,requires_login", PAGES)
def test_pages_render_for_a_logged_in_user(login, user_factory, path, requires_login):
    client = login(user_factory())
    response = client.get(path)
    assert response.status_code in (200, 302), response.get_data(as_text=True)[:500]


@pytest.mark.parametrize("path,requires_login", [p for p in PAGES if p[1]])
def test_protected_pages_redirect_anonymous_users(client, path, requires_login):
    response = client.get(path)
    assert response.status_code == 302
    assert "/" in response.headers["Location"]


def test_landing_page_renders_for_anonymous_users(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Log in" in body
    assert "Create an account" in body


def test_game_detail_renders(login, user_factory, game_factory):
    host = user_factory()
    game = game_factory(host=host, players=[host])
    client = login(host)
    response = client.get(f"/games/{game.id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Roster" in body
    assert host.username in body
    assert game.court.name in body


def test_profile_renders_with_no_stats(login, user_factory):
    user = user_factory()
    client = login(user)
    response = client.get(f"/users/{user.id}")
    assert response.status_code == 200
    assert "No game statistics available yet." in response.get_data(as_text=True)


def test_missing_game_is_404_not_500(login, user_factory):
    client = login(user_factory())
    assert client.get("/games/999999").status_code == 404


def test_login_with_valid_credentials(client, user_factory):
    user_factory(username="alice", password="s3cret-passphrase")
    response = client.post("/login", data={"username": "alice", "password": "s3cret-passphrase"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_login_with_wrong_password_is_rejected(client, user_factory):
    user_factory(username="bob", password="s3cret-passphrase")
    response = client.post("/login", data={"username": "bob", "password": "wrong"})
    assert response.status_code == 200
    assert "Invalid credentials." in response.get_data(as_text=True)
