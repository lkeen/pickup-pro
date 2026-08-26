"""Enable the PostGIS extension

Split from the migration that uses it so the two can be reasoned about
separately: this one changes what the database is capable of, the next changes
the schema.

Revision ID: b1c4e9a72f10
Revises: ad178fd5d52b
Create Date: 2026-08-26 17:55:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b1c4e9a72f10'
down_revision = 'ad178fd5d52b'
branch_labels = None
depends_on = None


def upgrade():
    # Requires a database image that ships the PostGIS libraries; docker-compose
    # uses postgis/postgis:16-3.4. Creating an extension needs superuser or the
    # pg_database_owner role, which the compose user has.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade():
    # RESTRICT (the default) rather than CASCADE: if anything still depends on
    # PostGIS, failing loudly beats silently dropping the columns that use it.
    op.execute("DROP EXTENSION IF EXISTS postgis")
