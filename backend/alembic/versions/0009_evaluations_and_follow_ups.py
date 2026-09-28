"""evaluations and follow-ups

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-28 16:19:34.757055

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('follow_ups',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('property_id', sa.Integer(), nullable=False),
    sa.Column('requested_by', sa.Integer(), nullable=False),
    sa.Column('assignee_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='open', nullable=False),
    sa.Column('response', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_follow_ups_assignee_id'), 'follow_ups', ['assignee_id'], unique=False)
    op.create_index(op.f('ix_follow_ups_property_id'), 'follow_ups', ['property_id'], unique=False)
    op.create_table('property_evaluations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('property_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('property_version', sa.Integer(), nullable=False),
    sa.Column('trigger', sa.String(length=24), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('confidence', sa.String(length=8), nullable=True),
    sa.Column('hard_flags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('risks', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('factors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('completeness', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('config_version', sa.String(length=32), nullable=False),
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['data_snapshots.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_property_evaluations_property_id'), 'property_evaluations', ['property_id'], unique=False)
    op.create_index('uq_property_evaluations_version', 'property_evaluations', ['property_id', 'version'], unique=True)
    op.add_column('properties', sa.Column('latest_job_id', sa.BigInteger(), nullable=True))
    # Hand-added: evaluations are immutable versions (Core rule 2), same rule as area_reports.
    op.execute("""
        CREATE FUNCTION property_evaluations_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('sitescout.purge', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'property_evaluations rows are immutable (% rejected); create a new version instead', TG_OP;
        END $$""")
    op.execute("""CREATE TRIGGER property_evaluations_immutable BEFORE UPDATE OR DELETE ON property_evaluations
                  FOR EACH ROW EXECUTE FUNCTION property_evaluations_immutable()""")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER property_evaluations_immutable ON property_evaluations")
    op.execute("DROP FUNCTION property_evaluations_immutable()")
    op.drop_column('properties', 'latest_job_id')
    op.drop_index('uq_property_evaluations_version', table_name='property_evaluations')
    op.drop_index(op.f('ix_property_evaluations_property_id'), table_name='property_evaluations')
    op.drop_table('property_evaluations')
    op.drop_index(op.f('ix_follow_ups_property_id'), table_name='follow_ups')
    op.drop_index(op.f('ix_follow_ups_assignee_id'), table_name='follow_ups')
    op.drop_table('follow_ups')
