"""Create permanent learner identities without merging ambiguous names."""
from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0002_permanent_learner_ids"
down_revision = "0001_legacy_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("learners",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("class_name", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_learners_name", "learners", ["name"])
    op.create_index("ix_learners_class_name", "learners", ["class_name"])
    # A nullable additive reference supports legacy API writes during the staged
    # API cutover. The following revision will enforce ID-based mark identity.
    if op.get_bind().dialect.name == "sqlite":
        # SQLite supports an inline REFERENCES clause on a nullable new column.
        # Avoid recreating the fees parent table while payment rows reference it.
        op.execute("ALTER TABLE fees ADD COLUMN learner_id VARCHAR(36) REFERENCES learners(id)")
    else:
        op.add_column("fees", sa.Column("learner_id", sa.String(36), sa.ForeignKey("learners.id")))
    op.create_index("ix_fees_learner_id", "fees", ["learner_id"])
    if op.get_bind().dialect.name == "sqlite":
        op.execute("ALTER TABLE marks ADD COLUMN learner_id VARCHAR(36) REFERENCES learners(id)")
    else:
        op.add_column("marks", sa.Column("learner_id", sa.String(36), sa.ForeignKey("learners.id")))
    op.create_index("ix_marks_learner_id", "marks", ["learner_id"])
    connection = op.get_bind()
    learners = sa.table("learners", sa.column("id"), sa.column("name"), sa.column("class_name"), sa.column("created_at", sa.DateTime(timezone=True)))
    identities = {}
    fees = connection.execute(sa.text("SELECT id, learner_name, grade FROM fees ORDER BY id")).mappings().all()
    for fee in fees:
        key = (fee["learner_name"].strip(), fee["grade"].strip())
        if not key[0] or not key[1]:
            raise RuntimeError("Blank learner names/classes must be resolved before assigning permanent IDs")
        if key not in identities:
            identities[key] = str(uuid4())
            connection.execute(learners.insert().values(id=identities[key], name=key[0], class_name=key[1], created_at=datetime.now(timezone.utc)))
        connection.execute(sa.text("UPDATE fees SET learner_id=:learner_id WHERE id=:id"), {"learner_id": identities[key], "id": fee["id"]})
    for mark in connection.execute(sa.text("SELECT id, name FROM marks ORDER BY id")).mappings().all():
        name = (mark["name"] or "").strip()
        candidates = [learner_id for (learner_name, _), learner_id in identities.items() if learner_name == name]
        if not name or len(candidates) > 1:
            raise RuntimeError("A legacy mark has an empty or ambiguous learner name; resolve its identity before migration")
        if not candidates:
            key = (name, "Unassigned")
            identities[key] = str(uuid4())
            connection.execute(learners.insert().values(id=identities[key], name=name, class_name="Unassigned", created_at=datetime.now(timezone.utc)))
            candidates = [identities[key]]
        connection.execute(sa.text("UPDATE marks SET learner_id=:learner_id WHERE id=:id"), {"learner_id": candidates[0], "id": mark["id"]})


def downgrade():
    raise RuntimeError("Permanent learner identities must not be discarded; restore a verified backup instead")
