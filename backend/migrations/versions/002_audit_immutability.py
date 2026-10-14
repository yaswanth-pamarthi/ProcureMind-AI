from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE OR REPLACE FUNCTION reject_audit_change() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'Audit records cannot be changed'; END; $$ LANGUAGE plpgsql"""
    )
    for table in ["activity_logs", "approvals", "agent_outputs", "vendor_scores"]:
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_audit_change()"
        )


def downgrade():
    for table in ["activity_logs", "approvals", "agent_outputs", "vendor_scores"]:
        op.execute(f"DROP TRIGGER immutable_{table} ON {table}")
    op.execute("DROP FUNCTION reject_audit_change()")
