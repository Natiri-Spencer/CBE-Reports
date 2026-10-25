"""Close index drift between historical SQLite databases and the ORM schema."""
from alembic import op
import sqlalchemy as sa

revision = "0004_standardize_indexes"
down_revision = "0003_mark_periods_and_retry"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    for table, indexes in {
        "fees": {"ix_fees_academic_year": ["academic_year"], "ix_fees_term": ["term"]},
        "users": {"ix_users_id": ["id"]},
    }.items():
        existing = {index["name"] for index in sa.inspect(connection).get_indexes(table)}
        for name, columns in indexes.items():
            if name not in existing:
                op.create_index(name, table, columns)


def downgrade():
    raise RuntimeError("Restore a verified backup to revert the adopted schema")
