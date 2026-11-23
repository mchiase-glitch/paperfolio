FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Rome \
    DATABASE_URL=sqlite:////data/paperfolio.db \
    FRONTEND_DIR=/app/frontend

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/app backend/app
COPY backend/alembic backend/alembic
COPY backend/alembic.ini backend/alembic.ini
COPY backend/data backend/data
COPY frontend frontend

VOLUME /data
EXPOSE 8042

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8042/api/health')"

# Un solo processo: il job degli ordini in attesa non deve girare due volte
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8042", "--workers", "1"]
