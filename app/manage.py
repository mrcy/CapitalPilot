"""ابزار خط فرمان مدیریت CapitalPilot برای استقرار (نصب، به‌روزرسانی، پشتیبان‌گیری و بازیابی).

    python -m app.manage version
    python -m app.manage check                 # بررسی تنظیمات، مسیرها، سلامت و نسخهٔ طرح‌واره (فقط‌خواندنی)
    python -m app.manage migrate               # اجرای مهاجرت‌ها (پیش از مهاجرت، پشتیبان خودکار می‌گیرد)
    python -m app.manage backup [--dir DIR] [--keep N]
    python -m app.manage restore FILE [--yes]  # فقط وقتی سرویس متوقف است

پشتیبان SQLite با API رسمی sqlite3 (Online Backup) گرفته می‌شود؛ حتی با سرویس روشن و حالت WAL سازگار و کامل است.
هیچ‌کدام از دستورها داده‌ها را حذف نمی‌کنند؛ بازیابی ابتدا از دیتابیس فعلی یک نسخهٔ ایمنی می‌گیرد.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import ENV_FILE, get_settings


def _db_path() -> Path:
    p = get_settings().sqlite_path
    if p is None:
        sys.exit("این دستور فقط برای SQLite است؛ برای PostgreSQL از pg_dump استفاده کنید.")
    return p


def _single_file(path: Path) -> None:
    """نسخهٔ پشتیبان را از حالت WAL خارج می‌کند تا یک فایل مستقل و بدون -wal/-shm باشد."""
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=DELETE")
    finally:
        con.close()


def _integrity(path: Path) -> str:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()


def _schema_version(path: Path) -> int | None:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        has = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
        return con.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] if has else None
    finally:
        con.close()


def cmd_version(_: argparse.Namespace) -> int:
    print(__version__)
    return 0


def cmd_check(_: argparse.Namespace) -> int:
    from .migrations.runner import LATEST_VERSION
    from .main import production_warnings

    s = get_settings()
    ok = True
    print(f"CapitalPilot {__version__}  env={s.app_env}")
    print(f"env file : {ENV_FILE} ({'موجود' if ENV_FILE.exists() else 'ندارد؛ از پیش‌فرض‌ها/متغیرهای محیطی استفاده می‌شود'})")
    print(f"database : {s.database_url.split('://')[0]}  {s.sqlite_path or ''}")
    print(f"data dir : {s.data_dir}\nbackups  : {s.backup_dir}\nlogs     : {s.log_dir}")
    for name, d in (("data", s.data_dir), ("backup", s.backup_dir), ("log", s.log_dir)):
        d.mkdir(parents=True, exist_ok=True)
        if not os.access(d, os.W_OK):
            print(f"✗ پوشهٔ {name} قابل نوشتن نیست: {d}")
            ok = False
    p = s.sqlite_path
    if p and p.exists():
        res = _integrity(p)
        print(f"integrity: {res}")
        cur = _schema_version(p)
        print(f"schema    : {cur if cur is not None else '—'} / {LATEST_VERSION}" + ("  (migrate لازم است)" if cur != LATEST_VERSION else ""))
        ok &= res == "ok"
        mode = p.stat().st_mode & 0o777
        if mode & 0o077:
            print(f"⚠ مجوز فایل دیتابیس {oct(mode)} است؛ پیشنهاد: chmod 600 {p}")
    elif p:
        print("دیتابیس هنوز ساخته نشده است (در اولین migrate/اجرا ساخته می‌شود).")
    print(f"آخرین نسخهٔ طرح‌واره در کد: {LATEST_VERSION}")
    for w in production_warnings(s):
        print(f"⚠ {w}")
    if s.is_production and s.backup_dir.resolve().is_relative_to((Path(__file__).parent / "static").resolve()):
        print("✗ مسیر Backup داخل پوشهٔ عمومی static است!")
        ok = False
    return 0 if ok else 1


def cmd_migrate(_: argparse.Namespace) -> int:
    from .database import SessionLocal, engine
    from .migrations import run_migrations
    from .services.fsperm import harden_runtime_paths
    from .services.seed import is_seeded, seed_defaults

    info = run_migrations(engine)
    s = get_settings()
    if s.seed_on_startup:
        with SessionLocal() as db:
            if not is_seeded(db):
                seed_defaults(db)
                info["seeded"] = True
    harden_runtime_paths(s)
    print(json.dumps(info, ensure_ascii=False, default=str))
    return 0


def cmd_backup(a: argparse.Namespace) -> int:
    src = _db_path()
    if not src.exists():
        sys.exit(f"دیتابیس پیدا نشد: {src}")
    dest_dir = Path(a.dir) if a.dir else get_settings().backup_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(dest_dir, 0o700)
    dest = dest_dir / f"capitalpilot-{a.label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    out = sqlite3.connect(dest)
    try:
        con.backup(out)
    finally:
        out.close()
        con.close()
    _single_file(dest)
    os.chmod(dest, 0o600)
    res = _integrity(dest)
    if res != "ok":
        dest.unlink(missing_ok=True)
        sys.exit(f"پشتیبان ناسالم بود و حذف شد: {res}")
    print(dest)
    if a.keep and a.keep > 0:
        mine = sorted(dest_dir.glob(f"capitalpilot-{a.label}-*.db"))
        for old in mine[: -a.keep]:
            old.unlink()
    return 0


def cmd_restore(a: argparse.Namespace) -> int:
    src = Path(a.file)
    if not src.is_file():
        sys.exit(f"فایل پشتیبان پیدا نشد: {src}")
    res = _integrity(src)
    if res != "ok":
        sys.exit(f"فایل پشتیبان سالم نیست ({res}) و بازیابی انجام نشد.")
    dst = _db_path()
    if not a.yes:
        sys.exit("برای تأیید بازیابی گزینهٔ --yes را بدهید (سرویس باید متوقف باشد؛ از دیتابیس فعلی نسخهٔ ایمنی گرفته می‌شود).")
    safety = None
    if dst.exists():
        s = get_settings()
        s.backup_dir.mkdir(parents=True, exist_ok=True)
        safety = s.backup_dir / f"capitalpilot-before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
        con = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
        out = sqlite3.connect(safety)
        try:
            con.backup(out)
        finally:
            out.close()
            con.close()
        _single_file(safety)
        os.chmod(safety, 0o600)
        for old in sorted(s.backup_dir.glob("capitalpilot-before-restore-*.db"))[:-10]:
            old.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(dst) + suffix).unlink(missing_ok=True)
    tmp = dst.with_suffix(".restoring")
    shutil.copy2(src, tmp)
    os.chmod(tmp, 0o600)
    os.replace(tmp, dst)
    print(f"بازیابی انجام شد: {src} → {dst}" + (f"\nنسخهٔ ایمنی دیتابیس قبلی: {safety}" if safety else ""))
    print("اکنون «python -m app.manage migrate» و سپس راه‌اندازی سرویس را اجرا کنید (اسکریپت restore.sh این مراحل را انجام می‌دهد).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.manage", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version").set_defaults(fn=cmd_version)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    b = sub.add_parser("backup")
    b.add_argument("--dir")
    b.add_argument("--keep", type=int, default=0, help="نگه‌داشتن N پشتیبان آخر همین برچسب (۰ = بدون حذف)")
    b.add_argument("--label", default="manual")
    b.set_defaults(fn=cmd_backup)
    r = sub.add_parser("restore")
    r.add_argument("file")
    r.add_argument("--yes", action="store_true")
    r.set_defaults(fn=cmd_restore)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
