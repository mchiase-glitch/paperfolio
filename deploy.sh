#!/usr/bin/env bash
# Aggiornamento di PaperFolio sul Raspberry Pi: backup del database, git pull, rebuild e riavvio.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Creato .env da .env.example: controlla i valori e rilancia ./deploy.sh"
  exit 1
fi
set -a; . ./.env; set +a

DATA_DIR="${PAPERFOLIO_DATA_DIR:-../paperfolio-data}"
PORT="${PORT:-8042}"
mkdir -p "$DATA_DIR/backups"

# 1. Backup del database (prima di qualsiasi modifica)
if [ -f "$DATA_DIR/paperfolio.db" ]; then
  STAMP="$(date +%Y%m%d-%H%M%S)"
  if [ -n "$(docker compose ps --status running -q paperfolio 2>/dev/null)" ]; then
    # Backup a caldo tramite l'API di SQLite: copia coerente anche con l'app in funzione
    docker compose exec -T paperfolio python -c "
import sqlite3
src = sqlite3.connect('/data/paperfolio.db')
dst = sqlite3.connect('/data/backups/paperfolio-$STAMP.db')
src.backup(dst); dst.close(); src.close()"
  else
    cp "$DATA_DIR/paperfolio.db" "$DATA_DIR/backups/paperfolio-$STAMP.db"
  fi
  echo "Backup creato: $DATA_DIR/backups/paperfolio-$STAMP.db"
  # Conserva gli ultimi 30 backup
  ls -1t "$DATA_DIR"/backups/paperfolio-*.db 2>/dev/null | tail -n +31 | xargs -r rm --
else
  echo "Nessun database esistente: primo avvio."
fi

# 2. Codice aggiornato
git pull --ff-only

# 3. Rebuild e riavvio (le migrazioni del database partono da sole all'avvio)
docker compose up -d --build

# 4. Verifica
for i in $(seq 1 30); do
  if curl -fsS "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
    echo "PaperFolio è attivo sulla porta $PORT"
    exit 0
  fi
  sleep 2
done
echo "ATTENZIONE: l'app non risponde. Controlla i log con: docker compose logs --tail 100"
exit 1
