"""کلاینت HTTP امن برای منابع قیمت: timeout، سقف حجم پاسخ، بدون redirect، محافظت SSRF.

- آدرس‌های داخلی (loopback/private/link-local) مسدودند مگر ``PRICE_ALLOW_PRIVATE_HOSTS=true``.
- اگر ``PRICE_API_ALLOWED_HOSTS`` تنظیم شده باشد، منابع سفارشی فقط به همان میزبان‌ها وصل می‌شوند.
- کلید API هرگز روی http ساده ارسال نمی‌شود.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from ...config import get_settings

MAX_BYTES = 5_000_000
_transport: httpx.BaseTransport | None = None  # فقط برای تست (MockTransport)


def set_test_transport(t: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = t


def _perr(message: str, code: str, retriable: bool = False, http_status: int | None = None):
    from .base import ProviderError
    return ProviderError(message, code, retriable, http_status)


def check_url(url: str, *, allow_http: bool, has_credentials: bool, enforce_allowlist: bool) -> None:
    s = get_settings()
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise _perr("آدرس منبع قیمت نامعتبر است (باید با http:// یا https:// شروع شود).", "config")
    if u.scheme == "http" and (not allow_http or has_credentials):
        raise _perr("برای این منبع (به‌ویژه همراه با کلید API) فقط https مجاز است.", "config")
    host = u.hostname.lower()
    if enforce_allowlist and s.allowed_price_hosts and host not in s.allowed_price_hosts:
        raise _perr(f"میزبان «{host}» در PRICE_API_ALLOWED_HOSTS مجاز نشده است.", "config")
    if _transport is not None or s.price_allow_private_hosts:
        return
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise _perr(f"نام میزبان «{host}» قابل تشخیص نیست.", "network", retriable=True)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise _perr("اتصال به آدرس‌های داخلی/خصوصی مجاز نیست (PRICE_ALLOW_PRIVATE_HOSTS).", "config")


class HttpClient:
    def __init__(self, timeout: float = 8.0, *, allow_http: bool = False, enforce_allowlist: bool = False, max_bytes: int = MAX_BYTES):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.allow_http = allow_http
        self.enforce_allowlist = enforce_allowlist

    def get(self, url: str, params: dict | None = None, headers: dict | None = None, *, secret_params: tuple[str, ...] = (),
            has_credentials: bool = False, allow_not_modified: bool = False) -> httpx.Response:
        check_url(url, allow_http=self.allow_http, has_credentials=has_credentials, enforce_allowlist=self.enforce_allowlist)
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False, transport=_transport,
                              headers={"Accept": "application/json, text/plain, */*", "User-Agent": "CapitalPilot/2"}) as c:
                with c.stream("GET", url, params=params, headers=headers) as resp:
                    body = bytearray()
                    for chunk in resp.iter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_bytes:
                            raise _perr("پاسخ منبع بیش از حد بزرگ است.", "parse")
                    status = resp.status_code
                    out = httpx.Response(status, content=bytes(body), headers=resp.headers, request=resp.request)
        except httpx.TimeoutException:
            raise _perr("زمان انتظار پاسخ منبع تمام شد.", "timeout", retriable=True)
        except httpx.HTTPError as e:
            raise _perr(f"اتصال به منبع ناموفق بود ({type(e).__name__}).", "network", retriable=True)
        if status == 304 and allow_not_modified:
            return out
        if status in (401, 403):
            raise _perr(f"دسترسی رد شد (HTTP {status}): کلید API یا نوع احراز هویت را بررسی کنید.", "auth", http_status=status)
        if status == 429:
            raise _perr("منبع محدودیت تعداد درخواست اعمال کرد (HTTP 429).", "rate_limited", retriable=True, http_status=status)
        if 300 <= status < 400:
            raise _perr(f"منبع به آدرس دیگری هدایت کرد (HTTP {status}); آدرس را اصلاح کنید.", "http", http_status=status)
        if status >= 500:
            raise _perr(f"خطای سرور منبع (HTTP {status}).", "http", retriable=True, http_status=status)
        if status >= 400:
            raise _perr(f"درخواست رد شد (HTTP {status}).", "http", http_status=status)
        return out

    def get_json(self, url: str, **kw):
        resp = self.get(url, **kw)
        try:
            return resp.json()
        except ValueError:
            raise _perr("پاسخ منبع JSON معتبر نیست.", "parse")
