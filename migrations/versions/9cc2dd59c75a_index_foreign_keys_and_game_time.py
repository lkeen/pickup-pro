"""Index foreign keys and game time

PostgreSQL does not create an index for a foreign key automatically. It creates
one for a PRIMARY KEY and for a UNIQUE constraint, and people generalise from
that. Every foreign key in this schema was unindexed, which makes both the
lookup in that direction and any ON DELETE / ON UPDATE check a sequential scan.

Revision ID: 9cc2dd59c75a
Revises: d3e6a9c45b72
Create Date: 2026-08-26 18:40:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '9cc2dd59c75a'
down_revision = 'd3e6a9c45b72'
branch_labels = None
depends_on = None

# (name, table, columns). All btree; the GiST index on courts.geog is separate.
INDEXES = [
    ('ix_courts_created_by', 'courts', 'created_by'),
    ('ix_game_players_user_id', 'game_players', 'user_id'),
    ('ix_games_court_id', 'games', 'court_id'),
    ('ix_games_host_id', 'games', 'host_id'),
    # Every game listing filters or orders on time. Its absence showed up as a
    # sequential scan over 75,000 rows in the nearby-search plan.
    ('ix_games_time', 'games', 'time'),
    # Composite for the common "games at this court on this day" filter.
    ('ix_games_court_id_time', 'games', 'court_id, "time"'),
    ('ix_player_ratings_game_id', 'player_ratings', 'game_id'),
    ('ix_player_ratings_to_user_id', 'player_ratings', 'to_user_id'),
    ('ix_player_stats_user_id', 'player_stats', 'user_id'),
]


def _drop_if_invalid(name):
    """Clear the wreckage of a CONCURRENTLY build that failed.

    A failed concurrent build leaves an INVALID index behind. The planner
    ignores it, IF NOT EXISTS will not replace it, and the migration that
    "created" it reports success -- so the table ends up with no usable index
    and nothing says so.
    """
    invalid = op.get_bind().exec_driver_sql(
        "SELECT 1 FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
        "WHERE c.relname = %s AND NOT i.indisvalid",
        (name,),
    ).scalar()
    if invalid:
        op.execute(f'DROP INDEX IF EXISTS {name}')


def upgrade():
    # CONCURRENTLY for the same reason as the GiST index: a plain CREATE INDEX
    # takes a SHARE lock and blocks writes to the table for its duration. That
    # is invisible on an empty development database and very visible on a
    # populated one.
    with op.get_context().autocommit_block():
        for name, table, columns in INDEXES:
            _drop_if_invalid(name)
            op.execute(
                f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} ({columns})'
            )


def downgrade():
    with op.get_context().autocommit_block():
        for name, _table, _columns in reversed(INDEXES):
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {name}')
