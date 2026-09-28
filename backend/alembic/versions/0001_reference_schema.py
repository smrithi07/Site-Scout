"""reference schema

Revision ID: 0001
Revises: 
Create Date: 2026-09-28 09:52:08.588551

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('data_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('config_version', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('data_sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('bytes', sa.BigInteger(), nullable=False),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['snapshot_id'], ['data_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_data_sources_snapshot_id'), 'data_sources', ['snapshot_id'], unique=False)
    op.create_geospatial_table('h3_cells',
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('h3', sa.String(length=16), nullable=False),
    sa.Column('res', sa.Integer(), nullable=False),
    sa.Column('parent_h3', sa.String(length=16), nullable=True),
    sa.Column('ward_no', sa.Integer(), nullable=True),
    sa.Column('zone_no', sa.Integer(), nullable=True),
    sa.Column('area_km2', sa.Float(), nullable=False),
    sa.Column('geom', Geometry(geometry_type='POLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.ForeignKeyConstraint(['snapshot_id'], ['data_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('snapshot_id', 'h3')
    )
    op.create_geospatial_index('idx_h3_cells_geom', 'h3_cells', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_geospatial_table('localities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('name_norm', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('pincode', sa.String(length=6), nullable=True),
    sa.Column('ward_no', sa.Integer(), nullable=True),
    sa.Column('zone_no', sa.Integer(), nullable=True),
    sa.Column('geom', Geometry(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.ForeignKeyConstraint(['snapshot_id'], ['data_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_localities_geom', 'localities', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index(op.f('ix_localities_snapshot_id'), 'localities', ['snapshot_id'], unique=False)
    op.create_geospatial_table('pincodes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('pincode', sa.String(length=6), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('geom_source', sa.String(length=32), nullable=False),
    sa.Column('clipped', sa.Boolean(), nullable=False),
    sa.Column('geom', Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.ForeignKeyConstraint(['snapshot_id'], ['data_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_pincodes_geom', 'pincodes', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index(op.f('ix_pincodes_snapshot_id'), 'pincodes', ['snapshot_id'], unique=False)
    op.create_geospatial_table('post_offices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('pincode', sa.String(length=6), nullable=False),
    sa.Column('office_name', sa.Text(), nullable=False),
    sa.Column('area', sa.Text(), nullable=False),
    sa.Column('office_type', sa.String(length=4), nullable=True),
    sa.Column('district', sa.Text(), nullable=True),
    sa.Column('coord_decimals', sa.Integer(), nullable=False),
    sa.Column('in_service_area', sa.Boolean(), nullable=False),
    sa.Column('ward_no', sa.Integer(), nullable=True),
    sa.Column('zone_no', sa.Integer(), nullable=True),
    sa.Column('geom', Geometry(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.ForeignKeyConstraint(['snapshot_id'], ['data_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_post_offices_geom', 'post_offices', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index(op.f('ix_post_offices_pincode'), 'post_offices', ['pincode'], unique=False)
    op.create_index(op.f('ix_post_offices_snapshot_id'), 'post_offices', ['snapshot_id'], unique=False)
    op.create_geospatial_table('service_areas',
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('geom', Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.ForeignKeyConstraint(['snapshot_id'], ['data_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('snapshot_id')
    )
    op.create_geospatial_index('idx_service_areas_geom', 'service_areas', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_geospatial_table('stores',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('store_code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('zone', sa.String(length=16), nullable=True),
    sa.Column('is_operational', sa.Boolean(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('geom', Geometry(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.ForeignKeyConstraint(['snapshot_id'], ['data_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_stores_geom', 'stores', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index(op.f('ix_stores_snapshot_id'), 'stores', ['snapshot_id'], unique=False)
    op.create_geospatial_table('wards',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('ward_no', sa.Integer(), nullable=False),
    sa.Column('zone_no', sa.Integer(), nullable=True),
    sa.Column('geom', Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.ForeignKeyConstraint(['snapshot_id'], ['data_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_wards_geom', 'wards', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index(op.f('ix_wards_snapshot_id'), 'wards', ['snapshot_id'], unique=False)
    op.create_geospatial_table('zones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('zone_no', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('region', sa.Text(), nullable=True),
    sa.Column('geom', Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.ForeignKeyConstraint(['snapshot_id'], ['data_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_zones_geom', 'zones', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index(op.f('ix_zones_snapshot_id'), 'zones', ['snapshot_id'], unique=False)

    # Hand-added: one row per natural key per snapshot, fuzzy locality search, grid lookups.
    op.create_index('uq_zones_snapshot_zone', 'zones', ['snapshot_id', 'zone_no'], unique=True)
    op.create_index('uq_wards_snapshot_ward', 'wards', ['snapshot_id', 'ward_no'], unique=True)
    # A pincode may have a datameet part and a Voronoi extension part — one row per source.
    op.create_index('uq_pincodes_snapshot_pin_source', 'pincodes', ['snapshot_id', 'pincode', 'geom_source'], unique=True)
    op.create_index('uq_stores_snapshot_code', 'stores', ['snapshot_id', 'store_code'], unique=True)
    op.create_index('ix_h3_cells_snapshot_res', 'h3_cells', ['snapshot_id', 'res'])
    op.create_index('ix_h3_cells_parent', 'h3_cells', ['snapshot_id', 'parent_h3'])
    op.execute("CREATE INDEX ix_localities_name_trgm ON localities USING gin (name_norm gin_trgm_ops)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_localities_name_trgm")
    op.drop_index(op.f('ix_zones_snapshot_id'), table_name='zones')
    op.drop_geospatial_index('idx_zones_geom', table_name='zones', postgresql_using='gist', column_name='geom')
    op.drop_geospatial_table('zones')
    op.drop_index(op.f('ix_wards_snapshot_id'), table_name='wards')
    op.drop_geospatial_index('idx_wards_geom', table_name='wards', postgresql_using='gist', column_name='geom')
    op.drop_geospatial_table('wards')
    op.drop_index(op.f('ix_stores_snapshot_id'), table_name='stores')
    op.drop_geospatial_index('idx_stores_geom', table_name='stores', postgresql_using='gist', column_name='geom')
    op.drop_geospatial_table('stores')
    op.drop_geospatial_index('idx_service_areas_geom', table_name='service_areas', postgresql_using='gist', column_name='geom')
    op.drop_geospatial_table('service_areas')
    op.drop_index(op.f('ix_post_offices_snapshot_id'), table_name='post_offices')
    op.drop_index(op.f('ix_post_offices_pincode'), table_name='post_offices')
    op.drop_geospatial_index('idx_post_offices_geom', table_name='post_offices', postgresql_using='gist', column_name='geom')
    op.drop_geospatial_table('post_offices')
    op.drop_index(op.f('ix_pincodes_snapshot_id'), table_name='pincodes')
    op.drop_geospatial_index('idx_pincodes_geom', table_name='pincodes', postgresql_using='gist', column_name='geom')
    op.drop_geospatial_table('pincodes')
    op.drop_index(op.f('ix_localities_snapshot_id'), table_name='localities')
    op.drop_geospatial_index('idx_localities_geom', table_name='localities', postgresql_using='gist', column_name='geom')
    op.drop_geospatial_table('localities')
    op.drop_geospatial_index('idx_h3_cells_geom', table_name='h3_cells', postgresql_using='gist', column_name='geom')
    op.drop_geospatial_table('h3_cells')
    op.drop_index(op.f('ix_data_sources_snapshot_id'), table_name='data_sources')
    op.drop_table('data_sources')
    op.drop_table('data_snapshots')
