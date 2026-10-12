"""OIDC memberships, session identity, audit actors and tenant query indexes."""

import sqlalchemy as sa
from alembic import op

revision = "6e42d701a9b0"
down_revision = "3b84b0c696a5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memberships",
        sa.Column("tenant_id", sa.String(100), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("issuer", sa.String(255), primary_key=True),
        sa.Column("subject", sa.String(255), primary_key=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("role IN ('viewer', 'dispatcher')", name="membership_role"),
    )
    op.add_column("login_sessions", sa.Column("issuer", sa.String(255), nullable=True))
    op.add_column("login_sessions", sa.Column("subject", sa.String(255), nullable=True))
    op.add_column("audit_events", sa.Column("actor", sa.String(600), nullable=True))
    op.create_index("ix_runs_tenant_created", "runs", ["tenant_id", "created_at"])
    op.create_index("ix_proposals_tenant_created", "rule_proposals", ["tenant_id", "created_at"])


def downgrade():
    op.drop_index("ix_proposals_tenant_created", table_name="rule_proposals")
    op.drop_index("ix_runs_tenant_created", table_name="runs")
    op.drop_column("audit_events", "actor")
    op.drop_column("login_sessions", "subject")
    op.drop_column("login_sessions", "issuer")
    op.drop_table("memberships")
