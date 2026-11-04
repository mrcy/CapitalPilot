"""رمزنگاری کلیدهای API ذخیره‌شده در دیتابیس (Fernet). کلید هرگز به مرورگر ارسال نمی‌شود."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from ...config import get_settings

log = logging.getLogger("capitalpilot.crypto")


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    if s.secret_key:
        key = base64.urlsafe_b64encode(hashlib.sha256(s.secret_key.encode()).digest())
    else:
        path = s.data_dir / ".secret_key"
        if path.exists():
            key = path.read_bytes().strip()
        else:
            s.data_dir.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(key)
            log.info("generated new secret key file")
    return Fernet(key)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode() if plain else ""


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        log.warning("cannot decrypt stored API key (secret key changed?)")
        return ""
