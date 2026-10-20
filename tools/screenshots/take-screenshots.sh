#!/bin/sh
# Regenerates docs/screenshots with fake data only. Needs uv and Docker; the throwaway database
# runs on port 55432 so it never touches the one of `make db`.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/../.."
WORK="$(mktemp -d)"
DB=dimonapp-screenshots-db
PORT=8599

cleanup() {
    [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null
    docker rm -f "$DB" >/dev/null 2>&1
    rm -rf "$WORK"
}
trap cleanup EXIT

docker run -d --rm --name "$DB" -p 55432:5432 \
    -e POSTGRES_USER=dimonapp -e POSTGRES_PASSWORD=dimonapp -e POSTGRES_DB=dimonapp \
    postgres:16 >/dev/null
until docker exec "$DB" pg_isready -U dimonapp >/dev/null 2>&1; do sleep 1; done

export APP_ENV=TEST
export DATABASE_URL=postgresql+psycopg://dimonapp:dimonapp@localhost:55432/dimonapp
export STORAGE_FOLDER="$WORK/storage"
export SEED_PASSWORD=demo-password
export SEED_ADMIN_EMAIL=
cd "$ROOT"
uv run alembic upgrade head
uv run python -m dimonapp.fake_data
uv run python tools/screenshots/demo_activities.py
uv run python -m dimonapp.page_locale

uv run streamlit run tools/screenshots/shots_app.py \
    --server.port "$PORT" --server.headless true >"$WORK/streamlit.log" 2>&1 &
APP_PID=$!

uv run --with playwright playwright install chromium
uv run --with playwright python tools/screenshots/take_screenshots.py \
    "http://localhost:$PORT" docs/screenshots "$SEED_PASSWORD"
