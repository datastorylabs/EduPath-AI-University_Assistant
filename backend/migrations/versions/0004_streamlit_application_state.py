"""Add per-account persistent state for the original Streamlit experience.

Revision ID: 0004_streamlit_application_state
Revises: 0003_profiles_and_conversations
Create Date: 2026-10-23
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_streamlit_application_state"
down_revision: Union[str, None] = "0003_profiles_and_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "streamlit_application_states",
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_streamlit_application_states_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_streamlit_application_states"),
    )


def downgrade() -> None:
    op.drop_table("streamlit_application_states")
