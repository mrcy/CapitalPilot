"""جست‌وجوی سراسری بازار (نسخهٔ ۲٫۴).

یک موتور جست‌وجوی محلی روی داده‌های واقعی دیتابیس:
  • نمادهای Iran Market Data (جدول market_symbols؛ آخرین فایل دریافت‌شده)
  • دارایی‌های ثبت‌شده در CapitalPilot (به‌همراه شناسهٔ آن‌ها در منابع قیمت)
  • پلتفرم‌ها و بازارهای تعریف‌شده در سیستم

قواعد مهم:
  • هیچ درخواست شبکه‌ای انجام نمی‌شود؛ بدون اینترنت هم روی آخرین داده‌های ذخیره‌شده کار می‌کند.
  • هیچ فهرست ساختگی در کار نیست؛ فقط «مترادف‌ها» (دلار = USD = dollar) برای گسترش عبارت جست‌وجو در کد هستند.
  • جست‌وجو هرگز تراکنش، موجودی یا قیمت نمی‌سازد/تغییر نمی‌دهد. قیمت نامعتبر به‌عنوان قیمت زنده برنمی‌گردد.
  • اتصال/ایجاد دارایی فقط با تأیید صریح کاربر (confirm=true) و بدون ثبت هیچ تراکنشی انجام می‌شود.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..errors import ConflictError, NotFoundError, ValidationFailure
from .clock import now_local
from .marketdata import iranmarket as im
from .marketdata.quality import price_state

# ---------------------------------------------------------------- گروه‌ها (فیلترهای سریع)
GROUPS: list[tuple[str, str]] = [
    ("mine", "دارایی‌های من"), ("currency", "ارز"), ("gold_coin", "طلا و سکه"), ("funds", "صندوق‌ها"),
    ("bourse", "بورس"), ("crypto", "رمزارز"), ("commodity_energy", "کالا و انرژی"), ("other", "سایر موارد"),
]
GROUP_LABEL = dict(GROUPS)
GROUP_KEYS = ["all"] + [k for k, _ in GROUPS]

CATEGORY_LABELS = {"currency": "ارز", "gold": "طلا", "coin": "سکه", "crypto": "رمزارز", "commodity": "کالا", "energy": "انرژی",
                   "precious_metal": "فلزات گرانبها", "index": "شاخص", "other": "سایر"}
MARKET_LABELS = {"iran_free": "بازار آزاد ایران", "iran_gold": "بازار طلا و سکهٔ ایران", "crypto_iran": "رمزارز (ریالی)",
                 "crypto": "رمزارز جهانی", "global": "جهانی", "other": "سایر"}
PLATFORM_KINDS = {"funds": "صندوق‌ها", "digital": "دیجیتال", "other": "سایر"}

# مترادف‌های زبانی برای گسترش عبارت جست‌وجو (نه داده‌ی بازار). هر ردیف یک «مفهوم» است.
SYNONYMS: list[tuple[str, ...]] = [
    ("دلار", "dollar", "usd", "us dollar", "دلار آمریکا"), ("یورو", "euro", "eur"), ("پوند", "pound", "gbp"),
    ("درهم", "dirham", "aed"), ("لیر", "lira", "try"), ("ین", "yen", "jpy"), ("یوان", "yuan", "cny"),
    ("طلا", "gold", "xau", "زر", "زر"), ("سکه", "coin", "sekke", "sekee", "sekeb"), ("نقره", "silver", "xag"),
    ("پلاتین", "platinum", "xpt"), ("پالادیوم", "palladium", "xpd"), ("مس", "copper"), ("روی", "zinc"),
    ("نفت", "oil", "crude", "crude oil", "نفت خام"), ("برنت", "brent"), ("گاز", "gas"),
    ("بیتکوین", "bitcoin", "btc", "بیت کوین"), ("اتریوم", "ethereum", "eth", "ether"), ("تتر", "tether", "usdt"),
    ("ریپل", "ripple", "xrp"), ("سولانا", "solana", "sol"), ("دوج کوین", "dogecoin", "doge"), ("لایت کوین", "litecoin", "ltc"),
    ("صندوق", "fund", "etf"), ("سهام", "stock", "share", "equity"), ("شاخص", "index", "indices"),
    ("ریال", "rial", "irr"), ("تومان", "toman", "irt"), ("اونس", "ounce", "oz", "troy"), ("مثقال", "mesghal", "mithqal"),
    ("گرم", "gram"), ("امامی", "emami"), ("بهار آزادی", "azadi", "bahar"), ("بورس", "bourse", "tse", "tsetmc"),
    ("رمزارز", "crypto", "cryptocurrency", "رمز ارز"), ("ارز", "currency", "forex", "fx"),
    ("کالا", "commodity"), ("انرژی", "energy"),
]

# نمادهایی که در پیشنهادهای «محبوب» (فقط اگر در داده‌ها موجود باشند) نشان داده می‌شوند و در رتبه‌بندی امتیاز اندکی دارند.
POPULAR_SYMBOLS = ["USD_IRR_FREE", "EUR_IRR_FREE", "GOLD_18K_IRR", "COIN_EMAMI_IRR", "USDT_IRR", "BTC_USD", "XAU_USD", "BRENT_USD"]
POPULAR_TERMS = ["دلار", "طلا", "سکه", "bitcoin", "تتر", "یورو", "نفت", "صندوق"]

# ---------------------------------------------------------------- نرمال‌سازی
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_LETTERS = str.maketrans({
    "ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "ؤ": "و", "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ڪ": "ک", "ې": "ی",
})
_STRIP = re.compile(r"[\u064b-\u065f\u0670\u0640\u06d6-\u06ed]")  # اعراب، کشیده
_SEP = re.compile(r"[\W_]+", re.UNICODE)


@lru_cache(maxsize=200_000)
def fold(text: str) -> str:
    """یکسان‌سازی برای جست‌وجو: ی/ي، ک/ك، آ/ا، اعداد فارسی/عربی/انگلیسی، نیم‌فاصله، علائم و فاصله‌های اضافه، حروف کوچک."""
    t = unicodedata.normalize("NFKC", text or "").translate(_DIGITS).translate(_LETTERS)
    t = _STRIP.sub("", t).lower()
    return _SEP.sub(" ", t).strip()


def compact(text: str) -> str:
    return fold(text).replace(" ", "")


def _is_persian(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06ff]", text))


@lru_cache(maxsize=4096)
def _synonym_map() -> dict[str, tuple[str, ...]]:
    out: dict[str, set[str]] = {}
    for grp in SYNONYMS:
        terms = {fold(t) for t in grp if fold(t)}
        for t in terms:
            out.setdefault(t, set()).update(terms - {t})
    return {k: tuple(sorted(v)) for k, v in out.items()}


def alternatives(token: str, phrase: str = "") -> tuple[str, ...]:
    mp = _synonym_map()
    alts = set(mp.get(token, ()))
    if phrase and phrase in mp:
        alts.update(mp[phrase])
    return tuple(sorted(alts))


def edit_distance(a: str, b: str, limit: int) -> int:
    """فاصلهٔ Damerau-Levenshtein (حالت OSA) با برش زودهنگام؛ اگر از limit بیشتر شود limit+1 برمی‌گردد."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] | None = None
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
            best = min(best, v)
        if best > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


def _fuzzy_limit(token: str) -> int:
    """سقف فاصلهٔ ویرایشی: کلمهٔ فارسی ۳ حرفی ۱؛ لاتین ≥۴ حرف ۱؛ ≥۸ حرف ۲."""
    persian = bool(re.search(r"[\u0600-\u06ff]", token))
    if len(token) < (3 if persian else 4):
        return 0
    return 1 if len(token) < 8 else 2


# ---------------------------------------------------------------- نمایهٔ حافظه‌ای
@dataclass
class Entry:
    kind: str                # symbol | asset | platform | market
    key: str                 # شناسهٔ یکتا در نتیجه (sym:… / asset:… / platform:… / market:…)
    group: str
    symbol: str = ""
    name_fa: str = ""
    name_en: str = ""
    category: str = ""
    market: str = ""
    f_symbol: str = ""       # symbol فولدشده؛ توکن‌ها با فاصله
    c_symbol: str = ""
    f_fa: str = ""
    f_en: str = ""
    c_fa: str = ""
    c_en: str = ""
    f_codes: list[str] = field(default_factory=list)
    f_extra: str = ""        # نام دسته/بازار/نوع/پلتفرم
    words: set[str] = field(default_factory=set)
    mine: bool = False
    popular: bool = False
    status_rank: int = 0
    payload: dict = field(default_factory=dict)  # اطلاعات کمکی برای ساخت خروجی


def _make(kind: str, key: str, group: str, *, symbol: str = "", name_fa: str = "", name_en: str = "", category: str = "", market: str = "",
          codes: list[str] | None = None, extra: str = "") -> Entry:
    e = Entry(kind=kind, key=key, group=group, symbol=symbol, name_fa=name_fa, name_en=name_en, category=category, market=market)
    e.f_symbol, e.c_symbol = fold(symbol), compact(symbol)
    e.f_fa, e.f_en = fold(name_fa), fold(name_en)
    e.c_fa, e.c_en = compact(name_fa), compact(name_en)
    e.f_codes = [c for c in (fold(x) for x in (codes or [])) if c]
    e.f_extra = fold(extra)
    ws: set[str] = set()
    for t in (e.f_symbol, e.f_fa, e.f_en, *e.f_codes):
        ws.update(t.split())
    e.words = ws
    return e


def classify_group(category: str, market: str, symbol: str, name_fa: str, name_en: str, crypto_bases: set[str], currency_bases: set[str]) -> str:
    """گروه نمایشی (فیلتر سریع) یک نماد؛ بر پایهٔ دستهٔ خود فایل و نام‌ها، نه فهرست ثابت نمادها."""
    sym = symbol.upper()
    text = f"{name_fa} {name_en}".lower()
    if "صندوق" in name_fa or re.search(r"\b(etf|fund)\b", text) or re.search(r"(^|_)FUND(_|$)", sym):
        return "funds"
    if sym.startswith(("RATIO_", "DIFF_")):
        return "other"
    if category == "currency":
        return "currency"
    if category in ("gold", "coin"):
        return "gold_coin"
    if category == "crypto":
        return "crypto"
    if category in ("commodity", "energy"):
        return "commodity_energy"
    if category == "precious_metal":
        return "gold_coin" if (market == "iran_gold" or "XAU" in sym or "طلا" in name_fa or "gold" in text) else "commodity_energy"
    if category == "index":
        return "bourse"
    toks = [t for t in re.split(r"[^A-Z0-9]+", sym) if t]
    if toks and toks[0] in crypto_bases:
        return "crypto"
    if any(t in currency_bases for t in toks) and not sym.startswith(("IME_", "ICE_")):
        return "currency"
    if sym.startswith("IME_"):
        return "commodity_energy"
    return "other"


def _asset_group(a: m.Asset, name: str) -> str:
    t = a.asset_type
    if t in ("fund",):
        return "funds"
    if t in ("stock", "index"):
        return "bourse"
    if t == "digital":
        return "crypto"
    if t in ("gold",):
        return "gold_coin"
    if t in ("currency",):
        return "currency"
    if t in ("silver", "copper", "commodity"):
        return "commodity_energy"
    return "other"


def build_entries(db: Session) -> list[Entry]:
    """نمایهٔ همهٔ منابع قابل جست‌وجو را از دیتابیس می‌سازد (فقط ستون‌های لازم؛ ردیف کامل فقط برای نتایج نمایش‌داده‌شده خوانده می‌شود)."""
    S = m.MarketSymbol
    rows = db.execute(select(S.symbol, S.name_fa, S.name_en, S.category, S.market)).all()
    crypto_bases = {re.split(r"[^A-Z0-9]+", r.symbol.upper())[0] for r in rows if r.category == "crypto"}
    currency_bases = {re.split(r"[^A-Z0-9]+", r.symbol.upper())[0] for r in rows if r.category == "currency"}
    crypto_bases.discard("")
    currency_bases.discard("")
    popular = set(POPULAR_SYMBOLS)
    linked = linked_symbols(db)
    out: list[Entry] = []
    for r in rows:
        grp = classify_group(r.category, r.market, r.symbol, r.name_fa, r.name_en, crypto_bases, currency_bases)
        fa = "" if r.name_fa == r.symbol else r.name_fa  # نامی که همان نماد است نام واقعی نیست
        en = "" if r.name_en == r.symbol else r.name_en
        e = _make("symbol", f"sym:{r.symbol}", grp, symbol=r.symbol, name_fa=fa, name_en=en, category=r.category, market=r.market,
                  extra=f"{CATEGORY_LABELS.get(r.category, r.category)} {MARKET_LABELS.get(r.market, r.market)} {r.category} {r.market}")
        e.popular = r.symbol in popular
        e.mine = r.symbol in linked
        out.append(e)
    # دارایی‌های ثبت‌شده
    types = {t.key: t.label for t in db.scalars(select(m.AssetType))}
    ext: dict[int, list[str]] = {}
    for aid, ext_id, pname in db.execute(select(m.AssetPriceSource.asset_id, m.AssetPriceSource.external_id, m.PriceProvider.name)
                                          .join(m.PriceProvider, m.PriceProvider.id == m.AssetPriceSource.provider_id)):
        ext.setdefault(aid, []).append(ext_id or "")
    plats = {p.id: p for p in db.scalars(select(m.Platform))}
    for a in db.scalars(select(m.Asset).where(m.Asset.is_archived.is_(False)).order_by(m.Asset.sort_order, m.Asset.id)):
        pl = plats.get(a.platform_id)
        codes = [a.symbol, *ext.get(a.id, [])]
        e = _make("asset", f"asset:{a.id}", _asset_group(a, a.name), symbol=a.symbol, name_fa=a.name, name_en=a.name_en, category=a.asset_type, market=a.market,
                  codes=codes, extra=f"{types.get(a.asset_type, a.asset_type)} {a.market} {pl.name if pl else ''} دارایی من")
        e.mine = True
        e.payload = {"asset_id": a.id}
        out.append(e)
    # پلتفرم‌ها
    counts = dict(db.execute(select(m.Asset.platform_id, func.count()).where(m.Asset.is_archived.is_(False)).group_by(m.Asset.platform_id)).all())
    for p in plats.values():
        if p.is_archived:
            continue
        e = _make("platform", f"platform:{p.id}", "other", name_fa=p.name, category=p.kind, extra=f"پلتفرم {PLATFORM_KINDS.get(p.kind, p.kind)} {p.kind} {p.note}")
        e.payload = {"platform_id": p.id, "asset_count": counts.get(p.id, 0)}
        out.append(e)
    # بازارها (از خود نمادها و دارایی‌ها)
    mk: dict[str, int] = {}
    for key, n in db.execute(select(S.market, func.count()).group_by(S.market)).all():
        if key:
            mk[key] = mk.get(key, 0) + n
    for key, n in db.execute(select(m.Asset.market, func.count()).where(m.Asset.is_archived.is_(False)).group_by(m.Asset.market)).all():
        if key:
            mk[key] = mk.get(key, 0) + n
    for key, n in mk.items():
        label = MARKET_LABELS.get(key, key)
        e = _make("market", f"market:{key}", "other", name_fa=label, name_en=key, market=key, extra=f"بازار {label}")
        e.payload = {"market": key, "count": n}
        out.append(e)
    return out


def linked_symbols(db: Session) -> dict[str, list[dict]]:
    """نماد Iran Market → دارایی‌های (غیربایگانی‌ شده و بایگانی‌شده) متصل به آن."""
    rows = db.execute(select(m.AssetPriceSource.external_id, m.Asset.id, m.Asset.name, m.Asset.is_archived, m.AssetPriceSource.priority)
                      .join(m.PriceProvider, m.PriceProvider.id == m.AssetPriceSource.provider_id)
                      .join(m.Asset, m.Asset.id == m.AssetPriceSource.asset_id)
                      .where(m.PriceProvider.kind == im.KIND).order_by(m.Asset.id)).all()
    out: dict[str, list[dict]] = {}
    for sym, aid, name, arch, prio in rows:
        out.setdefault(sym, []).append({"asset_id": aid, "name": name, "is_archived": bool(arch), "priority": prio})
    return out


# ---------------------------------------------------------------- امتیازدهی
TIER_SYMBOL_EXACT, TIER_CODE_EXACT, TIER_NAME_EXACT = 100, 98, 90
TIER_SYMBOL_TOKEN, TIER_SYMBOL_PREFIX, TIER_NAME_START, TIER_NAME_WORD = 82, 78, 72, 70
TIER_NAME_CONTAINS, TIER_EN_WORD, TIER_SYMBOL_CONTAINS, TIER_EN_CONTAINS = 60, 56, 55, 50
TIER_SYNONYM, TIER_EXTRA, TIER_FUZZY = 40, 30, 22


@dataclass
class Query:
    raw: str
    folded: str
    compact: str
    tokens: list[str]
    alts: list[tuple[str, ...]]


def parse_query(q: str) -> Query:
    f = fold(q)
    toks = f.split()
    return Query(q, f, f.replace(" ", ""), toks, [alternatives(t, f if len(toks) == 1 else "") for t in toks])


def _has_prefix(text: str, token: str) -> bool:
    """token (یک یا چند کلمه) ابتدای یک کلمه در text باشد."""
    return (" " + text).find(" " + token) >= 0


def _tok_in(entry: Entry, token: str, strict: bool = False) -> int:
    """بهترین تطبیق یک توکن: 3 = شروع کلمهٔ نام فارسی، 2 = بخشی از نام فارسی، 1 = انگلیسی/نماد/کد، 0 = هیچ.

    strict (برای مترادف‌ها): فقط ابتدای کلمه در نام‌ها و «نخستین جزء نماد» (دارایی پایه)؛ تا USD در BTC_USD دلیل تطبیق «دلار» نشود.
    """
    if _has_prefix(entry.f_fa, token):
        return 3
    if strict:
        first = entry.f_symbol.split(" ", 1)[0] if entry.f_symbol else ""
        if _has_prefix(entry.f_en, token) or first.startswith(token) or any(_has_prefix(c, token) for c in entry.f_codes):
            return 1
        return 0
    persian = _is_persian(token)
    if token in entry.f_fa or (persian and token in entry.c_fa):
        return 2
    if _has_prefix(entry.f_en, token) or _has_prefix(entry.f_symbol, token) or any(_has_prefix(c, token) for c in entry.f_codes):
        return 1
    if len(token) >= 3 and (token in entry.f_en or token in entry.f_symbol or any(token in c for c in entry.f_codes)):
        return 1
    return 0


def _extra_has(entry: Entry, token: str) -> bool:
    return token in entry.f_extra


def score(entry: Entry, q: Query) -> tuple[int, str] | None:
    """(tier, how) یا None اگر ورودی با عبارت تطبیق ندارد. فقط دقیق/بخشی/مترادف؛ تقریبی جداگانه در fuzzy_score."""
    qc, qf = q.compact, q.folded
    if not qc:
        return None
    if entry.c_symbol and entry.c_symbol == qc:
        return TIER_SYMBOL_EXACT, "symbol_exact"
    if any(c.replace(" ", "") == qc for c in entry.f_codes):
        return TIER_CODE_EXACT, "code_exact"
    if (entry.c_fa and entry.c_fa == qc) or (entry.c_en and entry.c_en == qc):
        return TIER_NAME_EXACT, "name_exact"
    stoks = entry.f_symbol.split()
    toks = q.tokens
    if toks and all(t in stoks for t in toks):
        return TIER_SYMBOL_TOKEN, "symbol_token"
    if entry.f_symbol.startswith(qf):
        return TIER_SYMBOL_PREFIX, "symbol_prefix"
    # نام فارسی: همهٔ توکن‌ها
    fa_hits = [(_tok_in(entry, t) if (t in entry.f_fa or t in entry.c_fa) else 0) for t in toks]
    if toks and all(fa_hits):
        if entry.f_fa.startswith(qf) or (_is_persian(qf) and entry.c_fa.startswith(qc)):
            return TIER_NAME_START, "name_start"
        if all(h == 3 for h in fa_hits):
            return TIER_NAME_WORD, "name_word"
        return TIER_NAME_CONTAINS, "name_contains"
    compact_ok = _is_persian(qf) or " " in qf  # «بیت کوین» ≈ «بیت‌کوین»؛ برای لاتین تک‌کلمه‌ای مرز کلمه‌ها نادیده گرفته نمی‌شود
    if compact_ok and qc in entry.c_fa:
        return TIER_NAME_CONTAINS, "name_contains"
    # نام انگلیسی
    if toks and all((t in entry.f_en) for t in toks):
        if all(any(w.startswith(t) for w in entry.f_en.split()) for t in toks):
            return TIER_EN_WORD, "en_word"
        return TIER_EN_CONTAINS, "en_contains"
    if compact_ok and qc in entry.c_en:
        return TIER_EN_CONTAINS, "en_contains"
    if len(qc) >= 2 and qf in entry.f_symbol:
        return TIER_SYMBOL_CONTAINS, "symbol_contains"
    if len(qc) >= 3 and any(qf in c for c in entry.f_codes):
        return TIER_SYMBOL_CONTAINS, "code_contains"
    # مترادف‌ها: هر توکن یا خودش یا یکی از مترادف‌هایش باید تطبیق داشته باشد
    if toks:
        used_syn, ok = False, True
        for t, alts in zip(toks, q.alts):
            if _tok_in(entry, t):
                continue
            if any(_tok_in(entry, a, True) for a in alts):
                used_syn = True
                continue
            ok = False
            break
        if ok and used_syn:
            return TIER_SYNONYM, "synonym"
        # نام دسته/بازار/پلتفرم/نوع (مستقیم یا با مترادف)
        if all(_extra_has(entry, t) or _tok_in(entry, t) or any(_extra_has(entry, x) or _tok_in(entry, x, True) for x in alts) for t, alts in zip(toks, q.alts)):
            if any(_extra_has(entry, t) for t in toks) or any(_extra_has(entry, x) for alts in q.alts for x in alts):
                return TIER_EXTRA, "category"
    return None


def fuzzy_score(entry: Entry, q: Query) -> tuple[int, str] | None:
    """تطبیق تقریبی برای غلط‌های تایپی (حذف/افزودن/تعویض/جابجایی یک یا دو حرف) برای توکن‌های حداقل ۴ حرفی."""
    if not q.tokens:
        return None
    cands = list(entry.words | {entry.c_fa, entry.c_en, entry.c_symbol})
    fuzzy_used = False
    for t in q.tokens:
        if _tok_in(entry, t) or any(_tok_in(entry, a, True) for a in alternatives(t)):
            continue
        lim = _fuzzy_limit(t)
        if lim == 0:
            return None
        hit = False
        for c in cands:
            if c and (len(t) >= 6 or c[0] == t[0]) and (edit_distance(t, c, lim) <= lim or (len(c) > len(t) and edit_distance(t, c[: len(t)], lim) <= lim)):
                hit = True
                break
        if not hit:
            return None
        fuzzy_used = True
    return (TIER_FUZZY, "fuzzy") if fuzzy_used else None


# ---------------------------------------------------------------- ساخت خروجی
_STATUS_TEXT = {"valid": "معتبر", "stale": "قدیمی", "invalid": "نامعتبر", "missing": "ناموجود"}
_STATUS_RANK = {"valid": 3, "stale": 2, "invalid": 1, "missing": 0}


def unify_symbol_status(s: str) -> tuple[str, bool]:
    """وضعیت نماد Iran Market → (valid|stale|invalid|missing, با هشدار؟)."""
    if s == "warning":
        return "valid", True
    if s == "no_price":
        return "missing", False
    return s, False


def unify_asset_status(s: str) -> tuple[str, bool]:
    if s == "manual":
        return "valid", False
    if s in ("valid", "stale"):
        return s, False
    if s == "missing":
        return "missing", False
    return "invalid", False  # invalid | pending | conflict


def _dec(v) -> str | None:
    return None if v is None else format(v if isinstance(v, Decimal) else Decimal(str(v)), "f")


def _age_text(minutes: int | None) -> str:
    if minutes is None:
        return ""
    if minutes < 1:
        return "هم‌اکنون"
    if minutes < 60:
        return f"{minutes} دقیقه پیش"
    if minutes < 1440:
        return f"{minutes // 60} ساعت پیش"
    return f"{minutes // 1440} روز پیش"


class _Ctx:
    """زمینهٔ مشترک یک درخواست: زمان، سن مجاز قیمت، وضعیت تازگی فایل و اتصال‌ها."""

    def __init__(self, db: Session, now: datetime):
        self.db, self.now = db, now
        self.max_age = im.max_age_days(db)
        self.pv = im.get_provider(db)
        self.snap = im.snapshot_state(db, self.pv, now)
        self.linked = linked_symbols(db)
        self.portfolios = _asset_portfolios(db)


def _asset_portfolios(db: Session) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for aid, pid, pname, active in db.execute(select(m.PortfolioAsset.asset_id, m.Portfolio.id, m.Portfolio.name, m.PortfolioAsset.is_active)
                                              .join(m.Portfolio, m.Portfolio.id == m.PortfolioAsset.portfolio_id)
                                              .where(m.Portfolio.is_archived.is_(False)).order_by(m.Portfolio.sort_order, m.Portfolio.id)):
        out.setdefault(aid, []).append({"id": pid, "name": pname})
    return out


def _symbol_item(r: m.MarketSymbol, e: Entry, ctx: _Ctx) -> dict:
    d = im.symbol_dict(r, ctx.now, ctx.max_age, ctx.snap["stale"], ctx.snap["reason"], {})
    status, warn = unify_symbol_status(d["status"])
    live = status == "valid"
    shown = status in ("valid", "stale")  # قیمت نامعتبر/ناموجود هرگز نمایش داده نمی‌شود
    links = [x for x in ctx.linked.get(r.symbol, []) if not x["is_archived"]]
    return {
        "id": e.key, "kind": "symbol", "group": e.group, "group_label": GROUP_LABEL.get(e.group, ""),
        "symbol": r.symbol, "name_fa": r.name_fa, "name_en": r.name_en,
        "category": r.category, "category_label": CATEGORY_LABELS.get(r.category, r.category),
        "market": r.market, "market_label": MARKET_LABELS.get(r.market, r.market),
        "price": _dec(r.price) if shown else None, "currency": r.currency, "unit": r.unit, "unit_size": _dec(r.unit_size),
        "change_pct": _dec(r.change_pct) if shown else None, "source": r.upstream_source, "provider": "Iran Market Data",
        "price_time": r.price_time, "age_minutes": d["age_minutes"], "age_text": _age_text(d["age_minutes"]),
        "status": status, "status_text": _STATUS_TEXT[status], "status_reason": d["status_reason"], "warning": warn, "live": live,
        "linked_assets": links, "link_blockers": im.link_blockers(r),
        "asset_id": None,
    }


def _asset_item(a: m.Asset, e: Entry, ctx: _Ctx, prices: dict[int, list[m.Price]], platforms: dict[int, m.Platform], types: dict[str, str]) -> dict:
    ps = price_state(prices.get(a.id, []), ctx.now, ctx.max_age)
    status, warn = unify_asset_status(ps["status"])
    rec = ps.get("record") if status in ("valid", "stale") else None
    age = int((ctx.now - rec.recorded_at).total_seconds() // 60) if rec is not None else None
    src = None
    if rec is not None:
        src = rec.source or ("دستی" if rec.origin == "manual" else "")
    pl = platforms.get(a.platform_id)
    return {
        "id": e.key, "kind": "asset", "group": e.group, "group_label": GROUP_LABEL.get(e.group, ""),
        "asset_id": a.id, "symbol": a.symbol, "name_fa": a.name, "name_en": a.name_en,
        "category": a.asset_type, "category_label": types.get(a.asset_type, a.asset_type),
        "market": a.market, "market_label": MARKET_LABELS.get(a.market, a.market),
        "platform": pl.name if pl else "", "platform_id": a.platform_id,
        "price": _dec(rec.price) if rec is not None else None, "currency": rec.currency if rec is not None else a.price_currency, "unit": a.unit,
        "change_pct": None, "source": src, "provider": None,
        "price_time": rec.recorded_at if rec is not None else None, "age_minutes": age, "age_text": _age_text(age),
        "status": status, "status_text": _STATUS_TEXT[status], "status_reason": ps.get("reason", ""), "warning": warn, "live": status == "valid",
        "origin": rec.origin if rec is not None else None, "portfolios": ctx.portfolios.get(a.id, []),
        "linked_assets": [], "link_blockers": [],
    }


def _simple_item(e: Entry, kind_label: str) -> dict:
    return {"id": e.key, "kind": e.kind, "group": e.group, "group_label": GROUP_LABEL.get(e.group, ""), "symbol": "",
            "name_fa": e.name_fa, "name_en": e.name_en if e.kind == "market" else "", "category": e.category, "category_label": kind_label,
            "market": e.market, "market_label": MARKET_LABELS.get(e.market, e.market) if e.market else "", "price": None, "currency": "", "unit": "",
            "change_pct": None, "source": None, "provider": None, "price_time": None, "age_minutes": None, "age_text": "",
            "status": None, "status_text": "", "status_reason": "", "warning": False, "live": False, "linked_assets": [], "link_blockers": [],
            "asset_id": None, **{k: v for k, v in e.payload.items()}}


def hydrate(db: Session, entries: list[Entry], ctx: _Ctx) -> list[dict]:
    """ردیف‌های کامل فقط برای ورودی‌هایی که واقعاً نمایش داده می‌شوند خوانده می‌شوند."""
    sym_keys = [e.symbol for e in entries if e.kind == "symbol"]
    syms = {r.symbol: r for r in db.scalars(select(m.MarketSymbol).where(m.MarketSymbol.symbol.in_(sym_keys)))} if sym_keys else {}
    aids = [e.payload["asset_id"] for e in entries if e.kind == "asset"]
    assets = {a.id: a for a in db.scalars(select(m.Asset).where(m.Asset.id.in_(aids)))} if aids else {}
    prices: dict[int, list[m.Price]] = {}
    if aids:
        for p in db.scalars(select(m.Price).where(m.Price.asset_id.in_(aids)).order_by(m.Price.recorded_at.desc(), m.Price.id.desc())):
            prices.setdefault(p.asset_id, []).append(p)
    platforms = {p.id: p for p in db.scalars(select(m.Platform))}
    types = {t.key: t.label for t in db.scalars(select(m.AssetType))}
    out = []
    for e in entries:
        if e.kind == "symbol" and e.symbol in syms:
            out.append(_symbol_item(syms[e.symbol], e, ctx))
        elif e.kind == "asset" and e.payload["asset_id"] in assets:
            out.append(_asset_item(assets[e.payload["asset_id"]], e, ctx, prices, platforms, types))
        elif e.kind == "platform":
            out.append(_simple_item(e, "پلتفرم"))
        elif e.kind == "market":
            out.append(_simple_item(e, "بازار"))
    return out


# ---------------------------------------------------------------- جست‌وجو
def data_state(ctx: _Ctx, total_symbols: int) -> dict:
    s = ctx.snap
    return {"provider_enabled": bool(ctx.pv and ctx.pv.is_enabled), "has_data": bool(s.get("has_data")) and total_symbols > 0, "stale": bool(s.get("stale")),
            "reason": s.get("reason") or "", "fetch_age_minutes": s.get("fetch_age_minutes"), "last_ok_at": s.get("last_ok_at"),
            "generated_at": s.get("generated_at"), "symbols": total_symbols, "offline_capable": True}


def search(db: Session, q: str, *, group: str = "all", page: int = 1, page_size: int = 20, per_group: int = 5, now: datetime | None = None) -> dict:
    """جست‌وجوی سراسری. group=all: چند نتیجهٔ برتر هر گروه؛ group=<کلید>: نتایج همان گروه با صفحه‌بندی."""
    if group not in GROUP_KEYS:
        raise ValidationFailure("گروه فیلتر نامعتبر است.")
    now = now or now_local()
    ctx = _Ctx(db, now)
    query = parse_query(q)
    entries = build_entries(db)
    n_symbols = sum(1 for e in entries if e.kind == "symbol")
    base = {"q": q, "normalized": query.folded, "group": group, "page": page, "page_size": page_size, "data_state": data_state(ctx, n_symbols),
            "groups": [], "items": [], "total": 0, "counts": {k: 0 for k in GROUP_KEYS}, "fuzzy": False}
    if not query.folded:
        return base
    scored: list[tuple[Entry, int, str]] = []
    for e in entries:
        r = score(e, query)
        if r is not None:
            scored.append((e, r[0], r[1]))
    fuzzy = False
    if not scored:  # تقریبی فقط وقتی هیچ تطبیق دقیق/بخشی/مترادفی نیست (جلوگیری از نتایج نامرتبط)
        have = {e.key for e, _, _ in scored}
        for e in entries:
            if e.key in have:
                continue
            r = fuzzy_score(e, query)
            if r is not None:
                scored.append((e, r[0], r[1]))
                fuzzy = True
    # رتبه: tier، سپس امتیازهای جزئی (دارایی من، محبوب، وضعیت معتبر، کوتاه‌تر بودن نام)
    def key(t: tuple[Entry, int, str]):
        e, tier, how = t
        name_len = max(len(e.c_fa or e.c_en or e.c_symbol), 1)
        ratio = min(len(query.compact) / name_len, 1.0)
        bonus = (4 if e.mine else 0) + (2 if e.popular else 0) + int(ratio * 3)
        return (-(tier * 10 + min(bonus, 9)), -int(e.c_symbol.startswith(query.compact)), len(e.c_fa or e.c_symbol), e.name_fa or e.symbol, e.key)
    scored.sort(key=key)
    # شمارش گروه‌ها: «دارایی‌های من» = دارایی‌های ثبت‌شده؛ سایر گروه‌ها = همهٔ نتایج آن گروه (دارایی‌ها و نمادها)
    counts = {k: 0 for k in GROUP_KEYS}
    for e, _, _ in scored:
        counts["all"] += 1
        counts[e.group] += 1
        if e.kind == "asset":
            counts["mine"] += 1
    # گروه «دارایی‌های من» جدا از گروه موضوعی است: دارایی‌ها در هر دو شمرده می‌شوند ولی در حالت all فقط یک‌بار (در گروه موضوعی) نمایش می‌یابند.
    def members(g: str) -> list[tuple[Entry, int, str]]:
        if g == "mine":
            return [t for t in scored if t[0].kind == "asset"]
        return [t for t in scored if t[0].group == g]
    base["counts"] = counts
    base["fuzzy"] = fuzzy and all(how == "fuzzy" for _, _, how in scored)
    if group == "all":
        # «دارایی‌های من» دارایی‌ها را یک‌بار نشان می‌دهد؛ بخش‌های موضوعی فقط نمادها/پلتفرم‌ها/بازارها را (جمع هر بخش شامل دارایی‌ها هم هست).
        picks: list[tuple[str, list[tuple[Entry, int, str]]]] = []
        for k, _ in GROUPS:
            mem = members(k)
            top = (mem if k == "mine" else [t for t in mem if t[0].kind != "asset"])[:per_group]
            if top:
                picks.append((k, top))
        by = {it["id"]: it for it in hydrate(db, [t[0] for _, top in picks for t in top], ctx)}
        base["groups"] = [{"key": k, "label": GROUP_LABEL[k], "total": counts[k],
                           "items": [{**by[e.key], "match": how, "tier": tier} for e, tier, how in top if e.key in by]} for k, top in picks]
        base["total"] = counts["all"]
        return base
    mem = members(group)
    base["total"] = len(mem)
    chunk = mem[(page - 1) * page_size: page * page_size]
    items = hydrate(db, [t[0] for t in chunk], ctx)
    by = {it["id"]: it for it in items}
    base["items"] = [{**by[e.key], "match": how, "tier": tier} for e, tier, how in chunk if e.key in by]
    return base


def suggestions(db: Session, now: datetime | None = None) -> dict:
    """پیشنهادهای محبوب از دادهٔ واقعی: نمادهای متصل به دارایی‌های کاربر + نمادهای پرکاربرد که در داده‌ها واقعاً وجود دارند."""
    now = now or now_local()
    ctx = _Ctx(db, now)
    linked = list(ctx.linked)
    want = []
    for s in linked + POPULAR_SYMBOLS:
        if s not in want:
            want.append(s)
    syms = {r.symbol: r for r in db.scalars(select(m.MarketSymbol).where(m.MarketSymbol.symbol.in_(want)))} if want else {}
    entries = []
    for s in want:
        r = syms.get(s)
        if r is None:
            continue
        entries.append(Entry(kind="symbol", key=f"sym:{s}", group="other", symbol=s))
    items = []
    for e in entries[:10]:
        r = syms[e.symbol]
        it = _symbol_item(r, e, ctx)
        it["mine"] = e.symbol in ctx.linked
        items.append(it)
    # عبارت‌های محبوب فقط اگر واقعاً نتیجه داشته باشند
    all_entries = build_entries(db)
    terms = []
    for t in POPULAR_TERMS:
        qq = parse_query(t)
        if any(score(e, qq) for e in all_entries):
            terms.append(t)
    return {"popular_symbols": items, "popular_terms": terms, "data_state": data_state(ctx, db.scalar(select(func.count()).select_from(m.MarketSymbol)) or 0)}


# ---------------------------------------------------------------- عملیات (فقط با تأیید صریح کاربر)
_UNIT_FA = {"unit": "واحد", "gram": "گرم", "coin": "عدد", "troy_ounce": "اونس", "barrel": "بشکه", "mesghal": "مثقال", "ton": "تن", "kg": "کیلوگرم", "contract": "قرارداد"}
_TYPE_BY_GROUP = {"currency": "currency", "gold_coin": "gold", "funds": "fund", "bourse": "index", "crypto": "digital", "commodity_energy": "commodity", "other": "other"}


def _need_confirm(confirm: bool) -> None:
    if not confirm:
        raise ValidationFailure("این عملیات باید صریحاً تأیید شود؛ هیچ تغییری بدون تأیید شما انجام نمی‌شود.", code="not_confirmed")


def _symbol(db: Session, symbol: str) -> m.MarketSymbol:
    r = db.get(m.MarketSymbol, symbol.strip())
    if r is None:
        raise ValidationFailure(f"نماد «{symbol}» در داده‌های ذخیره‌شدهٔ Iran Market Data پیدا نشد.", code="symbol_not_found")
    return r


def _check_not_linked(db: Session, symbol: str, asset: m.Asset | None = None) -> None:
    """جلوگیری از اتصال تکراری: هر نماد فقط به یک دارایی (غیربایگانی) و هر دارایی فقط به یک نماد Iran Market متصل می‌شود."""
    existing = [x for x in linked_symbols(db).get(symbol, []) if not x["is_archived"]]
    if existing:
        x = existing[0]
        raise ConflictError(f"این نماد از قبل به دارایی «{x['name']}» متصل است و اتصال تکراری ممکن نیست.", code="symbol_already_linked",
                            details={"asset_id": x["asset_id"], "asset": x["name"], "symbol": symbol})
    if asset is not None:
        pv = im.get_provider(db)
        row = db.scalar(select(m.AssetPriceSource).where(m.AssetPriceSource.asset_id == asset.id, m.AssetPriceSource.provider_id == (pv.id if pv else 0)))
        if row is not None and row.external_id:
            raise ConflictError(f"دارایی «{asset.name}» از قبل به نماد {row.external_id} متصل است؛ برای تغییر، آن را از صفحهٔ دارایی یا بازار جامع ویرایش کنید.",
                                code="asset_already_linked", details={"asset_id": asset.id, "asset": asset.name, "symbol": row.external_id})


def link_to_asset(db: Session, symbol: str, asset_id: int, *, confirm: bool, ack_unit: bool = False) -> dict:
    _need_confirm(confirm)
    r = _symbol(db, symbol)
    a = db.get(m.Asset, asset_id)
    if a is None:
        raise NotFoundError("دارایی یافت نشد.")
    if a.is_archived:
        raise ValidationFailure("دارایی بایگانی‌شده به نماد وصل نمی‌شود؛ ابتدا آن را بازیابی کنید.", code="asset_archived")
    _check_not_linked(db, r.symbol, a)
    if r.unit and r.unit != "unit" and not ack_unit:
        raise ValidationFailure(f"قیمت این نماد «هر {_UNIT_FA.get(r.unit, r.unit)}» است؛ باید صریحاً تأیید کنید که مقدار دارایی با همین واحد ثبت می‌شود.", code="unit_not_acknowledged")
    row = im.link_symbol(db, a, r.symbol, confirm=True)
    return {"ok": True, "asset_id": a.id, "asset": a.name, "symbol": row.external_id, "link": im._link_meta(row.link_meta),
            "note": "فقط منبع قیمت دارایی تنظیم شد؛ هیچ تراکنش یا موجودی‌ای ثبت نشد."}


def create_asset_from_symbol(db: Session, symbol: str, *, platform_id: int, portfolio_id: int | None, name: str = "", asset_type: str = "",
                             confirm: bool, ack_unit: bool = False) -> dict:
    """دارایی جدیدِ متصل به نماد؛ بدون تراکنش خرید، بدون موجودی و با وزن هدف صفر."""
    from ..schemas import AssetIn, PriceSourceIn
    from . import assets as asvc
    _need_confirm(confirm)
    r = _symbol(db, symbol)
    _check_not_linked(db, r.symbol)
    if r.unit and r.unit != "unit" and not ack_unit:
        raise ValidationFailure(f"قیمت این نماد «هر {_UNIT_FA.get(r.unit, r.unit)}» است؛ باید صریحاً تأیید کنید که مقدار دارایی با همین واحد ثبت می‌شود.", code="unit_not_acknowledged")
    pv = im.get_provider(db)
    if pv is None:
        raise NotFoundError("منبع Iran Market Data تعریف نشده یا بایگانی شده است.")
    cur = db.get(m.Currency, (r.currency or "").upper())
    if cur is None or not cur.is_active:
        raise ValidationFailure(f"واحد پول نماد ({r.currency or 'نامشخص'}) در سیستم تعریف یا فعال نیست؛ این نماد را نمی‌توان خودکار به دارایی تبدیل کرد.", code="currency_unsupported")
    bl = im.link_blockers(r)
    if bl:
        raise ValidationFailure(bl[0], code="link_blocked", details={"blockers": bl})
    ents = [e for e in build_entries(db) if e.key == f"sym:{r.symbol}"]
    grp = ents[0].group if ents else "other"
    typ = asset_type or _TYPE_BY_GROUP.get(grp, "other")
    t = db.get(m.AssetType, typ)
    if t is None or not t.is_active:
        typ = "other"
    title = (name or "").strip() or (r.name_fa if r.name_fa and r.name_fa != r.symbol else "") or r.name_en or r.symbol
    decimals = 4 if r.unit in ("gram", "troy_ounce", "mesghal", "barrel", "ton", "kg") else (8 if grp == "crypto" else (2 if grp == "currency" else 0))
    payload = AssetIn(platform_id=platform_id, name=title[:120], name_en=(r.name_en if r.name_en != title else "")[:120], symbol=r.symbol[:40], asset_type=typ,
                      market=(r.market or "")[:40], unit=_UNIT_FA.get(r.unit, r.unit or "واحد")[:32], price_currency=cur.code, decimals=decimals,
                      target_weight=Decimal(0), portfolio_id=portfolio_id, note=f"ایجادشده از نتیجهٔ جست‌وجو؛ نماد Iran Market Data: {r.symbol}",
                      sources=[PriceSourceIn(provider_id=pv.id, external_id=r.symbol, priority=1, confirm_link=True)])
    a = asvc.create_asset(db, payload)
    fetch = None
    if pv.is_enabled:
        try:
            from .marketdata.engine import get_engine
            res = get_engine().refresh_asset(db, a, force=True)
            fetch = {"ok": res.get("ok"), "status": res.get("status"), "message": res.get("message")}
        except Exception as exc:  # دریافت قیمت اختیاری است؛ شکست آن نباید ایجاد دارایی را خراب کند
            fetch = {"ok": False, "status": "error", "message": str(exc)[:200]}
    n_tx = db.scalar(select(func.count()).select_from(m.Transaction).where(m.Transaction.asset_id == a.id)) or 0
    return {"ok": True, "asset_id": a.id, "asset": a.name, "symbol": r.symbol, "asset_type": a.asset_type, "transactions_created": n_tx,
            "portfolio_ids": [pa.portfolio_id for pa in db.scalars(select(m.PortfolioAsset).where(m.PortfolioAsset.asset_id == a.id))],
            "price_fetch": fetch, "note": "فقط تعریف دارایی انجام شد؛ هیچ تراکنش خرید، موجودی یا سفارشی ثبت نشد."}


def add_asset_to_portfolio(db: Session, asset_id: int, portfolio_id: int, *, confirm: bool) -> dict:
    from . import portfolios as psvc
    _need_confirm(confirm)
    pf = psvc.get_portfolio(db, portfolio_id)
    psvc.add_member(db, pf, asset_id, Decimal(0), Decimal(0))
    a = db.get(m.Asset, asset_id)
    return {"ok": True, "asset_id": asset_id, "asset": a.name if a else "", "portfolio_id": pf.id, "portfolio": pf.name,
            "note": "دارایی با وزن هدف صفر به سبد اضافه شد؛ تراکنش یا موجودی‌ای ثبت نشد."}
