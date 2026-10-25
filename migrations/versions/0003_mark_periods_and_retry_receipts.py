"""Give marks a constrained learner/class/period identity and persist retries."""
from alembic import op
import sqlalchemy as sa

revision = "0003_mark_periods_and_retry"
down_revision = "0002_permanent_learner_ids"
branch_labels = None
depends_on = None
SUBJECTS = ("mathematics", "pretechnical", "cre", "agriculture", "integrated_science", "social_studies", "english", "kiswahili", "creative_arts")


def upgrade():
    connection = op.get_bind()
    # Any unlinked rows added through an old app must be reconciled before this
    # constraint can be made permanent. Never delete or guess conflicting rows.
    if connection.execute(sa.text("SELECT count(*) FROM marks WHERE learner_id IS NULL")).scalar():
        raise RuntimeError("Legacy marks without learner IDs require identity reconciliation")
    if connection.execute(sa.text("SELECT count(*) FROM (SELECT learner_id FROM marks GROUP BY learner_id HAVING count(*) > 1) AS conflicts")).scalar():
        raise RuntimeError("Conflicting legacy marks require period reconciliation; no records were deleted")
    for field in SUBJECTS:
        old_field = '"creativeArts"' if field == "creative_arts" else field
        if connection.execute(sa.text(f"SELECT count(*) FROM marks WHERE {old_field} IS NULL OR {old_field} < 0 OR {old_field} > 100")).scalar():
            raise RuntimeError("Legacy marks contain missing or invalid scores; reconcile before migration")
    op.add_column("marks", sa.Column("class_name", sa.String(50)))
    op.add_column("marks", sa.Column("academic_year", sa.Integer, nullable=False, server_default="0"))
    op.add_column("marks", sa.Column("term", sa.Integer, nullable=False, server_default="0"))
    connection.execute(sa.text("UPDATE marks SET class_name=(SELECT class_name FROM learners WHERE learners.id=marks.learner_id)"))
    with op.batch_alter_table("marks") as batch:
        batch.alter_column("learner_id", existing_type=sa.String(36), nullable=False)
        batch.alter_column("class_name", existing_type=sa.String(50), nullable=False)
        batch.alter_column("creativeArts", new_column_name="creative_arts", existing_type=sa.Float, nullable=False)
        for field in SUBJECTS[:-1]:
            batch.alter_column(field, existing_type=sa.Float, nullable=False)
        batch.create_unique_constraint("uq_marks_learner_period", ["learner_id", "class_name", "academic_year", "term"])
        batch.create_check_constraint("ck_marks_period", "(academic_year = 0 AND term = 0) OR (academic_year BETWEEN 2000 AND 2200 AND term BETWEEN 1 AND 3)")
        batch.create_check_constraint("ck_marks_class", "length(trim(class_name)) > 0")
        for field in SUBJECTS:
            batch.create_check_constraint(f"ck_marks_{field}", f"{field} >= 0 AND {field} <= 100")
    op.create_table("request_receipts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_body", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("actor_id", "operation", "key", name="uq_request_receipt"))


def downgrade():
    raise RuntimeError("Restore a verified backup to revert mark identities and retry receipts")
