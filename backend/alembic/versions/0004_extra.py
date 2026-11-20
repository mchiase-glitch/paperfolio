"""extra: ordini limite/stop con scadenza, watchlist

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa
import app.database

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('trigger_price', app.database.DecimalText(length=40), nullable=True))
    op.add_column('orders', sa.Column('expires_on', sa.Date(), nullable=True))
    op.create_table(
        'watchlist',
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('added_at', app.database.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id']),
        sa.PrimaryKeyConstraint('instrument_id'),
    )


def downgrade() -> None:
    op.drop_table('watchlist')
    op.drop_column('orders', 'expires_on')
    op.drop_column('orders', 'trigger_price')
