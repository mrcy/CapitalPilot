"""تست‌های رابط کاربری: واحد (node:test) و سرتاسری (Puppeteer).

- بدون Node این فایل skip می‌شود.
- تست سرتاسری بدون مرورگر Chrome/Chromium (یا CHROME_PATH، یا بستهٔ @sparticuz/chromium) skip می‌شود.
- نصب وابستگی‌ها: cd tests/frontend && npm install
تست سرتاسری روی سرور و دیتابیس موقت جداگانه اجرا می‌شود و به داده‌های شما دست نمی‌زند.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "tests" / "frontend"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js نصب نیست")


def _run_node(args, env=None, timeout=600):
    return subprocess.run([NODE, *args], cwd=FRONT, env={**os.environ, **(env or {})}, capture_output=True, text=True, timeout=timeout)


def test_format_unit_tests():
    r = _run_node(["--test", "format.test.mjs"])
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1500:]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def live_server():
    tmp = Path(tempfile.mkdtemp(prefix="cp-e2e-srv-"))
    port = _free_port()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp / 'e2e.db'}", "DATA_DIR": str(tmp), "BACKUP_DIR": str(tmp / "backups"),
           "LOG_DIR": str(tmp / "logs"), "SCHEDULER_ENABLED": "false", "APP_TIMEZONE": "Asia/Tehran", "PRICE_API_ALLOWED_HOSTS": ""}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(f"{base}/api/meta", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("سرور تست بالا نیامد")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def test_e2e_browser_suite(live_server):
    if not (FRONT / "node_modules" / "puppeteer-core").exists():
        pytest.skip("puppeteer-core نصب نیست: cd tests/frontend && npm install")
    r = _run_node(["--test", "--test-concurrency=1", "--test-reporter=tap", "e2e.test.mjs"],
                  env={"BASE_URL": live_server, "E2E_ALLOW_DESTRUCTIVE": "1"}, timeout=900)
    out = r.stdout
    if "# pass 0" in out and "# skipped" in out and "# fail 0" in out:
        reason = next((l for l in out.splitlines() if "SKIP" in l.upper()), "")
        pytest.skip(f"مرورگر در دسترس نیست: {reason[:200]}")
    assert r.returncode == 0, out[-6000:] + r.stderr[-1500:]
