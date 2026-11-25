"""backtest: esecuzioni e operazioni simulate (tabelle separate dal ledger)

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa
import app.database

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'backtest_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('strategy_config_id', sa.Integer(), nullable=True),
        sa.Column('strategy_type', sa.String(10), nullable=False),
        sa.Column('strategy_version', sa.String(20), nullable=False),
        sa.Column('params_json', sa.Text(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('split_date', sa.Date(), nullable=True),
        sa.Column('initial_capital', app.database.DecimalText(length=40), nullable=False),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('results_json', sa.Text(), nullable=True),
        sa.Column('created_at', app.database.UTCDateTime(), nullable=False),
        sa.Column('finished_at', app.database.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(['strategy_config_id'], ['strategy_configs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_backtest_runs_strategy_config_id', 'backtest_runs', ['strategy_config_id'])
    op.create_table(
        'backtest_trades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('symbol', sa.String(40), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('quantity', app.database.DecimalText(length=40), nullable=False),
        sa.Column('price', app.database.DecimalText(length=40), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('gross_eur', app.database.DecimalText(length=40), nullable=False),
        sa.Column('costs_eur', app.database.DecimalText(length=40), nullable=False),
        sa.Column('tax_eur', app.database.DecimalText(length=40), nullable=False),
        sa.Column('cash_delta_eur', app.database.DecimalText(length=40), nullable=False),
        sa.Column('realized_eur', app.database.DecimalText(length=40), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['backtest_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_backtest_trades_run_id', 'backtest_trades', ['run_id'])


def downgrade() -> None:
    op.drop_index('ix_backtest_trades_run_id', 'backtest_trades')
    op.drop_table('backtest_trades')
    op.drop_index('ix_backtest_runs_strategy_config_id', 'backtest_runs')
    op.drop_table('backtest_runs')
