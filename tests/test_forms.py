"""Server-side input validation.

Validation used to be hand-rolled in the views: `if not all([...])` followed by
bare float()/int() calls in try blocks. These tests pin the behaviour that
replaced it.
"""

import pytest

from app.models import Court


def test_court_at_the_origin_is_accepted(login, user_factory, db):
    """lat=0/lng=0 is a real place, not a missing value.

    The forms use InputRequired rather than DataRequired precisely because
    DataRequired treats 0.0 as absent -- the same class of bug as the nearby
    search rejecting the equator.
    """
    client = login(user_factory())
    response = client.post(
        "/courts/create",
        data={"name": "Null Island", "address": "0,0", "lat": "0", "lng": "0"},
        follow_redirects=False,
    )
    assert response.status_code == 302, "court at (0, 0) was rejected"
    court = db.session.query(Court).filter_by(name="Null Island").one()
    assert (court.lat, court.lng) == (0.0, 0.0)


@pytest.mark.parametrize(
    "lat,lng,why",
    [
        ("91", "0", "latitude above 90"),
        ("-91", "0", "latitude below -90"),
        ("0", "181", "longitude above 180"),
        ("0", "-181", "longitude below -180"),
        ("abc", "0", "non-numeric latitude"),
        ("", "0", "empty latitude"),
    ],
)
def test_out_of_range_coordinates_are_rejected(login, user_factory, db, lat, lng, why):
    client = login(user_factory())
    response = client.post(
        "/courts/create",
        data={"name": "Bad Court", "address": "somewhere", "lat": lat, "lng": lng},
    )
    assert response.status_code == 200, f"{why} should re-render the form, not redirect"
    assert db.session.query(Court).filter_by(name="Bad Court").count() == 0


def test_short_passwords_are_rejected(client):
    response = client.post("/register", data={"username": "shorty", "password": "abc"})
    assert response.status_code == 200
    assert "at least 10 characters" in response.get_data(as_text=True)


def test_usernames_with_html_are_rejected(client):
    response = client.post(
        "/register", data={"username": "<script>x</script>", "password": "long-enough-pw"}
    )
    assert response.status_code == 200
    assert "letters, numbers" in response.get_data(as_text=True)


def test_valid_registration_succeeds(client):
    response = client.post(
        "/register", data={"username": "newplayer", "password": "long-enough-pw"}
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_max_players_out_of_range_is_rejected(login, user_factory, court_factory, db):
    from app.models import Game

    user = user_factory()
    court = court_factory(created_by=user.id)
    client = login(user)
    response = client.post(
        "/games/create",
        data={"court_id": str(court.id), "time": "2099-01-01T18:00", "max_players": "999"},
    )
    assert response.status_code == 200
    assert db.session.query(Game).count() == 0


def test_game_creation_with_valid_input(login, user_factory, court_factory, db):
    from app.models import Game

    user = user_factory()
    court = court_factory(created_by=user.id)
    client = login(user)
    response = client.post(
        "/games/create",
        data={"court_id": str(court.id), "time": "2099-01-01T18:00", "max_players": "10"},
    )
    assert response.status_code == 302
    game = db.session.query(Game).one()
    assert game.max_players == 10
    assert game.time.year == 2099
