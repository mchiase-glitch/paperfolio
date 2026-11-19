import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR.parent / ".env")
load_dotenv(BACKEND_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'data' / 'paperfolio.db'}")
PORT = int(os.getenv("PORT", "8042"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
DISPLAY_TZ = os.getenv("DISPLAY_TZ", "Europe/Rome")
INITIAL_CAPITAL = Decimal(os.getenv("INITIAL_CAPITAL", "10000.00"))
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", str(BACKEND_DIR.parent / "frontend")))
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "1") == "1"
