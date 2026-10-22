"""Add owner-scoped academic profiles and persistent conversation history.

Revision ID: 0003_profiles_and_conversations
Revises: 0002_auth_sessions_and_audit
Create Date: 2026-10-22
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_profiles_and_conversations"
down_revision: Union[str, None] = "0002_auth_sessions_and_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "student_profiles",
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("qualification", sa.String(length=120), nullable=True),
        sa.Column("ssc_percent", sa.Float(), nullable=True),
        sa.Column("hssc_percent", sa.Float(), nullable=True),
        sa.Column("subjects", sa.JSON(), nullable=False),
        sa.Column("subject_percentages", sa.JSON(), nullable=False),
        sa.Column("equivalency_status", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "ssc_percent IS NULL OR (ssc_percent >= 0 AND ssc_percent <= 100)",
            name="ck_student_profiles_ssc_percent_range",
        ),
        sa.CheckConstraint(
            "hssc_percent IS NULL OR (hssc_percent >= 0 AND hssc_percent <= 100)",
            name="ck_student_profiles_hssc_percent_range",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_student_profiles_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name="pk_student_profiles"),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_conversations_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index(
        "ix_conversations_user_id_updated_at",
        "conversations",
        ["user_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_conversation_messages_role_allowed"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"],
            name="fk_conversation_messages_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_messages"),
    )
    op.create_index(
        "ix_conversation_messages_conversation_created_at",
        "conversation_messages",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_conversation_created_at", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_user_id_updated_at", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("student_profiles")
