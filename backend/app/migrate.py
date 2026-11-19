from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent


def upgrade_to_head(connection=None) -> None:
    """Applica le migrazioni mancanti. Chiamata all'avvio: un aggiornamento non perde mai i dati."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    if connection is not None:
        cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")
