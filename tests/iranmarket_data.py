"""دادهٔ واقعی Iran Market Data برای آزمون‌ها (و پر کردن دیتابیس آزمایشی رابط کاربری از مسیر واقعی دریافت و پردازش)."""
import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "iranmarket_latest_toman_20261104.json.gz"
URL_PATH = "latest-toman.json"
REAL_GENERATED = datetime(2026, 11, 4, 14, 0, 1, tzinfo=timezone.utc)


def load_real() -> dict:
    return json.load(gzip.open(FIXTURE))


def records(payload):
    return [r for lst in payload["data"]["categories"].values() for r in lst]


def rec(payload, symbol):
    return next(r for r in records(payload) if r["symbol"] == symbol)


def _shift(iso, delta):
    if not isinstance(iso, str):
        return iso
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")) + delta
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def retimed(minutes_ago=20, payload=None) -> dict:
    """زمان همهٔ فیلدهای زمانی را طوری جابه‌جا می‌کند که generated_at = «minutes_ago دقیقه پیش» شود."""
    p = payload or load_real()
    target = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    delta = target - REAL_GENERATED
    p["data"]["generated_at"] = _shift(p["data"]["generated_at"], delta)
    p["meta"]["published_at"] = _shift(p["meta"]["published_at"], delta)
    for r in records(p):
        for k in ("timestamp", "checked_at"):
            r[k] = _shift(r.get(k), delta)
    return p




def seed_database() -> dict:
    """دیتابیس جاری (طبق متغیرهای محیطی) را با همان مسیر واقعی fetch_snapshot و فایل واقعی (زمان‌های جابه‌جاشده) پر می‌کند.
    منبع Iran Market فعال می‌شود. فقط برای آزمون و تصویربرداری؛ شبکه استفاده نمی‌شود."""
    import httpx

    from app.database import SessionLocal
    from app.main import init_db
    from app.services.marketdata import http, iranmarket as im

    init_db()
    payload = retimed(25)
    body = json.dumps(payload, ensure_ascii=False).encode()
    http.set_test_transport(httpx.MockTransport(lambda req: httpx.Response(200, content=body, headers={"etag": '"seed"'})))
    try:
        with SessionLocal() as db:
            pv = im.get_provider(db)
            pv.is_enabled = True
            db.commit()
            return im.fetch_snapshot(db, pv, raise_errors=True)
    finally:
        http.set_test_transport(None)


if __name__ == "__main__":
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
    print(seed_database())
