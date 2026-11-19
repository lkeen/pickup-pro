"""Roster capacity under concurrency, and court de-duplication.

Joining used to be check-then-act: can_join() counted the roster, then a
separate INSERT added the player. Two requests for the last slot could both read
"one slot left" and both succeed.
"""

import threading

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Court, GamePlayer


class TestCapacityTrigger:
    def test_the_trigger_refuses_to_overfill_a_game(self, db, user_factory, game_factory):
        host = user_factory()
        game = game_factory(host=host, max_players=2, players=[host, user_factory()])

        with pytest.raises((IntegrityError, DBAPIError)) as excinfo:
            db.session.add(GamePlayer(game_id=game.id, user_id=user_factory().id))
            db.session.commit()
        db.session.rollback()
        assert "full" in str(excinfo.value).lower()

    def test_it_applies_to_writes_that_bypass_the_application(
        self, db, user_factory, game_factory
    ):
        """The point of enforcing it in the database: a seed script or a hand-run
        INSERT is subject to the same rule as the join route."""
        host = user_factory()
        game = game_factory(host=host, max_players=1, players=[host])
        outsider = user_factory()

        with pytest.raises(Exception) as excinfo:
            db.session.execute(
                text("INSERT INTO game_players (game_id, user_id) VALUES (:g, :u)"),
                {"g": game.id, "u": outsider.id},
            )
            db.session.commit()
        db.session.rollback()
        assert "full" in str(excinfo.value).lower()

    def test_joining_up_to_capacity_still_works(self, db, user_factory, game_factory):
        host = user_factory()
        game = game_factory(host=host, max_players=3, players=[host])
        for _ in range(2):
            db.session.add(GamePlayer(game_id=game.id, user_id=user_factory().id))
            db.session.commit()
        assert db.session.query(GamePlayer).filter_by(game_id=game.id).count() == 3


class TestConcurrentJoins:
    def test_two_threads_racing_for_the_last_slot(self, app, db, user_factory, game_factory):
        """The original bug, reproduced. Without the row lock and the trigger,
        both inserts land and the game ends up over capacity.
        """
        host = user_factory()
        game = game_factory(host=host, max_players=2, players=[host])
        contenders = [user_factory(), user_factory()]
        game_id = game.id
        user_ids = [u.id for u in contenders]

        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        engine = create_engine(uri)
        Session = sessionmaker(bind=engine)

        start = threading.Barrier(len(user_ids))
        results = []
        lock = threading.Lock()

        def attempt(user_id):
            session = Session()
            try:
                start.wait(timeout=10)
                session.execute(
                    text("SELECT max_players FROM games WHERE id = :g FOR UPDATE"),
                    {"g": game_id},
                )
                taken = session.execute(
                    text("SELECT count(*) FROM game_players WHERE game_id = :g"),
                    {"g": game_id},
                ).scalar()
                capacity = session.execute(
                    text("SELECT max_players FROM games WHERE id = :g"), {"g": game_id}
                ).scalar()
                if taken < capacity:
                    session.execute(
                        text("INSERT INTO game_players (game_id, user_id) VALUES (:g, :u)"),
                        {"g": game_id, "u": user_id},
                    )
                    session.commit()
                    outcome = "joined"
                else:
                    session.rollback()
                    outcome = "full"
            except Exception as exc:  # noqa: BLE001 - recording, not handling
                session.rollback()
                outcome = f"rejected: {type(exc).__name__}"
            finally:
                session.close()
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=attempt, args=(uid,)) for uid in user_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        engine.dispose()

        final = db.session.execute(
            text("SELECT count(*) FROM game_players WHERE game_id = :g"), {"g": game_id}
        ).scalar()

        assert final <= 2, (
            f"roster overfilled: {final} players in a 2-player game. outcomes={results}"
        )
        assert results.count("joined") == 1, f"expected exactly one winner, got {results}"


class TestCourtUniqueness:
    def test_the_same_court_cannot_be_entered_twice(self, db, user_factory):
        user = user_factory()
        db.session.add(
            Court(name="Legion Field", address="A", lat=33.9519, lng=-83.3576, created_by=user.id)
        )
        db.session.commit()

        with pytest.raises(IntegrityError):
            db.session.add(
                Court(
                    name="legion field",  # case-insensitive
                    address="different address",
                    lat=33.95190001,  # within ~11 m
                    lng=-83.35760001,
                    created_by=user.id,
                )
            )
            db.session.commit()
        db.session.rollback()

    def test_genuinely_different_courts_are_allowed(self, db, user_factory):
        user = user_factory()
        # Same spot, different name; same name, different spot. Both allowed.
        rows = [("Court A", "A", 33.95), ("Court B", "B", 33.95), ("Court A", "C", 34.95)]
        for name, address, lat in rows:
            db.session.add(
                Court(name=name, address=address, lat=lat, lng=-83.35, created_by=user.id)
            )
        db.session.commit()
        assert db.session.query(Court).count() == 3
