#!/bin/sh
# Runs every time the container starts: wait for the database, prepare it, start the server.
set -e

echo "Waiting for the database..."
python - <<'PY'
import os, sys, time
import psycopg

url = os.environ.get("DATABASE_URL")
kwargs = dict(
    dbname=os.environ.get("POSTGRES_DB", "salama"),
    user=os.environ.get("POSTGRES_USER", "salama"),
    password=os.environ.get("POSTGRES_PASSWORD", ""),
    host=os.environ.get("POSTGRES_HOST", "localhost"),
    port=os.environ.get("POSTGRES_PORT", "5432"),
)
for attempt in range(40):
    try:
        psycopg.connect(url) if url else psycopg.connect(**kwargs)
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"  database not ready yet ({attempt + 1}/40)")
        time.sleep(2)
print("Database never became ready"); sys.exit(1)
PY

python manage.py migrate --noinput
python manage.py createcachetable
python manage.py collectstatic --noinput

exec "$@"
