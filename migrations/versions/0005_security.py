"""Revocable sessions, disabled accounts and private login monitoring."""
from alembic import op
import sqlalchemy as sa

revision = "0005_security"
down_revision = "0004_standardize_indexes"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.create_table("auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.Integer()))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table("refresh_tokens",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("auth_sessions.id"), nullable=False),
        sa.Column("consumed_at", sa.Integer()))
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])
    op.create_table("login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_key", sa.String(64), nullable=False),
        sa.Column("client_key", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False))
    for field in ("account_key", "client_key", "occurred_at"):
        op.create_index("ix_login_attempts_" + field, "login_attempts", [field])

def downgrade():
    raise RuntimeError("Restore a verified backup to revert security schema")
