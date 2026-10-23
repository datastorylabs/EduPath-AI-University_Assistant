"""Add revocable auth sessions and low-PII security audit events.

Revision ID: 0002_auth_sessions_and_audit
Revises: 0001_initial_users
Create Date: 2026-10-22
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_auth_sessions_and_audit"
down_revision: Union[str, None] = "0001_initial_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_auth_sessions_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], unique=False)
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"], unique=False)

    op.create_table(
        "security_audit_events",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_security_audit_events_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_security_audit_events"),
    )
    op.create_index("ix_security_audit_events_created_at", "security_audit_events", ["created_at"], unique=False)
    op.create_index("ix_security_audit_events_event_type", "security_audit_events", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_security_audit_events_event_type", table_name="security_audit_events")
    op.drop_index("ix_security_audit_events_created_at", table_name="security_audit_events")
    op.drop_table("security_audit_events")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
