#!/usr/bin/env bash
# اجرای CapitalPilot روی Linux/macOS: ./run.sh  (پورت: PORT=9000 ./run.sh)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
. .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "CapitalPilot → http://127.0.0.1:${PORT:-8000}   (مستندات API: /api/docs)"
exec uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
