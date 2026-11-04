"""مجوزهای محدود برای فایل‌های حساس (دیتابیس، پشتیبان‌ها، کلید رمزنگاری). خطاها نادیده گرفته می‌شوند (مثلاً فایل‌سیستم بدون chmod)."""
from __future__ import annotations

import os
from pathlib import Path


def secure_file(path: Path | str) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def secure_dir(path: Path | str) -> None:
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def harden_runtime_paths(s) -> None:
    """پس از ساخت دیتابیس: DB و فایل‌های جانبی WAL=600، پوشهٔ پشتیبان=700، (در production) پوشهٔ داده=700."""
    p = s.sqlite_path
    if p is not None:
        for suffix in ("", "-wal", "-shm"):
            f = Path(str(p) + suffix)
            if f.exists():
                secure_file(f)
    if s.backup_dir.exists():
        secure_dir(s.backup_dir)
        for f in s.backup_dir.glob("capitalpilot-*"):
            if f.is_file():
                secure_file(f)
    key = s.data_dir / ".secret_key"
    if key.exists():
        secure_file(key)
    if s.is_production and s.data_dir.exists():
        secure_dir(s.data_dir)
