"""Add a GiST index on courts.geog

Revision ID: d3e6a9c45b72
Revises: c2d5f8b31e44
Create Date: 2026-08-26 18:10:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd3e6a9c45b72'
down_revision = 'c2d5f8b31e44'
branch_labels = None
depends_on = None

INDEX_NAME = 'ix_courts_geog'


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
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block, and
    # Alembic wraps every migration in one. autocommit_block() steps outside it
    # for the duration.
    #
    # The point of CONCURRENTLY is that an ordinary CREATE INDEX takes a SHARE
    # lock, blocking every write to courts until it finishes. CONCURRENTLY does
    # two passes and takes no blocking lock, so the application keeps serving.
    with op.get_context().autocommit_block():
        _drop_if_invalid(INDEX_NAME)
        op.execute(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} '
            f'ON courts USING GIST (geog)'
        )


def downgrade():
    # DROP INDEX CONCURRENTLY has the same transaction restriction.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
