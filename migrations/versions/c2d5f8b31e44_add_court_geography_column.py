"""Add a generated geography column to courts

Revision ID: c2d5f8b31e44
Revises: b1c4e9a72f10
Create Date: 2026-08-26 17:56:00.000000

"""
import geoalchemy2
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c2d5f8b31e44'
down_revision = 'b1c4e9a72f10'
branch_labels = None
depends_on = None

GENERATED_FROM = "ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography"


def upgrade():
    # A GENERATED ... STORED column rather than a nullable column plus a
    # backfill. PostgreSQL computes the value for every existing row as part of
    # this statement and for every future row on write, so geog cannot drift out
    # of sync with lat/lng -- not through the ORM, not through a bulk COPY, not
    # through someone poking at psql.
    #
    # The trade-off is the lock: adding a stored generated column rewrites the
    # table under ACCESS EXCLUSIVE. On a courts table of any realistic size that
    # is milliseconds, so correctness-by-construction is the better deal here.
    # If this table were large enough for the rewrite to matter, the shape would
    # be the usual three steps instead -- add nullable, backfill in batches,
    # then SET NOT NULL -- at the cost of a window where the column can be wrong.
    op.add_column(
        'courts',
        sa.Column(
            'geog',
            geoalchemy2.types.Geography(
                geometry_type='POINT',
                srid=4326,
                from_text='ST_GeogFromText',
                name='geography',
                nullable=False,
                spatial_index=False,
            ),
            sa.Computed(GENERATED_FROM, persisted=True),
            nullable=False,
        ),
    )
    # No index here on purpose: the GiST index is created CONCURRENTLY in the
    # next migration, which cannot run inside this transaction.


def downgrade():
    op.drop_column('courts', 'geog')
