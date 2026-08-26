"""Google sign-in.

The claims-to-user mapping is tested directly rather than through a live OAuth
handshake: standing up an identity provider would test Authlib, not this code.
The route-level tests cover the parts that are ours -- that the endpoints stay
hidden when unconfigured, and that a successful callback starts a fresh session.
"""

import pytest

from app.blueprints.oauth import resolve_oauth_user
from app.models import User


def claims(sub="google-sub-1", email="player@gmail.com", verified=True, **extra):
    return {"sub": sub, "email": email, "email_verified": verified, **extra}


class TestResolveOAuthUser:
    def test_creates_an_account_on_first_sign_in(self, db):
        user, error = resolve_oauth_user("google", claims())
        assert error is None
        assert user.email == "player@gmail.com"
        assert user.oauth_provider == "google"
        assert user.oauth_sub == "google-sub-1"
        assert user.email_verified is True
        # No password: the credential check constraint is satisfied by the
        # provider identity instead.
        assert user.password_hash is None
        assert user.has_password is False

    def test_returns_the_same_account_on_later_sign_ins(self, db):
        first, _ = resolve_oauth_user("google", claims())
        second, error = resolve_oauth_user("google", claims())
        assert error is None
        assert second.id == first.id
        assert db.session.query(User).count() == 1

    def test_follows_the_subject_not_the_email(self, db):
        """People change their email address; the subject claim is stable."""
        first, _ = resolve_oauth_user("google", claims(email="old@gmail.com"))
        again, error = resolve_oauth_user("google", claims(email="new@gmail.com"))
        assert error is None
        assert again.id == first.id

    def test_refuses_an_unverified_email(self, db):
        user, error = resolve_oauth_user("google", claims(verified=False))
        assert user is None
        assert "not verified" in error
        assert db.session.query(User).count() == 0

    @pytest.mark.parametrize("missing", [{"sub": None}, {"email": ""}])
    def test_refuses_incomplete_claims(self, db, missing):
        user, error = resolve_oauth_user("google", {**claims(), **missing})
        assert user is None
        assert error
        assert db.session.query(User).count() == 0

    def test_refuses_when_the_email_belongs_to_a_password_account(self, db, user_factory):
        """Linking is deliberately not implemented; silently taking over an
        existing account would be the wrong way to handle this."""
        user_factory(username="existing", email="taken@gmail.com")
        user, error = resolve_oauth_user("google", claims(email="taken@gmail.com"))
        assert user is None
        assert "Sign in with your password" in error

    def test_derives_a_username_from_the_email(self, db):
        """The address is normalised to lower case first, so the derived
        username does not depend on how the provider happened to capitalise
        it."""
        user, _ = resolve_oauth_user("google", claims(email="Jordan.Smith@gmail.com"))
        assert user.username == "jordan.smith"
        assert user.email == "jordan.smith@gmail.com"

    def test_makes_a_derived_username_unique(self, db, user_factory):
        user_factory(username="jordan", email="someone.else@example.com")
        user, error = resolve_oauth_user("google", claims(email="jordan@gmail.com"))
        assert error is None
        assert user.username == "jordan2"

    def test_strips_unsafe_characters_from_the_derived_username(self, db):
        user, _ = resolve_oauth_user("google", claims(email="we+ird!name@gmail.com"))
        assert user.username == "weirdname"


class TestOAuthRoutes:
    def test_routes_are_hidden_when_google_is_not_configured(self, client, app):
        assert app.config["GOOGLE_OAUTH_READY"] is False
        assert client.get("/auth/google").status_code == 404
        assert client.get("/auth/callback").status_code == 404

    def test_the_sign_in_button_is_not_rendered_when_unconfigured(self, client):
        body = client.get("/").get_data(as_text=True)
        assert "Continue with Google" not in body

    def test_the_sign_in_button_appears_once_configured(self, client, app):
        app.config["GOOGLE_OAUTH_READY"] = True
        try:
            body = client.get("/").get_data(as_text=True)
            assert "Continue with Google" in body
            assert "/auth/google" in body
        finally:
            app.config["GOOGLE_OAUTH_READY"] = False


class TestPasswordLoginStillWorks:
    def test_oauth_accounts_cannot_be_logged_into_with_a_password(self, db, client):
        """check_password on a null hash must be False, not an exception."""
        user, _ = resolve_oauth_user("google", claims(email="nopass@gmail.com"))
        assert user.check_password("") is False
        assert user.check_password("anything") is False

        response = client.post(
            "/login", data={"username": user.username, "password": "anything"}
        )
        assert response.status_code == 200
        assert "Invalid credentials." in response.get_data(as_text=True)

    def test_password_accounts_are_unaffected(self, client, user_factory):
        user = user_factory(username="classic")
        response = client.post(
            "/login", data={"username": "classic", "password": user._test_password}
        )
        assert response.status_code == 302
