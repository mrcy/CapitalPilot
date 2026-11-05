"""تولید مستندات API از خود برنامه:  python tools/gen_api_docs.py   →  docs/openapi.json و docs/API.md

بدون نیاز به سرور یا دیتابیس واقعی اجرا می‌شود (از دایرکتوری موقت استفاده می‌کند).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TAGS = {
    "core": "هسته: سلامت، متادیتا، تنظیمات، داشبورد",
    "catalog": "کاتالوگ: ارزها، پلتفرم‌ها، دسته‌بندی‌ها",
    "assets": "دارایی‌ها",
    "portfolios": "سبدها و هدف‌گذاری",
    "transactions": "تراکنش‌ها (دفتر کل)",
    "prices": "قیمت‌ها و کنترل کیفیت",
    "market-data": "منابع قیمت، زمان‌بند و دریافت خودکار",
    "iran-market": "Iran Market Data (قیمت طلا، ارز، کریپتو و سهام ایران)",
    "search": "جست‌وجوی سراسری (بدون تغییر دادهٔ مالی بدون تأیید)",
    "analytics": "تحلیل: عملکرد، ریسک، بازتوازن (بدون سفارش خودکار)",
    "reports": "گزارش‌ها (PDF / Excel / CSV)",
    "data": "پشتیبان‌گیری، بازیابی و بازنشانی",
}


def build() -> dict:
    tmp = tempfile.mkdtemp(prefix="cp-apidocs-")
    os.environ.update(
        CAPITALPILOT_ENV_FILE=str(Path(tmp) / "none.env"),
        DATABASE_URL=f"sqlite:///{tmp}/api.db",
        DATA_DIR=tmp, BACKUP_DIR=f"{tmp}/b", LOG_DIR=f"{tmp}/l",
        SCHEDULER_ENABLED="false", DOCS_ENABLED="true", BASIC_AUTH_USER="", BASIC_AUTH_PASSWORD="",
    )
    from app.main import create_app

    return create_app().openapi()


def ref_name(schema: dict | None) -> str:
    if not schema:
        return ""
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if schema.get("type") == "array" and "items" in schema:
        return f"[{ref_name(schema['items'])}]"
    return schema.get("type", "")


def render(o: dict) -> str:
    L = [
        f"# مستندات API — CapitalPilot {o['info']['version']}",
        "",
        "> این فایل از روی خود برنامه تولید شده است (`python tools/gen_api_docs.py`). مشخصات کامل OpenAPI در `docs/openapi.json` است.",
        "> روی سرور production مستندات تعاملی (`/api/docs`) به‌طور پیش‌فرض خاموش است (`DOCS_ENABLED=false`).",
        "",
        "## قراردادهای عمومی",
        "",
        "- نشانی پایه: `https://<دامنه>/api` — همهٔ پاسخ‌ها JSON هستند و `Cache-Control: no-store` دارند.",
        "- **احراز هویت:** اگر `BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD` تنظیم شده باشد، همهٔ مسیرها (به‌جز `OPTIONS`) Basic Auth می‌خواهند: `curl -u user:pass https://<دامنه>/api/health`.",
        "- **خطاها:** قالب یکسان `{\"error\": {\"code\": \"...\", \"message\": \"پیام فارسی\", \"details\": ...}}`. خطای ۵۰۰ فقط پیام عمومی برمی‌گرداند؛ جزئیات فنی فقط در لاگ سرور است.",
        "- **اعتبارسنجی:** کدهای `422` (ورودی نامعتبر)، `404`، `409` (تعارض/تکراری).",
        "- **اعداد مالی** به‌صورت رشتهٔ دهدهی دقیق (Decimal) ارسال/دریافت می‌شوند، نه float. تاریخ‌ها میلادی (ISO 8601) هستند؛ تبدیل به شمسی فقط در رابط کاربری است.",
        "- **عملیات حساس** (`/api/backup/restore`، `/api/data/reset/*` که دو مرحله‌ای است، و `/api/search/link`، `/api/search/create-asset`، `/api/search/add-to-portfolio`) نیازمند `confirm: true` یا `?confirm=true` هستند.",
        "- **هیچ سفارش خرید/فروش خودکاری** ساخته یا ارسال نمی‌شود؛ کلیدهای API منابع قیمت هرگز در پاسخ‌ها برنمی‌گردند (فقط `has_api_key`).",
        "",
    ]
    by_tag: dict[str, list] = {}
    for path, ms in o["paths"].items():
        for method, d in ms.items():
            by_tag.setdefault((d.get("tags") or ["other"])[0], []).append((path, method.upper(), d))
    order = [t for t in TAGS if t in by_tag] + [t for t in by_tag if t not in TAGS]
    total = sum(len(v) for v in by_tag.values())
    L += [f"## فهرست مسیرها ({total} عملیات)", ""]
    for tag in order:
        L += [f"### {TAGS.get(tag, tag)}  (`{tag}`)", "", "| متد | مسیر | پارامترها | بدنه | پاسخ |", "|---|---|---|---|---|"]
        for path, method, d in sorted(by_tag[tag], key=lambda x: (x[0], x[1])):
            params = ", ".join(f"`{p['name']}`" + ("*" if p.get("required") else "") for p in d.get("parameters", []))
            body = ref_name(d.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema"))
            ok = next((c for c in d.get("responses", {}) if c.startswith("2")), "")
            resp = ref_name(d.get("responses", {}).get(ok, {}).get("content", {}).get("application/json", {}).get("schema")) if ok else ""
            L.append(f"| {method} | `{path}` | {params or '—'} | {('`'+body+'`') if body else '—'} | {ok} {('`'+resp+'`') if resp else ''} |")
        L.append("")
    L += ["(* = اجباری)", "", "## مثال‌ها", "", "```bash",
          "curl -s https://<دامنه>/api/health",
          "curl -s -u USER:PASS https://<دامنه>/api/search?q=طلا",
          "curl -s -u USER:PASS -X POST https://<دامنه>/api/backup/db",
          "```", ""]
    return "\n".join(L)


def main() -> None:
    o = build()
    out = ROOT / "docs"
    out.mkdir(exist_ok=True)
    (out / "openapi.json").write_text(json.dumps(o, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "API.md").write_text(render(o), encoding="utf-8")
    print(f"docs/openapi.json و docs/API.md ساخته شد ({len(o['paths'])} مسیر)")


if __name__ == "__main__":
    main()
