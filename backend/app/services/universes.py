"""
Gestione delle liste di universo (FTSE MIB, Euro Stoxx 50, S&P 100, personalizzate).

Le liste sono salvate nel DB e modificabili dall'app.
Il seed iniziale viene caricato da backend/data/universi/*.json al primo avvio.
"""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import requests
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import utcnow
from ..models import UniverseList, UniverseListItem

log = logging.getLogger("paperfolio.universes")

DATA_DIR = Path(__file__).parent.parent / "data" / "universi"

SYSTEM_LISTS = ["ftse_mib", "eurostoxx50", "sp100"]
WIKIPEDIA_URLS = {
    "ftse_mib": ("https://en.wikipedia.org/wiki/FTSE_MIB", 2, "Ticker", "Company", "ISIN"),
    "eurostoxx50": ("https://en.wikipedia.org/wiki/EURO_STOXX_50", 3, "Ticker", "Name", None),
    "sp100": ("https://en.wikipedia.org/wiki/S%26P_100", 2, "Symbol", "Name", None),
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PaperFolio/1.0)"}
SYMBOL_FIXES = {"BRK.B": "BRK-B"}


# ── Seed al primo avvio ───────────────────────────────────────────────────────

def seed_universes(db: Session) -> None:
    """Carica le liste di universo dai file JSON se non sono ancora presenti nel DB."""
    for list_name in SYSTEM_LISTS:
        if db.scalar(select(UniverseList).where(UniverseList.name == list_name)) is not None:
            continue
        path = DATA_DIR / f"{list_name}.json"
        if not path.exists():
            log.warning("File universo non trovato: %s", path)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.error("Errore lettura %s: %s", path, exc)
            continue
        lst = UniverseList(name=data["name"], label=data["label"], source="seed", updated_at=utcnow())
        db.add(lst)
        db.flush()
        for item in data.get("items", []):
            db.add(UniverseListItem(
                list_id=lst.id,
                symbol=item["symbol"],
                name=item.get("name"),
                isin=item.get("isin") or None,
            ))
    # Simboli caricati in passato in un formato che yfinance non riconosce
    for old, new in SYMBOL_FIXES.items():
        for item in db.scalars(select(UniverseListItem).where(UniverseListItem.symbol == old)):
            item.symbol = new
    db.commit()


# ── Lettura ───────────────────────────────────────────────────────────────────

def get_list(db: Session, name: str) -> UniverseList | None:
    return db.scalar(select(UniverseList).where(UniverseList.name == name))


def get_all_lists(db: Session) -> list[UniverseList]:
    return list(db.scalars(select(UniverseList).order_by(UniverseList.id)))


def get_symbols(db: Session, list_names: list[str]) -> list[str]:
    """Restituisce i simboli distinti delle liste indicate (senza duplicati)."""
    seen: set[str] = set()
    result: list[str] = []
    for lst in db.scalars(select(UniverseList).where(UniverseList.name.in_(list_names))):
        for item in db.scalars(select(UniverseListItem).where(UniverseListItem.list_id == lst.id)):
            if item.symbol not in seen:
                seen.add(item.symbol)
                result.append(item.symbol)
    return result


def get_items(db: Session, list_name: str) -> list[UniverseListItem]:
    lst = get_list(db, list_name)
    if lst is None:
        return []
    return list(db.scalars(
        select(UniverseListItem).where(UniverseListItem.list_id == lst.id).order_by(UniverseListItem.symbol)
    ))


# ── Modifica ──────────────────────────────────────────────────────────────────

def create_custom_list(db: Session, name: str, label: str) -> UniverseList:
    lst = UniverseList(name=name, label=label, source="manual", updated_at=utcnow())
    db.add(lst)
    db.commit()
    return lst


def update_items(db: Session, list_name: str, items: list[dict]) -> int:
    """
    Sostituisce tutti i titoli della lista.
    items: [{"symbol": ..., "name": ..., "isin": ...}, ...]
    """
    lst = get_list(db, list_name)
    if lst is None:
        raise ValueError(f"Lista non trovata: {list_name}")
    # Cancella e reinserisce (le liste di universo non sono append-only)
    for item in db.scalars(select(UniverseListItem).where(UniverseListItem.list_id == lst.id)):
        db.delete(item)
    db.flush()
    for item in items:
        sym = item.get("symbol", "").strip()
        if not sym:
            continue
        db.add(UniverseListItem(
            list_id=lst.id, symbol=sym,
            name=item.get("name") or None,
            isin=item.get("isin") or None,
        ))
    lst.source = "manual"
    lst.updated_at = utcnow()
    db.commit()
    return len(items)


# ── Aggiornamento da Wikipedia ────────────────────────────────────────────────

def refresh_from_wikipedia(db: Session, list_name: str) -> dict:
    """
    Scarica la composizione attuale da Wikipedia e mostra le differenze.
    Restituisce {"added": [...], "removed": [...], "applied": bool}.
    Non modifica il DB (apply=False). Chiamare update_items per applicare.
    """
    if list_name not in WIKIPEDIA_URLS:
        raise ValueError(f"Nessuna fonte Wikipedia per: {list_name}")
    url, tbl_idx, sym_col, name_col, isin_col = WIKIPEDIA_URLS[list_name]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        df = tables[tbl_idx]
    except Exception as exc:
        raise RuntimeError(f"Errore Wikipedia: {exc}") from exc

    new_items = []
    for _, row in df.iterrows():
        sym = str(row.get(sym_col, "")).strip()
        sym = SYMBOL_FIXES.get(sym, sym)
        name = str(row.get(name_col, "")).strip() if name_col else ""
        isin = str(row.get(isin_col, "")).strip() if isin_col else ""
        if sym and sym.lower() != "nan":
            new_items.append({"symbol": sym, "name": name, "isin": isin})

    current_symbols = {i.symbol for i in get_items(db, list_name)}
    new_symbols = {i["symbol"] for i in new_items}
    added = [s for s in new_symbols if s not in current_symbols]
    removed = [s for s in current_symbols if s not in new_symbols]
    return {"added": added, "removed": removed, "new_items": new_items, "applied": False}


def apply_wikipedia_refresh(db: Session, list_name: str, new_items: list[dict]) -> int:
    return update_items(db, list_name, new_items)
