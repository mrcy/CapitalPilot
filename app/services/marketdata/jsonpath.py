"""استخراج مقدار از JSON با زیرمجموعه‌ای از JSONPath (بدون وابستگی خارجی).

پشتیبانی‌شده: ``$.a.b[0].c``، ``a.b.0.c``، ``$['a']['b']``، اندیس منفی و فیلتر ساده
``$.items[?(@.symbol=='BTC_IRT')].price`` (اولین تطبیق).
"""
from __future__ import annotations

import re
from typing import Any

from .base import ProviderError

_TOKEN = re.compile(
    r"""\.?(?P<name>[A-Za-z_\u0600-\u06FF][\w\u0600-\u06FF\-]*)"""
    r"""|\[(?P<idx>-?\d+)\]"""
    r"""|\[(?P<q>['"])(?P<key>.*?)(?P=q)\]"""
    r"""|\[\?\(@\.(?P<fk>[\w\-]+)\s*==\s*(?:(?P<fq>['"])(?P<fv>.*?)(?P=fq)|(?P<fn>-?\d+(?:\.\d+)?))\)\]"""
    r"""|\.(?P<num>\d+)""",
    re.VERBOSE,
)


def _tokens(path: str):
    p = path.strip()
    if p.startswith("$"):
        p = p[1:]
    pos = 0
    out = []
    while pos < len(p):
        m = _TOKEN.match(p, pos)
        if not m:
            raise ProviderError(f"مسیر JSON نامعتبر است: «{path}» (نزدیک «{p[pos:pos + 12]}»)", "config")
        pos = m.end()
        if m.group("num") is not None:
            out.append(("idx", int(m.group("num"))))
        elif m.group("name") is not None:
            name = m.group("name")
            out.append(("idx", int(name)) if name.isdigit() else ("key", name))
        elif m.group("idx") is not None:
            out.append(("idx", int(m.group("idx"))))
        elif m.group("key") is not None:
            out.append(("key", m.group("key")))
        else:
            val = m.group("fv") if m.group("fv") is not None else m.group("fn")
            out.append(("filter", (m.group("fk"), val)))
    return out


def validate_path(path: str) -> None:
    _tokens(path)


def extract(data: Any, path: str) -> Any:
    cur = data
    for kind, arg in _tokens(path):
        if kind == "key":
            if not isinstance(cur, dict) or arg not in cur:
                raise ProviderError(f"کلید «{arg}» در پاسخ منبع پیدا نشد.", "parse")
            cur = cur[arg]
        elif kind == "idx":
            if isinstance(cur, dict) and str(arg) in cur:
                cur = cur[str(arg)]
            elif isinstance(cur, list):
                try:
                    cur = cur[arg]
                except IndexError:
                    raise ProviderError(f"اندیس {arg} در آرایهٔ پاسخ وجود ندارد.", "parse")
            else:
                raise ProviderError(f"اندیس {arg} در ساختار پاسخ وجود ندارد.", "parse")
        else:
            key, val = arg
            if not isinstance(cur, list):
                raise ProviderError("فیلتر روی مقداری که آرایه نیست اعمال شد.", "parse")
            hit = next((x for x in cur if isinstance(x, dict) and str(x.get(key)) == str(val)), None)
            if hit is None:
                raise ProviderError(f"آیتمی با {key}={val} در پاسخ منبع پیدا نشد.", "parse")
            cur = hit
    return cur
