import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="cp-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["DATA_DIR"] = str(_tmp)
os.environ["BACKUP_DIR"] = str(_tmp / "backups")
os.environ["LOG_DIR"] = str(_tmp / "logs")
os.environ["APP_TIMEZONE"] = "Asia/Tehran"
os.environ["PRICE_API_ALLOWED_HOSTS"] = ""
os.environ["SCHEDULER_ENABLED"] = "false"

import pytest  # noqa: E402


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.database import Base, engine
    from app.main import app, init_db

    Base.metadata.drop_all(engine)
    init_db()
    with TestClient(app) as c:
        yield c
