"""instruments, instrument_aliases and the owner user

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("isin", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("series", sa.String(), nullable=False),
        sa.Column("sector", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instruments")),
        sa.UniqueConstraint("symbol", name=op.f("uq_instruments_symbol")),
    )
    op.create_table(
        "instrument_aliases",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("alias", sa.String(), nullable=False),
        sa.Column("alias_norm", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_instrument_aliases_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_instrument_aliases_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instrument_aliases")),
        sa.UniqueConstraint("user_id", "alias_norm", name=op.f("uq_instrument_aliases_user_id")),
    )
    op.create_index(op.f("ix_instrument_aliases_user_id"), "instrument_aliases", ["user_id"])

    # The single user until there is auth (app.api.deps.current_user_id returns this id).
    # setval keeps the identity sequence ahead of the explicit id.
    op.execute("INSERT INTO users (id, name) VALUES (1, 'owner') ON CONFLICT DO NOTHING")
    op.execute("SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT max(id) FROM users))")


def downgrade() -> None:
    op.drop_index(op.f("ix_instrument_aliases_user_id"), table_name="instrument_aliases")
    op.drop_table("instrument_aliases")
    op.drop_table("instruments")
    op.execute("DELETE FROM users WHERE id = 1")
