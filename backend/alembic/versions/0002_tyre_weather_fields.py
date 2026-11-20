"""tyre life, fresh-tyre and safety-car labels on laps; humidity and wind on weather

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("laps") as b:
        b.add_column(sa.Column("tyre_life", sa.Integer(), nullable=True))
        b.add_column(sa.Column("fresh_tyre", sa.Boolean(), nullable=True))
        b.add_column(sa.Column("sc_state", sa.Integer(), nullable=True))
    with op.batch_alter_table("weather") as b:
        b.add_column(sa.Column("humidity_pct", sa.Float(), nullable=True))
        b.add_column(sa.Column("wind_speed_ms", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("weather") as b:
        b.drop_column("wind_speed_ms")
        b.drop_column("humidity_pct")
    with op.batch_alter_table("laps") as b:
        b.drop_column("sc_state")
        b.drop_column("fresh_tyre")
        b.drop_column("tyre_life")
