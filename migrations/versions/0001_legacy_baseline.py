"""Adopt the existing schema without dropping or overwriting school data.

This frozen baseline also creates a new empty database. It intentionally does
not import current application models, which will evolve after this revision.
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

revision = "0001_legacy_baseline"
down_revision = None
branch_labels = None
depends_on = None


def legacy_metadata():
    metadata = sa.MetaData()
    sa.Table("users", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False))
    sa.Table("marks", metadata,
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("name", sa.String, index=True),
        *[sa.Column(field, sa.Float, default=0.0) for field in (
            "mathematics", "pretechnical", "cre", "agriculture", "integrated_science",
            "social_studies", "english", "kiswahili", "creativeArts", "total", "average")],
        sa.Column("status", sa.String, default=""),
        sa.Column("rank", sa.Integer, default=0))
    sa.Table("fees", metadata,
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("learner_name", sa.String(255), nullable=False, index=True),
        sa.Column("grade", sa.String(50), nullable=False, index=True),
        sa.Column("academic_year", sa.Integer, nullable=False, server_default="0", index=True),
        sa.Column("term", sa.Integer, nullable=False, server_default="0", index=True),
        *[sa.Column(f"{category}_{suffix}", sa.Float, nullable=False, default=0.0)
          for category in ("pta", "remedials", "welfare", "lunch", "school") for suffix in ("required", "fee")],
        *[sa.Column(field, sa.Float, nullable=False, default=0.0) for field in ("total_required", "total_paid", "total_balance")])
    sa.Table("fee_payments", metadata,
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("fee_id", sa.Integer, sa.ForeignKey("fees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("payment_date", sa.Date),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("reference", sa.String(120)), sa.Column("note", sa.Text),
        sa.Column("is_opening_balance", sa.Boolean, nullable=False, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    sa.Table("admin_activity", metadata,
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("actor_username", sa.String(100), nullable=False, index=True),
        sa.Column("action", sa.String(64), nullable=False, index=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64)),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True))
    return metadata


def upgrade():
    connection = op.get_bind()
    metadata = legacy_metadata()
    metadata.create_all(connection, checkfirst=True)
    # Historical deployments predate these additive columns.
    expected = {
        "fees": [sa.Column("academic_year", sa.Integer, nullable=False, server_default="0"),
                 sa.Column("term", sa.Integer, nullable=False, server_default="0"),
                 sa.Column("total_required", sa.Float, nullable=False, server_default="0")],
        "marks": [sa.Column("total", sa.Float, server_default="0"),
                  sa.Column("average", sa.Float, server_default="0"),
                  sa.Column("status", sa.String, server_default=""),
                  sa.Column("rank", sa.Integer, server_default="0")],
    }
    for table, columns in expected.items():
        existing = {column["name"] for column in sa.inspect(connection).get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    # Paid totals in a legacy fee row are opening balances only when no ledger
    # entries already account for the category. Re-running never duplicates them.
    fees = metadata.tables["fees"]
    payments = metadata.tables["fee_payments"]
    for fee in connection.execute(sa.select(fees)).mappings():
        for category in ("pta", "remedials", "welfare", "lunch", "school"):
            amount = fee[f"{category}_fee"] or 0.0
            exists = connection.execute(sa.select(payments.c.id).where(
                payments.c.fee_id == fee["id"], payments.c.category == category)).first()
            if amount > 0 and not exists:
                connection.execute(payments.insert().values(
                    fee_id=fee["id"], category=category, amount=amount,
                    is_opening_balance=True, payment_date=None,
                    note="Migrated balance; original payment date unavailable.",
                    created_at=datetime.now(timezone.utc)))


def downgrade():
    raise RuntimeError("The adoption baseline is not destructive. Restore a verified backup to revert it.")
