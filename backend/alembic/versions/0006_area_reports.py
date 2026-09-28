"""area reports

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-28 15:06:52.420759

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_geospatial_table('area_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('area_key', sa.String(length=16), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('selection', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('resolved', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('config_version', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('rating', sa.String(length=24), nullable=True),
    sa.Column('confidence', sa.String(length=8), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('narrative', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('narrative_source', sa.String(length=16), nullable=False),
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('select_cells', postgresql.ARRAY(sa.String(length=16)), nullable=False),
    sa.Column('geom', Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['data_snapshots.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_area_reports_geom', 'area_reports', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index(op.f('ix_area_reports_area_key'), 'area_reports', ['area_key'], unique=False)
    op.create_index('uq_area_reports_key_version', 'area_reports', ['area_key', 'version'], unique=True)
    # Hand-added: reports are immutable snapshots (Core rule 2). UPDATE is always rejected; DELETE
    # only inside a transaction that sets `sitescout.purge = on` (test-data cleanup — never app code).
    op.execute("""
        CREATE FUNCTION area_reports_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('sitescout.purge', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'area_reports rows are immutable (% rejected); create a new version instead', TG_OP;
        END $$""")
    op.execute("""CREATE TRIGGER area_reports_immutable BEFORE UPDATE OR DELETE ON area_reports
                  FOR EACH ROW EXECUTE FUNCTION area_reports_immutable()""")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER area_reports_immutable ON area_reports")
    op.execute("DROP FUNCTION area_reports_immutable()")
    op.drop_index('uq_area_reports_key_version', table_name='area_reports')
    op.drop_index(op.f('ix_area_reports_area_key'), table_name='area_reports')
    op.drop_geospatial_index('idx_area_reports_geom', table_name='area_reports', postgresql_using='gist', column_name='geom')
    op.drop_geospatial_table('area_reports')
