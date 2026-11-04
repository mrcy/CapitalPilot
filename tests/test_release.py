"""آزمون‌های بستهٔ انتشار/Production: نسخه، پیکربندی، امنیت، ابزار manage و اسکریپت‌های استقرار."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".pytest_cache", ".git", "data"}


def _project_files() -> list[Path]:
    """فایل‌های پروژه: اگر مخزن Git باشد فقط فایل‌های ردیابی‌شده؛ وگرنه (بستهٔ استخراج‌شده) همهٔ فایل‌ها."""
    if (ROOT / ".git").exists() and shutil.which("git"):
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode()
        return [ROOT / p for p in out.split("\0") if p and (ROOT / p).is_file()]
    return [p for p in ROOT.rglob("*") if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS)]


def _is_text(p: Path) -> bool:
    return p.suffix.lower() not in {".woff", ".woff2", ".ttf", ".png", ".jpg", ".ico", ".gz", ".zip", ".pdf", ".db"}


# ───────────────────────── نسخه
def test_version_is_consistent_everywhere():
    from app import __version__

    v = (ROOT / "VERSION").read_text().strip()
    assert v == __version__ == "2.4.0"
    assert re.search(rf'^version\s*=\s*"{re.escape(v)}"', (ROOT / "pyproject.toml").read_text(), re.M)
    assert json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))["info"]["version"] == v
    assert v in (ROOT / "RELEASE_NOTES_fa.md").read_text(encoding="utf-8")
    assert v in (ROOT / "docs" / "API.md").read_text(encoding="utf-8")


def test_health_reports_version(client):
    from app import __version__

    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "version": __version__}


# ───────────────────────── .env.example
def _env_example_keys() -> dict[str, str]:
    out = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#?\s?([A-Z][A-Z0-9_]+)=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def test_env_example_matches_settings_and_has_no_secrets():
    from app.config import Settings

    fields = {f.upper() for f in Settings.model_fields}
    keys = _env_example_keys()
    unknown = [k for k in keys if k not in fields and k != "CAPITALPILOT_ENV_FILE"]
    assert not unknown, f"کلیدهای ناشناخته در .env.example: {unknown}"
    for k in ("SECRET_KEY", "BASIC_AUTH_PASSWORD", "BASIC_AUTH_USER", "STREAMDATA_API_KEY", "SERVIX_API_KEY"):
        assert keys.get(k, "") == "", f"{k} نباید در .env.example مقدار داشته باشد"
    for k in ("APP_ENV", "ALLOWED_HOSTS", "CORS_ORIGINS", "DATA_DIR", "BACKUP_DIR", "LOG_DIR"):
        assert k in keys, f"{k} در .env.example مستند نشده است"


def test_no_env_db_or_secret_files_in_project():
    bad = []
    for p in _project_files():
        rel = p.relative_to(ROOT)
        if rel.name == ".env" or rel.name == ".secret_key" or rel.suffix in {".db", ".sqlite", ".sqlite3"} or rel.name.endswith(("-wal", "-shm")):
            bad.append(str(rel))
    assert not bad, bad


SECRET_PATTERNS = [re.compile(p) for p in (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"\bsk-[A-Za-z0-9]{20,}", r"\bghp_[A-Za-z0-9]{30,}", r"\bAKIA[0-9A-Z]{16}\b",
                                            r"(?i)\b(api[_-]?key|secret|password)\s*[:=]\s*['\"][A-Za-z0-9+/_\-]{16,}['\"]")]


def test_no_secret_like_strings_in_project():
    hits = []
    for p in _project_files():
        if not _is_text(p) or p.stat().st_size > 2_000_000 or "package-lock" in p.name or p.suffix == ".js" and "vendor" in p.parts:
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pat in SECRET_PATTERNS:
            m = pat.search(txt)
            if m:
                hits.append((str(p.relative_to(ROOT)), m.group(0)[:40]))
    assert not hits, hits


def test_no_dev_absolute_paths_in_runtime_files():
    pat = re.compile(r"/home/(?!capitalpilot)\w+|/Users/\w+|C:\\\\Users")
    hits = []
    for p in _project_files():
        rel = p.relative_to(ROOT)
        if rel.parts[0] in {"app", "deploy"} or rel.name in {"Dockerfile", "docker-compose.yml", "run.sh", "install.sh", "update.sh", "backup.sh", "restore.sh", ".env.example", "requirements.txt"}:
            if _is_text(p) and pat.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(rel))
    assert not hits, hits


# ───────────────────────── اسکریپت‌ها و قالب‌ها
SCRIPTS = ["install.sh", "update.sh", "backup.sh", "restore.sh", "run.sh", "deploy/common.sh"]


@pytest.mark.parametrize("script", SCRIPTS)
def test_shell_scripts_parse_and_are_executable(script):
    p = ROOT / script
    assert p.is_file()
    if script != "deploy/common.sh":
        assert os.access(p, os.X_OK), f"{script} اجرایی نیست"
    assert subprocess.run(["bash", "-n", str(p)], capture_output=True).returncode == 0
    assert p.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash") or script == "deploy/common.sh"


def test_install_script_never_overwrites_env_without_checking():
    src = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'if [ -f "$ENV_FILE" ]; then' in src  # فقط وقتی .env نیست ساخته می‌شود
    assert "set -euo pipefail" in src and "set -euo pipefail" in (ROOT / "update.sh").read_text(encoding="utf-8")
    upd = (ROOT / "update.sh").read_text(encoding="utf-8")
    assert "rollback" in upd and "manage backup" in upd and ".env" in upd


def test_templates_use_only_known_placeholders():
    known = {"APP_DIR", "USER", "PORT", "ENV_FILE", "DATA_DIR", "BACKUP_DIR", "LOG_DIR", "DOMAIN"}
    tmpls = list((ROOT / "deploy").glob("*.tmpl"))
    assert len(tmpls) == 4
    for t in tmpls:
        used = set(re.findall(r"@([A-Z_]+)@", t.read_text(encoding="utf-8")))
        assert used <= known, (t.name, used - known)
    svc = (ROOT / "deploy" / "capitalpilot.service.tmpl").read_text(encoding="utf-8")
    assert "--workers 1" in svc and "--reload" not in svc and "127.0.0.1" in svc and "NoNewPrivileges=true" in svc and "UMask=0077" in svc


# ───────────────────────── مجوزها
def test_harden_runtime_paths_sets_restrictive_modes(tmp_path):
    from app.config import Settings
    from app.services.fsperm import harden_runtime_paths

    data = tmp_path / "d"
    (data / "backups").mkdir(parents=True)
    db = data / "x.db"
    db.write_text("x")
    (data / "backups" / "capitalpilot-a.db").write_text("x")
    (data / ".secret_key").write_text("k")
    for f in (db, data / "backups" / "capitalpilot-a.db", data / ".secret_key"):
        os.chmod(f, 0o644)
    s = Settings(database_url=f"sqlite:///{db}", data_dir=data, backup_dir=data / "backups", log_dir=data / "logs", app_env="production")
    harden_runtime_paths(s)
    mode = lambda p: p.stat().st_mode & 0o777  # noqa: E731
    assert mode(db) == 0o600 and mode(data / ".secret_key") == 0o600 and mode(data / "backups" / "capitalpilot-a.db") == 0o600
    assert mode(data / "backups") == 0o700 and mode(data) == 0o700


def test_app_backups_are_private(client):
    from app.config import get_settings
    from app.services.backup import save_db_backup

    res = save_db_backup(None, "perm-test")
    d = get_settings().backup_dir
    assert (d.stat().st_mode & 0o777) == 0o700
    for name in res["files"]:
        assert ((d / name).stat().st_mode & 0o777) == 0o600


def test_backup_dir_is_not_served_statically(client):
    from app.config import get_settings
    from app.main import STATIC_DIR

    assert not get_settings().backup_dir.resolve().is_relative_to(STATIC_DIR.resolve())
    assert client.get("/static/../data/capitalpilot.db").status_code in (400, 404)
    assert client.get("/static/backups/").status_code == 404


# ───────────────────────── Middleware های امنیتی
@pytest.fixture()
def make_app(monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_settings

    def _make(**env):
        for k in ("APP_ENV", "ALLOWED_HOSTS", "CORS_ORIGINS", "DOCS_ENABLED", "BASIC_AUTH_USER", "BASIC_AUTH_PASSWORD"):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        from app.main import create_app

        return TestClient(create_app(), raise_server_exceptions=False, base_url="http://testserver")

    yield _make
    get_settings.cache_clear()


def test_docs_can_be_disabled(make_app):
    c = make_app(DOCS_ENABLED="false")
    for path in ("/api/docs", "/api/redoc", "/api/openapi.json"):
        assert c.get(path).status_code == 404, path
    assert c.get("/api/health").status_code == 200
    assert make_app(DOCS_ENABLED="true").get("/api/openapi.json").status_code == 200


def test_trusted_hosts(make_app):
    c = make_app(ALLOWED_HOSTS="capital.example.com")
    assert c.get("/api/health", headers={"host": "capital.example.com"}).status_code == 200
    assert c.get("/api/health", headers={"host": "capital.example.com:8000"}).status_code == 200
    assert c.get("/api/health", headers={"host": "evil.example"}).status_code == 400
    assert c.get("/api/health", headers={"host": "127.0.0.1:8000"}).status_code == 200  # health check محلی همیشه مجاز
    assert c.get("/api/health", headers={"host": "localhost"}).status_code == 200
    # بدون ALLOWED_HOSTS محدودیتی نیست
    assert make_app().get("/api/health", headers={"host": "anything.example"}).status_code == 200


def test_cors_closed_by_default_and_explicit_origins_only(make_app):
    c = make_app()
    r = c.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    c = make_app(CORS_ORIGINS="https://ok.example, *")
    r = c.get("/api/health", headers={"Origin": "https://ok.example"})
    assert r.headers.get("access-control-allow-origin") == "https://ok.example"
    r = c.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    r = c.options("/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers
    assert "access-control-allow-credentials" not in r.headers


def test_cors_wildcard_alone_is_ignored(make_app):
    r = make_app(CORS_ORIGINS="*").get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_hsts_only_in_production_over_https(make_app):
    prod = make_app(APP_ENV="production")
    assert "strict-transport-security" not in prod.get("/api/health").headers  # HTTP ساده
    assert "strict-transport-security" in make_app(APP_ENV="production", ).get("https://testserver/api/health").headers
    assert "strict-transport-security" not in make_app(APP_ENV="development").get("https://testserver/api/health").headers
    h = prod.get("/api/health").headers
    assert h["x-content-type-options"] == "nosniff" and "permissions-policy" in h and h["cache-control"] == "no-store"


def test_basic_auth_protects_everything_but_hosts_checked_first(make_app):
    c = make_app(BASIC_AUTH_USER="u", BASIC_AUTH_PASSWORD="p-secret", ALLOWED_HOSTS="capital.example.com")
    assert c.get("/api/health", headers={"host": "capital.example.com"}).status_code == 401
    assert c.get("/api/health", headers={"host": "capital.example.com"}, auth=("u", "wrong")).status_code == 401
    assert c.get("/api/health", headers={"host": "capital.example.com"}, auth=("u", "p-secret")).status_code == 200
    assert c.get("/api/health", headers={"host": "evil.example"}, auth=("u", "p-secret")).status_code == 400
    assert c.get("/", headers={"host": "capital.example.com"}).status_code == 401
    assert c.get("/static/index.html", headers={"host": "capital.example.com"}).status_code in (401, 404)


def test_unhandled_errors_do_not_leak_details(make_app):
    from fastapi import APIRouter

    app_client = make_app()
    app = app_client.app
    r = APIRouter()

    @r.get("/api/_boom")
    def boom():
        raise RuntimeError("SECRET-INTERNAL-DETAIL /opt/capitalpilot/.env password=hunter2")

    app.router.routes.insert(0, r.routes[0])
    resp = app_client.get("/api/_boom")
    assert resp.status_code == 500
    body = resp.text
    assert "SECRET-INTERNAL-DETAIL" not in body and "hunter2" not in body and "Traceback" not in body and "RuntimeError" not in body
    assert resp.json()["error"]["code"] == "internal_error"


def test_production_warnings_and_flags():
    from app.config import Settings
    from app.main import production_warnings

    assert production_warnings(Settings(app_env="development")) == []
    w = production_warnings(Settings(app_env="production"))
    assert len(w) == 3
    safe = Settings(app_env="production", docs_enabled=False, allowed_hosts="a.example", basic_auth_user="u", basic_auth_password="p")
    assert production_warnings(safe) == []
    assert Settings(allowed_hosts="a.example, b.example").allowed_host_list[:2] == ["a.example", "b.example"]
    assert Settings(cors_origins="https://a.example/, *").cors_origin_list == ["https://a.example"]


# ───────────────────────── ابزار manage (پشتیبان/بازیابی/مهاجرت)
def _manage(env_dir: Path, *args: str, extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "DATA_DIR", "BACKUP_DIR", "LOG_DIR"}}
    env.update(
        CAPITALPILOT_ENV_FILE=str(env_dir / "absent.env"), DATABASE_URL=f"sqlite:///{env_dir}/data/cp.db", DATA_DIR=str(env_dir / "data"),
        BACKUP_DIR=str(env_dir / "backups"), LOG_DIR=str(env_dir / "logs"), SCHEDULER_ENABLED="false", PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
    )
    env.update(extra or {})
    return subprocess.run([sys.executable, "-m", "app.manage", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


def test_manage_migrate_check_backup_restore_roundtrip(tmp_path):
    assert _manage(tmp_path, "version").stdout.strip() == "2.4.0"
    r = _manage(tmp_path, "migrate")
    assert r.returncode == 0, r.stderr
    info = json.loads(r.stdout.strip().splitlines()[-1])
    assert info["fresh"] is True and info["applied"] == [1, 2, 3, 4]
    r = _manage(tmp_path, "migrate")  # دوباره: چیزی اعمال نمی‌شود
    assert json.loads(r.stdout.strip().splitlines()[-1])["applied"] == []
    r = _manage(tmp_path, "check")
    assert r.returncode == 0 and "integrity: ok" in r.stdout and "schema    : 4 / 4" in r.stdout
    db = tmp_path / "data" / "cp.db"
    assert db.stat().st_mode & 0o077 == 0, "دیتابیس باید 600 باشد"

    con = sqlite3.connect(db)
    n_assets = con.execute("select count(*) from assets").fetchone()[0]
    con.close()

    r = _manage(tmp_path, "backup", "--label", "t", "--keep", "2")
    assert r.returncode == 0, r.stderr
    bk = Path(r.stdout.strip().splitlines()[-1])
    assert bk.is_file() and bk.stat().st_mode & 0o777 == 0o600 and bk.parent.stat().st_mode & 0o777 == 0o700
    assert not list(bk.parent.glob("*-wal")) and not list(bk.parent.glob("*-shm")), "پشتیبان باید یک فایل مستقل باشد"

    con = sqlite3.connect(db)
    con.execute("delete from assets"); con.commit(); con.close()
    assert _manage(tmp_path, "restore", str(bk)).returncode != 0  # بدون --yes انجام نمی‌شود
    assert sqlite3.connect(db).execute("select count(*) from assets").fetchone()[0] == 0
    r = _manage(tmp_path, "restore", str(bk), "--yes")
    assert r.returncode == 0, r.stderr
    assert sqlite3.connect(db).execute("select count(*) from assets").fetchone()[0] == n_assets > 0
    safety = list((tmp_path / "backups").glob("capitalpilot-before-restore-*.db"))
    assert len(safety) == 1, "پیش از بازیابی باید نسخهٔ ایمنی ساخته شود"
    assert sqlite3.connect(safety[0]).execute("select count(*) from assets").fetchone()[0] == 0


def test_manage_restore_rejects_corrupt_backup_and_keeps_data(tmp_path):
    _manage(tmp_path, "migrate")
    db = tmp_path / "data" / "cp.db"
    before = sqlite3.connect(db).execute("select count(*) from assets").fetchone()[0]
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite database" * 100)
    r = _manage(tmp_path, "restore", str(bad), "--yes")
    assert r.returncode != 0
    assert sqlite3.connect(db).execute("select count(*) from assets").fetchone()[0] == before
    assert _manage(tmp_path, "restore", str(tmp_path / "missing.db"), "--yes").returncode != 0


def test_manage_check_flags_backup_under_static(tmp_path):
    r = _manage(tmp_path, "check", extra={"APP_ENV": "production", "BACKUP_DIR": str(ROOT / "app" / "static" / "bk-test")})
    try:
        assert r.returncode == 1 and "static" in r.stdout
    finally:
        shutil.rmtree(ROOT / "app" / "static" / "bk-test", ignore_errors=True)


def test_manage_migrates_old_schema_with_automatic_backup(tmp_path):
    """دیتابیس با طرح‌واره قدیمی (نسخهٔ ثبت‌شده ۳) → migrate: پشتیبان خودکار، ارتقا به ۴ و حفظ داده‌ها."""
    assert _manage(tmp_path, "migrate").returncode == 0
    db = tmp_path / "data" / "cp.db"
    con = sqlite3.connect(db)
    assets = con.execute("select count(*) from assets").fetchone()[0]
    con.execute("delete from schema_migrations where version = 4")
    con.commit(); con.close()
    r = _manage(tmp_path, "migrate")
    assert r.returncode == 0, r.stderr
    info = json.loads(r.stdout.strip().splitlines()[-1])
    assert info["applied"] == [4] and info["backup"], info
    assert (tmp_path / "backups" / info["backup"]).is_file()
    assert sqlite3.connect(tmp_path / "backups" / info["backup"]).execute("select count(*) from assets").fetchone()[0] == assets
    assert sqlite3.connect(db).execute("select count(*) from assets").fetchone()[0] == assets
