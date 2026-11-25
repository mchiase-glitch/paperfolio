"""dati di bilancio (P6) e stato delle strategie (P7)

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa
import app.database

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('strategy_configs', sa.Column('state_json', sa.Text(), nullable=True))
    op.create_table(
        'fundamentals',
        sa.Column('symbol', sa.String(40), nullable=False),
        sa.Column('fetched_at', app.database.UTCDateTime(), nullable=False),
        sa.Column('data_json', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('symbol'),
    )


def downgrade() -> None:
    op.drop_table('fundamentals')
    op.drop_column('strategy_configs', 'state_json')
