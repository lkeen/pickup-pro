"""Enforce roster capacity in the database, and de-duplicate courts

Joining a game was check-then-act: can_join() counted the roster, and a separate
INSERT added the player. Two requests for the last slot could both read "one
slot left" and both insert, putting the game over capacity with nothing to stop
it.

The application now takes a row lock, which is the primary fix. This adds the
backstop: the invariant is enforced by the database, so it holds for every write
path -- a seed script, a fixture, someone in psql -- not only the one route that
remembers to lock.

Revision ID: e4f7b2a19c83
Revises: a8940ffb16a6
Create Date: 2026-08-26 19:30:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e4f7b2a19c83'
down_revision = 'a8940ffb16a6'
branch_labels = None
depends_on = None

# A CHECK constraint cannot do this: it sees only the row being written and
# cannot count sibling rows. A trigger can.
#
# The SELECT ... FOR UPDATE inside the trigger is what makes it correct rather
# than merely likely to work. Without it, two concurrent inserts each run the
# count before either commits, both see room, and both succeed. Locking the
# games row serialises them: the second waits, then counts again and sees the
# first.
CAPACITY_FUNCTION = """
CREATE OR REPLACE FUNCTION enforce_roster_capacity() RETURNS trigger AS $$
DECLARE
    capacity integer;
    taken integer;
BEGIN
    SELECT max_players INTO capacity FROM games WHERE id = NEW.game_id FOR UPDATE;

    IF capacity IS NULL THEN
        RETURN NEW;  -- no such game; the foreign key will reject it
    END IF;

    SELECT count(*) INTO taken FROM game_players WHERE game_id = NEW.game_id;

    IF taken >= capacity THEN
        RAISE EXCEPTION 'game % is full (capacity %)', NEW.game_id, capacity
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

CAPACITY_TRIGGER = """
CREATE TRIGGER game_players_capacity
BEFORE INSERT ON game_players
FOR EACH ROW EXECUTE FUNCTION enforce_roster_capacity();
"""

# Same court entered twice produces two sets of games nobody can see together.
# Rounded to four decimal places -- about 11 metres -- because two people typing
# coordinates for the same court will not agree to the last float digit.
COURT_UNIQUENESS = """
CREATE UNIQUE INDEX uq_courts_name_location
ON courts (lower(name), round(lat::numeric, 4), round(lng::numeric, 4));
"""


def upgrade():
    op.execute(CAPACITY_FUNCTION)
    op.execute(CAPACITY_TRIGGER)

    # Collapse any duplicates already present, keeping the earliest, before the
    # unique index can be built.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY lower(name),
                                    round(lat::numeric, 4),
                                    round(lng::numeric, 4)
                       ORDER BY id
                   ) AS position,
                   first_value(id) OVER (
                       PARTITION BY lower(name),
                                    round(lat::numeric, 4),
                                    round(lng::numeric, 4)
                       ORDER BY id
                   ) AS keep_id
            FROM courts
        )
        UPDATE games SET court_id = ranked.keep_id
        FROM ranked
        WHERE games.court_id = ranked.id AND ranked.position > 1
        """
    )
    op.execute(
        """
        DELETE FROM courts WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY lower(name),
                                 round(lat::numeric, 4),
                                 round(lng::numeric, 4)
                    ORDER BY id
                ) AS position
                FROM courts
            ) d WHERE position > 1
        )
        """
    )
    op.execute(COURT_UNIQUENESS)


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_courts_name_location")
    op.execute("DROP TRIGGER IF EXISTS game_players_capacity ON game_players")
    op.execute("DROP FUNCTION IF EXISTS enforce_roster_capacity()")
