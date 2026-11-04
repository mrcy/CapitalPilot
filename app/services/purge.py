"""حذف دائمی چندمرحله‌ای: مرحلهٔ ۱ بررسی وابستگی‌ها و دریافت توکن؛ مرحلهٔ ۲ تأیید با عبارت تایپ‌شده."""
from __future__ import annotations

import secrets
import time

from ..errors import ValidationFailure

PURGE_PHRASE = "حذف دائمی"
_tokens: dict[str, tuple[float, str, int]] = {}


def request_purge(kind: str, ident: int, dependencies: dict) -> dict:
    now = time.time()
    for k in [k for k, (exp, _, _) in _tokens.items() if exp < now]:
        _tokens.pop(k, None)
    token = secrets.token_urlsafe(16)
    _tokens[token] = (now + 300, kind, ident)
    return {"token": token, "expires_in": 300, "phrase": PURGE_PHRASE, "dependencies": dependencies,
            "warning": "حذف دائمی قابل بازگشت نیست. پیش از ادامه از داده‌ها پشتیبان گرفته می‌شود."}


def check_purge(kind: str, ident: int, token: str, phrase: str) -> None:
    entry = _tokens.get(token)
    if not entry or entry[0] < time.time():
        raise ValidationFailure("مرحلهٔ اول حذف دائمی منقضی شده یا نامعتبر است؛ از ابتدا شروع کنید.")
    if entry[1] != kind or entry[2] != ident:
        raise ValidationFailure("توکن تأیید برای این مورد صادر نشده است.")
    if phrase.strip() != PURGE_PHRASE:
        raise ValidationFailure("عبارت تأیید صحیح نیست.")
    _tokens.pop(token, None)
