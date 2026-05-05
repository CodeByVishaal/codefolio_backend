"""add mfa support

Revision ID: 5b1f2c3d4e5a
Revises: 9c1585331b3f
Create Date: 2026-05-05 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5b1f2c3d4e5a"
down_revision: Union[str, Sequence[str], None] = "9c1585331b3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "mfa_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("mfa_last_used_counter", sa.Integer(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "mfa_failed_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column("mfa_locked_until", sa.DateTime(), nullable=True),
    )
    op.alter_column("users", "mfa_enabled", server_default=None)
    op.alter_column("users", "mfa_failed_attempts", server_default=None)

    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mfa_recovery_codes_id"),
        "mfa_recovery_codes",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mfa_recovery_codes_user_id"),
        "mfa_recovery_codes",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mfa_recovery_codes_user_id"), table_name="mfa_recovery_codes")
    op.drop_index(op.f("ix_mfa_recovery_codes_id"), table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
    op.drop_column("users", "mfa_locked_until")
    op.drop_column("users", "mfa_failed_attempts")
    op.drop_column("users", "mfa_last_used_counter")
    op.drop_column("users", "mfa_enabled")
