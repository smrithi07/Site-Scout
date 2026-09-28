"""audit and jobs

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28 14:42:20.206624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audit_events',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('actor_role', sa.String(length=24), nullable=False),
    sa.Column('entity_type', sa.String(length=32), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=48), nullable=False),
    sa.Column('from_state', sa.Text(), nullable=True),
    sa.Column('to_state', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.CheckConstraint('length(btrim(reason)) > 0', name='ck_audit_reason_required'),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_entity', 'audit_events', ['entity_type', 'entity_id', 'id'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('kind', sa.String(length=48), nullable=False),
    sa.Column('queue', sa.String(length=24), server_default='default', nullable=False),
    sa.Column('status', sa.String(length=16), server_default='queued', nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=64), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('current_step', sa.String(length=48), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_jobs_claim', 'jobs', ['queue', 'status', 'run_after'], unique=False)
    op.create_table('job_steps',
    sa.Column('job_id', sa.BigInteger(), nullable=False),
    sa.Column('idx', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=48), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('output', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('job_id', 'idx')
    )
    # Hand-added: the audit log is append-only at the database level (Core rule 3) — no code
    # path, including a buggy one, can rewrite or erase history.
    op.execute("""
        CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP;
        END $$""")
    op.execute("""CREATE TRIGGER audit_events_no_update_delete BEFORE UPDATE OR DELETE ON audit_events
                  FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()""")
    op.execute("""CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
                  FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only()""")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER audit_events_no_truncate ON audit_events")
    op.execute("DROP TRIGGER audit_events_no_update_delete ON audit_events")
    op.execute("DROP FUNCTION audit_events_append_only()")
    op.drop_table('job_steps')
    op.drop_index('ix_jobs_claim', table_name='jobs')
    op.drop_table('jobs')
    op.drop_index('ix_audit_entity', table_name='audit_events')
    op.drop_table('audit_events')
