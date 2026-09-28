"""scouting

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-28 15:58:28.011246

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('scout_tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('assignee_id', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='open', nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('source_report_id', sa.Integer(), nullable=True),
    sa.Column('target_cells', postgresql.ARRAY(sa.String(length=16)), nullable=False),
    sa.Column('hotspot_cells', postgresql.ARRAY(sa.String(length=16)), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['source_report_id'], ['area_reports.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scout_tasks_assignee_id'), 'scout_tasks', ['assignee_id'], unique=False)
    op.create_geospatial_table('properties',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('client_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=True),
    sa.Column('lat', sa.Float(), nullable=False),
    sa.Column('lon', sa.Float(), nullable=False),
    sa.Column('gps_accuracy_m', sa.Float(), nullable=True),
    sa.Column('device_lat', sa.Float(), nullable=True),
    sa.Column('device_lon', sa.Float(), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('landmark', sa.Text(), nullable=True),
    sa.Column('access_notes', sa.Text(), nullable=True),
    sa.Column('nearby_road', sa.Text(), nullable=True),
    sa.Column('locality', sa.Text(), nullable=True),
    sa.Column('pincode', sa.String(length=6), nullable=True),
    sa.Column('ward_no', sa.Integer(), nullable=True),
    sa.Column('zone_no', sa.Integer(), nullable=True),
    sa.Column('monthly_rent', sa.Float(), nullable=True),
    sa.Column('rent_unit', sa.String(length=16), nullable=True),
    sa.Column('area_sqft', sa.Float(), nullable=True),
    sa.Column('security_deposit', sa.Float(), nullable=True),
    sa.Column('availability', sa.Text(), nullable=True),
    sa.Column('frontage_ft', sa.Float(), nullable=True),
    sa.Column('road_width_ft', sa.Float(), nullable=True),
    sa.Column('floor', sa.String(length=16), nullable=True),
    sa.Column('visibility', sa.String(length=8), nullable=True),
    sa.Column('accessibility', sa.String(length=8), nullable=True),
    sa.Column('parking', sa.String(length=8), nullable=True),
    sa.Column('condition', sa.String(length=8), nullable=True),
    sa.Column('owner_name', sa.Text(), nullable=True),
    sa.Column('owner_phone', sa.String(length=32), nullable=True),
    sa.Column('stage', sa.String(length=24), server_default='scouted', nullable=False),
    sa.Column('status', sa.String(length=24), server_default='active', nullable=False),
    sa.Column('duplicate_of', sa.Integer(), nullable=True),
    sa.Column('duplicate_candidates', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('warnings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('missing_fields', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('evaluation_status', sa.String(length=16), server_default='not_started', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('geom', Geometry(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['duplicate_of'], ['properties.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['scout_tasks.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('client_id')
    )
    op.create_geospatial_index('idx_properties_geom', 'properties', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index(op.f('ix_properties_created_by'), 'properties', ['created_by'], unique=False)
    op.create_index('ix_properties_label_trgm', 'properties', ['label'], unique=False, postgresql_using='gin', postgresql_ops={'label': 'gin_trgm_ops'})
    op.create_index(op.f('ix_properties_task_id'), 'properties', ['task_id'], unique=False)
    op.create_table('property_notes',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('property_id', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=24), server_default='note', nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_property_notes_property_id'), 'property_notes', ['property_id'], unique=False)
    op.create_table('property_photos',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('property_id', sa.Integer(), nullable=False),
    sa.Column('uploaded_by', sa.Integer(), nullable=False),
    sa.Column('filename', sa.Text(), nullable=False),
    sa.Column('content_type', sa.String(length=32), nullable=False),
    sa.Column('bytes', sa.Integer(), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_property_photos_property_id'), 'property_photos', ['property_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_property_photos_property_id'), table_name='property_photos')
    op.drop_table('property_photos')
    op.drop_index(op.f('ix_property_notes_property_id'), table_name='property_notes')
    op.drop_table('property_notes')
    op.drop_index(op.f('ix_properties_task_id'), table_name='properties')
    op.drop_index('ix_properties_label_trgm', table_name='properties', postgresql_using='gin', postgresql_ops={'label': 'gin_trgm_ops'})
    op.drop_index(op.f('ix_properties_created_by'), table_name='properties')
    op.drop_geospatial_index('idx_properties_geom', table_name='properties', postgresql_using='gist', column_name='geom')
    op.drop_geospatial_table('properties')
    op.drop_index(op.f('ix_scout_tasks_assignee_id'), table_name='scout_tasks')
    op.drop_table('scout_tasks')
