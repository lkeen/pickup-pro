"""Store timestamps as timestamptz

Every timestamp column was TIMESTAMP WITHOUT TIME ZONE, populated by
datetime.now() -- which returns naive *local* time. Two servers in different
zones writing to the same database would disagree about what a stored value
means, and nothing would report an error.

Revision ID: a8940ffb16a6
Revises: 9cc2dd59c75a
Create Date: 2026-08-26 19:05:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a8940ffb16a6'
down_revision = '9cc2dd59c75a'
branch_labels = None
depends_on = None

# What the existing naive values are assumed to mean.
#
# They were written by datetime.now(), so strictly they are local time in
# whatever zone the writer ran in -- which is not recorded anywhere. Assuming
# UTC is a decision, not a fact. If this were being applied to a database with
# meaningful history written from a known zone, this should be that zone
# instead: the conversion below is the only chance to get it right.
LEGACY_TZ = 'UTC'

COLUMNS = [
    ('users', 'created_at'),
    ('courts', 'created_at'),
    ('games', 'time'),
    ('games', 'created_at'),
    ('game_players', 'joined_at'),
    ('player_stats', 'created_at'),
    ('player_stats', 'updated_at'),
    ('player_ratings', 'created_at'),
]


def upgrade():
    for table, column in COLUMNS:
        # Without USING, PostgreSQL converts by assuming the *server's*
        # TimeZone setting, which makes the result depend on where the
        # migration happens to run. Stating the assumption explicitly makes it
        # reproducible.
        op.execute(
            f'ALTER TABLE {table} '
            f'ALTER COLUMN "{column}" TYPE timestamptz '
            f"USING \"{column}\" AT TIME ZONE '{LEGACY_TZ}'"
        )


def downgrade():
    for table, column in COLUMNS:
        op.execute(
            f'ALTER TABLE {table} '
            f'ALTER COLUMN "{column}" TYPE timestamp '
            f"USING \"{column}\" AT TIME ZONE '{LEGACY_TZ}'"
        )
