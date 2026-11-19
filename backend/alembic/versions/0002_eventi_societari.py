"""eventi societari: dividendi e split

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
import app.database

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'corporate_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('ex_date', sa.Date(), nullable=False),
        sa.Column('pay_date', sa.Date(), nullable=True),
        sa.Column('pay_date_estimated', sa.Integer(), nullable=False),
        sa.Column('amount', app.database.DecimalText(length=40), nullable=True),
        sa.Column('ratio', app.database.DecimalText(length=40), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('created_at', app.database.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('instrument_id', 'kind', 'ex_date'),
    )
    op.create_index('ix_corporate_events_instrument_id', 'corporate_events', ['instrument_id'])

    # ADD COLUMN diretto, non in modalità batch: la ricostruzione della tabella
    # cancellerebbe i trigger che rendono il ledger append-only
    op.add_column('ledger_entries', sa.Column('corporate_event_id', sa.Integer(), nullable=True))
    op.add_column('ledger_entries', sa.Column('withholding_eur', app.database.DecimalText(length=40), nullable=True))
    op.add_column('ledger_entries', sa.Column('ratio', app.database.DecimalText(length=40), nullable=True))
    op.create_index('ix_ledger_entries_corporate_event_id', 'ledger_entries', ['corporate_event_id'])


def downgrade() -> None:
    op.drop_index('ix_ledger_entries_corporate_event_id', 'ledger_entries')
    for col in ('ratio', 'withholding_eur', 'corporate_event_id'):
        op.drop_column('ledger_entries', col)
    op.drop_index('ix_corporate_events_instrument_id', 'corporate_events')
    op.drop_table('corporate_events')
