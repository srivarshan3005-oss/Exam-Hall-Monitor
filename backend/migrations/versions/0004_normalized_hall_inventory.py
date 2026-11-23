"""Normalized building/block/floor directory and individual hall seats.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("buildings",
        sa.Column("id",sa.Integer(),primary_key=True), sa.Column("code",sa.String(40),nullable=False),
        sa.Column("name",sa.String(150),nullable=False), sa.Column("address",sa.String(300)),
        sa.Column("active",sa.Boolean(),nullable=False), sa.UniqueConstraint("code",name="uq_buildings_code"))
    op.create_table("blocks",
        sa.Column("id",sa.Integer(),primary_key=True), sa.Column("building_id",sa.Integer(),nullable=False),
        sa.Column("code",sa.String(40),nullable=False), sa.Column("name",sa.String(150),nullable=False),
        sa.Column("active",sa.Boolean(),nullable=False),
        sa.ForeignKeyConstraint(["building_id"],["buildings.id"],ondelete="CASCADE"),
        sa.UniqueConstraint("building_id","code",name="uq_blocks_building_code"))
    op.create_index("ix_blocks_building_id","blocks",["building_id"])
    op.create_table("floors",
        sa.Column("id",sa.Integer(),primary_key=True), sa.Column("block_id",sa.Integer(),nullable=False),
        sa.Column("code",sa.String(30),nullable=False), sa.Column("name",sa.String(100),nullable=False),
        sa.Column("active",sa.Boolean(),nullable=False),
        sa.ForeignKeyConstraint(["block_id"],["blocks.id"],ondelete="CASCADE"),
        sa.UniqueConstraint("block_id","code",name="uq_floors_block_code"))
    op.create_index("ix_floors_block_id","floors",["block_id"])
    op.add_column("halls",sa.Column("building_id",sa.Integer(),nullable=True))
    op.add_column("halls",sa.Column("block_id",sa.Integer(),nullable=True))
    op.add_column("halls",sa.Column("floor_id",sa.Integer(),nullable=True))
    with op.batch_alter_table("halls") as b:
        b.create_foreign_key("fk_halls_building_id_buildings","buildings",["building_id"],["id"],ondelete="SET NULL")
        b.create_foreign_key("fk_halls_block_id_blocks","blocks",["block_id"],["id"],ondelete="SET NULL")
        b.create_foreign_key("fk_halls_floor_id_floors","floors",["floor_id"],["id"],ondelete="SET NULL")
        b.create_index("ix_halls_building_id",["building_id"])
        b.create_index("ix_halls_block_id",["block_id"])
        b.create_index("ix_halls_floor_id",["floor_id"])
    op.create_table("hall_seats",
        sa.Column("id",sa.Integer(),primary_key=True), sa.Column("hall_id",sa.Integer(),nullable=False),
        sa.Column("seat_label",sa.String(30),nullable=False), sa.Column("active",sa.Boolean(),nullable=False),
        sa.ForeignKeyConstraint(["hall_id"],["halls.id"],ondelete="CASCADE"),
        sa.UniqueConstraint("hall_id","seat_label",name="uq_hall_seats_hall_label"))
    op.create_index("ix_hall_seats_hall_id","hall_seats",["hall_id"])

def downgrade():
    op.drop_index("ix_hall_seats_hall_id",table_name="hall_seats"); op.drop_table("hall_seats")
    with op.batch_alter_table("halls") as b:
        b.drop_index("ix_halls_floor_id"); b.drop_index("ix_halls_block_id"); b.drop_index("ix_halls_building_id")
        b.drop_constraint("fk_halls_floor_id_floors",type_="foreignkey"); b.drop_constraint("fk_halls_block_id_blocks",type_="foreignkey"); b.drop_constraint("fk_halls_building_id_buildings",type_="foreignkey")
        b.drop_column("floor_id"); b.drop_column("block_id"); b.drop_column("building_id")
    op.drop_index("ix_floors_block_id",table_name="floors"); op.drop_table("floors")
    op.drop_index("ix_blocks_building_id",table_name="blocks"); op.drop_table("blocks"); op.drop_table("buildings")
