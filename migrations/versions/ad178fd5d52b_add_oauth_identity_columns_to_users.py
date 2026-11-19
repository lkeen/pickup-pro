"""Add OAuth identity columns to users

Adds the columns a third-party sign-in needs, relaxes password_hash so an
account can exist without one, and rewrites the fabricated email addresses the
old registration flow invented.

Revision ID: ad178fd5d52b
Revises: 37e8162690e7
Create Date: 2026-08-26 17:30:01.561287

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'ad178fd5d52b'
down_revision = '37e8162690e7'
branch_labels = None
depends_on = None

# Written out rather than reflected: a migration must keep working after the
# model it was generated from has moved on.
CREDENTIAL_CHECK = (
    'password_hash IS NOT NULL '
    'OR (oauth_provider IS NOT NULL AND oauth_sub IS NOT NULL)'
)


def upgrade():
    op.add_column(
        'users',
        sa.Column(
            'email_verified',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
    )
    op.add_column('users', sa.Column('oauth_provider', sa.String(length=32), nullable=True))
    op.add_column('users', sa.Column('oauth_sub', sa.String(length=255), nullable=True))

    # An account created through Google never has a password.
    op.alter_column(
        'users', 'password_hash', existing_type=sa.VARCHAR(length=255), nullable=True
    )

    # One account per provider identity. A partial index would also do, but the
    # constraint states the intent and both columns are NULL together.
    op.create_unique_constraint(
        'unique_oauth_identity', 'users', ['oauth_provider', 'oauth_sub']
    )

    # Now that password_hash is optional, something has to guarantee every row
    # still has a way to log in. Alembic's autogenerate does not detect check
    # constraints, so this is written by hand.
    op.create_check_constraint('user_has_a_credential', 'users', CREDENTIAL_CHECK)

    # Data migration. Registration used to invent "{username}@example.com"
    # because the form had no email field. Those addresses are fabricated, and
    # example.com is plausible enough that one could collide with a real address
    # someone later registers. Move them to .invalid, which RFC 2606 reserves
    # and which can never resolve, so they are unmistakably placeholders.
    op.execute(
        sa.text(
            "UPDATE users "
            "SET email = username || '@placeholder.invalid' "
            "WHERE email = username || '@example.com'"
        )
    )


def downgrade():
    # Reversing this would leave any Google-only account with no credential at
    # all: no password to restore, and the columns identifying the provider
    # about to be dropped. Refuse rather than silently create rows that nobody
    # can log into.
    orphans = op.get_bind().execute(
        sa.text('SELECT count(*) FROM users WHERE password_hash IS NULL')
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"Cannot downgrade: {orphans} account(s) authenticate only through "
            "OAuth and have no password. Reverting would leave them unable to "
            "log in and unidentifiable. Delete them, or give them a password, "
            "and run this again."
        )

    op.execute(
        sa.text(
            "UPDATE users "
            "SET email = username || '@example.com' "
            "WHERE email = username || '@placeholder.invalid'"
        )
    )

    op.drop_constraint('user_has_a_credential', 'users', type_='check')
    op.drop_constraint('unique_oauth_identity', 'users', type_='unique')
    op.alter_column(
        'users', 'password_hash', existing_type=sa.VARCHAR(length=255), nullable=False
    )
    op.drop_column('users', 'oauth_sub')
    op.drop_column('users', 'oauth_provider')
    op.drop_column('users', 'email_verified')
