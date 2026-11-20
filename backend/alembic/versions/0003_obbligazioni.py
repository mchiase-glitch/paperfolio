"""obbligazioni: anagrafica, data di regolamento, rateo e relativa imposta

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
import app.database

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('instruments', sa.Column('issue_date', sa.Date(), nullable=True))
    op.add_column('instruments', sa.Column('lot_size', app.database.DecimalText(length=40), nullable=True))
    op.add_column('instruments', sa.Column('day_count', sa.String(length=10), nullable=True))

    # ADD COLUMN diretto (niente batch): i trigger append-only del ledger devono restare
    op.add_column('ledger_entries', sa.Column('settlement_date', sa.Date(), nullable=True))
    op.add_column('ledger_entries', sa.Column('accrued_interest_eur', app.database.DecimalText(length=40), nullable=True))
    op.add_column('ledger_entries', sa.Column('interest_tax_eur', app.database.DecimalText(length=40), nullable=True))


def downgrade() -> None:
    for col in ('interest_tax_eur', 'accrued_interest_eur', 'settlement_date'):
        op.drop_column('ledger_entries', col)
    for col in ('day_count', 'lot_size', 'issue_date'):
        op.drop_column('instruments', col)
