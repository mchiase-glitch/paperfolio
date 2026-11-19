from alembic import context

from app import models  # noqa: F401  registra le tabelle
from app.database import Base, engine

target_metadata = Base.metadata


def run_migrations() -> None:
    connectable = context.config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
