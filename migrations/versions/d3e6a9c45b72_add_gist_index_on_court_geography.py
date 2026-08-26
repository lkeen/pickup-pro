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


def upgrade():
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block, and
    # Alembic wraps every migration in one. autocommit_block() steps outside it
    # for the duration.
    #
    # The point of CONCURRENTLY is that an ordinary CREATE INDEX takes a SHARE
    # lock, blocking every write to courts until it finishes. CONCURRENTLY does
    # two passes and takes no blocking lock, so the application keeps serving.
    # The cost is that it can fail and leave an INVALID index behind, which is
    # why IF NOT EXISTS alone is not enough -- see the note in downgrade.
    with op.get_context().autocommit_block():
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} ON courts USING GIST (geog)")


def downgrade():
    # DROP INDEX CONCURRENTLY has the same transaction restriction.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
