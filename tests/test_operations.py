"""Health check and the seed command."""

from app.models import Court, Game, User


class TestHealthCheck:
    def test_it_reports_ok(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok"}

    def test_it_needs_no_authentication(self, client):
        """A load balancer has no session."""
        assert client.get("/healthz").status_code == 200

    def test_it_checks_the_database_not_just_the_process(self, client):
        """A process that cannot reach its database should not be sent traffic."""
        from app.extensions import db

        original = db.session.execute

        def explode(*args, **kwargs):
            raise RuntimeError("database is gone")

        # Restored by hand rather than with monkeypatch: the db fixture's
        # teardown also runs queries, and it tears down after monkeypatch would
        # have undone this.
        db.session.execute = explode
        try:
            response = client.get("/healthz")
        finally:
            db.session.execute = original

        assert response.status_code == 503
        assert response.get_json()["status"] == "unhealthy"


class TestSeedCommand:
    def test_it_populates_an_empty_database(self, app, db):
        runner = app.test_cli_runner()
        result = runner.invoke(args=["seed"])
        assert result.exit_code == 0, result.output

        assert db.session.query(User).count() > 0
        assert db.session.query(Court).count() > 0
        assert db.session.query(Game).count() > 0

    def test_it_refuses_to_overwrite_without_force(self, app, db, user_factory):
        user_factory()
        runner = app.test_cli_runner()
        result = runner.invoke(args=["seed"])
        assert "already has data" in result.output
        assert db.session.query(User).count() == 1

    def test_force_replaces_existing_data(self, app, db, user_factory):
        user_factory(username="survivor")
        runner = app.test_cli_runner()
        result = runner.invoke(args=["seed", "--force"])
        assert result.exit_code == 0, result.output
        assert db.session.query(User).filter_by(username="survivor").count() == 0

    def test_seeded_games_include_past_and_future(self, app, db):
        """Past games can carry stats; future ones show up in search. A dataset
        with only one kind leaves half the app looking empty."""
        from app.timeutils import utcnow

        app.test_cli_runner().invoke(args=["seed"])
        now = utcnow()
        assert db.session.query(Game).filter(Game.time < now).count() > 0
        assert db.session.query(Game).filter(Game.time >= now).count() > 0

    def test_seeded_courts_get_a_geography(self, app, db):
        from sqlalchemy import text

        app.test_cli_runner().invoke(args=["seed"])
        nulls = db.session.execute(
            text("SELECT count(*) FROM courts WHERE geog IS NULL")
        ).scalar()
        assert nulls == 0

    def test_seeded_rosters_respect_capacity(self, app, db):
        """The capacity trigger applies to the seed command too -- if it did
        not, this command would be the write path that proves the point."""
        from sqlalchemy import text

        app.test_cli_runner().invoke(args=["seed"])
        over = db.session.execute(
            text(
                "SELECT count(*) FROM ("
                "  SELECT gp.game_id FROM game_players gp"
                "  JOIN games g ON g.id = gp.game_id"
                "  GROUP BY gp.game_id, g.max_players"
                "  HAVING count(*) > g.max_players"
                ") x"
            )
        ).scalar()
        assert over == 0

    def test_it_is_deterministic(self, app, db):
        """A fixed seed means screenshots and demos stay stable."""
        runner = app.test_cli_runner()
        runner.invoke(args=["seed", "--force"])
        first = [
            (g.court_id, g.max_players)
            for g in db.session.query(Game).order_by(Game.time).all()
        ]
        runner.invoke(args=["seed", "--force"])
        second = [
            (g.court_id, g.max_players)
            for g in db.session.query(Game).order_by(Game.time).all()
        ]
        assert [m for _, m in first] == [m for _, m in second]
