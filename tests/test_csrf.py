"""CSRF protection.

Before this branch, POST /login with no token returned 200 -- every
state-changing endpoint in the app could be driven from another origin.
"""

import pytest

from tests.conftest import csrf_token_from

# Every state-changing endpoint, with a body that would otherwise be valid.
STATE_CHANGING = [
    ("/login", {"username": "someone", "password": "irrelevant"}),
    ("/register", {"username": "newcomer", "password": "long-enough-pw"}),
    ("/logout", {}),
    ("/courts/create", {"name": "X", "address": "Y", "lat": "1", "lng": "2"}),
    ("/games/1/join", {}),
    ("/games/1/leave", {}),
    ("/games/1/stats", {"user_id": "1", "points": "1", "rebounds": "1", "assists": "1"}),
    ("/games/1/rate", {"to_user_id": "1", "rating": "5"}),
]


@pytest.mark.parametrize("path,data", STATE_CHANGING)
def test_post_without_a_token_is_rejected(csrf_client, user_factory, path, data):
    user = user_factory()
    with csrf_client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True

    response = csrf_client.post(path, data=data)
    assert response.status_code == 400, (
        f"{path} accepted a POST with no CSRF token (got {response.status_code})"
    )


def test_post_with_a_valid_token_succeeds(csrf_client, user_factory):
    user_factory(username="tokenuser", password="long-enough-pw")
    token = csrf_token_from(csrf_client.get("/").get_data(as_text=True))

    response = csrf_client.post(
        "/login",
        data={"username": "tokenuser", "password": "long-enough-pw", "csrf_token": token},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_a_token_from_another_session_is_rejected(csrf_client, app, user_factory):
    user_factory(username="victim", password="long-enough-pw")
    stolen = csrf_token_from(csrf_client.get("/").get_data(as_text=True))

    other = app.test_client()  # different session cookie
    response = other.post(
        "/login",
        data={"username": "victim", "password": "long-enough-pw", "csrf_token": stolen},
    )
    assert response.status_code == 400


def test_logout_is_not_reachable_by_GET(client, login, user_factory):
    """A GET logout can be fired by any page embedding <img src="/logout">."""
    client = login(user_factory())
    assert client.get("/logout").status_code == 405


def test_logout_via_post_ends_the_session(client, login, user_factory):
    user = user_factory()
    client = login(user)
    assert client.get("/dashboard").status_code == 200

    response = client.post("/logout")
    assert response.status_code == 302

    # Session is gone: a protected page now redirects to the landing page.
    assert client.get("/dashboard").status_code == 302


def test_every_state_changing_route_is_a_post(app):
    """No route that mutates data should be reachable by GET."""
    mutating = {"/logout", "/login", "/register"}
    for rule in app.url_map.iter_rules():
        if rule.rule in mutating:
            assert "GET" not in rule.methods, f"{rule.rule} is still reachable by GET"
