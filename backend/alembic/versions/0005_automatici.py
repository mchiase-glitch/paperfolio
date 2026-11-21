"""portafogli automatici: universi, strategie, registro, cache prezzi storica

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa
import app.database

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nuove colonne su tabelle esistenti
    op.add_column('accounts', sa.Column('strategy_config_id', sa.Integer(), nullable=True))
    op.add_column('orders', sa.Column('trailing_distance', app.database.DecimalText(length=40), nullable=True))

    # Liste universo
    op.create_table(
        'universe_lists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('updated_at', app.database.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'universe_list_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('list_id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(40), nullable=False),
        sa.Column('name', sa.String(200), nullable=True),
        sa.Column('isin', sa.String(12), nullable=True),
        sa.ForeignKeyConstraint(['list_id'], ['universe_lists.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('list_id', 'symbol', name='uq_list_symbol'),
    )

    # Configurazione strategie
    op.create_table(
        'strategy_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('strategy_type', sa.String(10), nullable=False),
        sa.Column('params_json', sa.Text(), nullable=False),
        sa.Column('is_paused', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_drawdown_braking', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', app.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # Registro esecuzioni
    op.create_table(
        'strategy_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('strategy_config_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('run_key', sa.String(100), nullable=False),
        sa.Column('ran_at', app.database.UTCDateTime(), nullable=False),
        sa.Column('is_dry_run', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(10), nullable=False),  # ok / skipped / error
        sa.Column('note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['strategy_config_id'], ['strategy_configs.id']),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_key'),
    )

    # Decisioni (registro in italiano)
    op.create_table(
        'strategy_decisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(40), nullable=False),
        sa.Column('action', sa.String(10), nullable=False),  # buy / sell / hold / skip
        sa.Column('reason_it', sa.Text(), nullable=False),
        sa.Column('signal_data_json', sa.Text(), nullable=True),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('created_at', app.database.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['strategy_runs.id']),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # Cache storico prezzi (per backtest e indicatori)
    op.create_table(
        'price_history_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(40), nullable=False, index=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('open', sa.Float(), nullable=True),
        sa.Column('high', sa.Float(), nullable=True),
        sa.Column('low', sa.Float(), nullable=True),
        sa.Column('close', sa.Float(), nullable=False),
        sa.Column('volume', sa.Integer(), nullable=True),
        sa.Column('dividend', sa.Float(), nullable=False, server_default='0'),
        sa.Column('split_ratio', sa.Float(), nullable=False, server_default='1'),
        sa.Column('fetched_at', app.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'date', name='uq_price_history_symbol_date'),
    )


def downgrade() -> None:
    op.drop_table('price_history_cache')
    op.drop_table('strategy_decisions')
    op.drop_table('strategy_runs')
    op.drop_table('strategy_configs')
    op.drop_table('universe_list_items')
    op.drop_table('universe_lists')
    op.drop_column('orders', 'trailing_distance')
    op.drop_column('accounts', 'strategy_config_id')
