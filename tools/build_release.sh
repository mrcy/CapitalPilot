#!/usr/bin/env bash
# ساخت بستهٔ انتشار از فایل‌های ثبت‌شده در Git (HEAD) — هیچ فایل ردیابی‌نشده‌ای (.env، دیتابیس، .venv، node_modules …) وارد بسته نمی‌شود.
#
#   tools/build_release.sh [OUT_DIR]        (پیش‌فرض: ../release کنار مخزن؛ خارج از مخزن)
#
# خروجی: CapitalPilot-v<VERSION>-production.zip و SHA256SUMS.txt (+ کپی راهنماها). پیش از ساخت، تمیز بودن مخزن و به‌روز بودن docs/API.md بررسی می‌شود.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
VER="$(tr -d '[:space:]' < VERSION)"
NAME="CapitalPilot-v${VER}-production"
OUT="${1:-$ROOT/../release}"
PY="${PYTHON:-$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )}"

[ -z "$(git status --porcelain)" ] || { echo "✗ مخزن تمیز نیست؛ ابتدا commit کنید:"; git status --short; exit 1; }
[ "$("$PY" -c 'import app;print(app.__version__)')" = "$VER" ] || { echo "✗ VERSION با app.__version__ یکی نیست"; exit 1; }
"$PY" tools/gen_api_docs.py >/dev/null
git diff --quiet -- docs || { echo "✗ docs/API.md یا openapi.json قدیمی است؛ tools/gen_api_docs.py را اجرا و commit کنید."; git diff --stat -- docs; exit 1; }

mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
rm -f "$OUT/$NAME.zip"
git archive --format=zip --prefix="CapitalPilot-v${VER}/" -9 -o "$OUT/$NAME.zip" HEAD
COMMIT="$(git rev-parse HEAD)"

# ───── بررسی محتوای ZIP
LIST="$(unzip -Z1 "$OUT/$NAME.zip")"
BAD="$(grep -E '(^|/)(\.env|\.git|\.venv|node_modules|__pycache__|\.pytest_cache|\.secret_key)(/|$)|\.(db|sqlite3?|pyc|log|bak)$|-(wal|shm)$|(^|/)data/|(^|/)dist/|(^|/)build/' <<<"$LIST" || true)"
[ -z "$BAD" ] || { echo "✗ فایل ممنوعه در ZIP:"; echo "$BAD"; exit 1; }
for f in app/main.py app/manage.py VERSION RELEASE_NOTES_fa.md README.md requirements.txt requirements.lock .env.example Dockerfile docker-compose.yml install.sh update.sh backup.sh restore.sh \
         deploy/capitalpilot.service.tmpl deploy/nginx-capitalpilot.conf.tmpl docs/API.md docs/INSTALL-UBUNTU-24.04.md docs/NGINX-HTTPS.md docs/BACKUP-RESTORE.md docs/PRICE-SOURCES.md app/static/index.html tests/test_release.py; do
  grep -qx "CapitalPilot-v${VER}/$f" <<<"$LIST" || { echo "✗ در ZIP نیست: $f"; exit 1; }
done
unzip -tq "$OUT/$NAME.zip" >/dev/null

# ───── کپی راهنماها کنار ZIP و SHA256SUMS
cp RELEASE_NOTES_fa.md "$OUT/RELEASE_NOTES_fa.md"
for d in INSTALL-UBUNTU-24.04 NGINX-HTTPS BACKUP-RESTORE PRICE-SOURCES DOCKER SECURITY API; do cp "docs/$d.md" "$OUT/$d.md"; done
cp docs/openapi.json "$OUT/openapi.json"
( cd "$OUT" && sha256sum "$NAME.zip" > SHA256SUMS.txt && sha256sum -c SHA256SUMS.txt >/dev/null )
printf '%s\n' "$COMMIT" > "$OUT/COMMIT.txt"
echo "✓ $OUT/$NAME.zip  ($(stat -c %s "$OUT/$NAME.zip") bytes, $(grep -c . <<<"$LIST") مورد)  commit=${COMMIT:0:7}"
cat "$OUT/SHA256SUMS.txt"
