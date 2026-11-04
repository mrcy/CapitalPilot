"""انواع دارایی و پلتفرم‌ها: ایجاد، ویرایش، بایگانی/بازیابی و حذف ایمن."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..errors import ConflictError, NotFoundError, ValidationFailure
from .clock import now_local


# ---------------- انواع دارایی ----------------
def type_fields(t: m.AssetType) -> list[dict]:
    try:
        return json.loads(t.fields_schema or "[]")
    except ValueError:
        return []


def type_dict(db: Session, t: m.AssetType) -> dict:
    n = db.scalar(select(func.count()).select_from(m.Asset).where(m.Asset.asset_type == t.key)) or 0
    return {"key": t.key, "label": t.label, "label_en": t.label_en, "color": t.color, "fields": type_fields(t),
            "is_system": t.is_system, "is_active": t.is_active, "sort_order": t.sort_order, "asset_count": n}


def save_type(db: Session, p, key: str | None = None) -> m.AssetType:
    t = db.get(m.AssetType, key) if key else None
    if key and t is None:
        raise NotFoundError("نوع دارایی یافت نشد.")
    if t is None:
        if db.get(m.AssetType, p.key):
            raise ConflictError("این کلید نوع دارایی قبلاً ثبت شده است.")
        t = m.AssetType(key=p.key, is_system=False)
        db.add(t)
    keys = [f.key for f in p.fields]
    if len(set(keys)) != len(keys):
        raise ValidationFailure("کلید فیلدهای اختصاصی نباید تکراری باشد.")
    for f in p.fields:
        if f.type == "select" and not f.options:
            raise ValidationFailure(f"برای فیلد «{f.label}» گزینه‌ها را تعریف کنید.")
    t.label, t.label_en, t.color, t.is_active, t.sort_order = p.label, p.label_en, p.color, p.is_active, p.sort_order
    t.fields_schema = json.dumps([f.model_dump(exclude_none=True) for f in p.fields], ensure_ascii=False)
    db.commit()
    return t


def delete_type(db: Session, key: str) -> None:
    t = db.get(m.AssetType, key)
    if t is None:
        raise NotFoundError("نوع دارایی یافت نشد.")
    if t.is_system:
        raise ValidationFailure("نوع‌های سیستمی قابل حذف نیستند؛ می‌توانید آن را غیرفعال کنید.")
    n = db.scalar(select(func.count()).select_from(m.Asset).where(m.Asset.asset_type == key)) or 0
    if n:
        raise ConflictError(f"{n} دارایی از این نوع استفاده می‌کنند؛ فقط غیرفعال‌سازی ممکن است.", code="in_use")
    db.delete(t)
    db.commit()


def validate_extra(db: Session, type_key: str, extra: dict) -> dict:
    """اعتبارسنجی فیلدهای اختصاصی نوع؛ فیلد ناشناخته پذیرفته نمی‌شود."""
    t = db.get(m.AssetType, type_key)
    if t is None:
        raise ValidationFailure("نوع دارایی تعریف نشده است. ابتدا آن را در «انواع دارایی» بسازید.")
    defs = {f["key"]: f for f in type_fields(t)}
    out = {}
    for k, v in (extra or {}).items():
        if v is None or v == "":
            continue
        f = defs.get(k)
        if f is None:
            raise ValidationFailure(f"فیلد «{k}» برای نوع «{t.label}» تعریف نشده است.")
        if f["type"] == "number":
            try:
                float(v)
            except (TypeError, ValueError):
                raise ValidationFailure(f"مقدار «{f['label']}» باید عدد باشد.")
        if f["type"] == "select" and v not in f.get("options", []):
            raise ValidationFailure(f"مقدار «{f['label']}» باید یکی از گزینه‌های تعریف‌شده باشد.")
        out[k] = v
    return out


# ---------------- پلتفرم‌ها ----------------
def platform_dict(db: Session, p: m.Platform) -> dict:
    n_assets = db.scalar(select(func.count()).select_from(m.Asset).where(m.Asset.platform_id == p.id)) or 0
    n_active = db.scalar(select(func.count()).select_from(m.Asset).where(
        m.Asset.platform_id == p.id, m.Asset.is_active.is_(True), m.Asset.is_archived.is_(False))) or 0
    n_tx = db.scalar(select(func.count()).select_from(m.Transaction).where(m.Transaction.platform_id == p.id)) or 0
    return {"id": p.id, "name": p.name, "kind": p.kind, "is_active": p.is_active, "is_archived": p.is_archived,
            "note": p.note, "sort_order": p.sort_order, "asset_count": n_assets, "active_asset_count": n_active,
            "transaction_count": n_tx}


def save_platform(db: Session, p, pid: int | None = None) -> m.Platform:
    pl = db.get(m.Platform, pid) if pid else None
    if pid and pl is None:
        raise NotFoundError("پلتفرم یافت نشد.")
    dup = db.scalar(select(m.Platform).where(m.Platform.name == p.name, m.Platform.id != (pid or 0)))
    if dup:
        raise ConflictError("پلتفرمی با این نام وجود دارد.")
    if pl is None:
        pl = m.Platform()
        db.add(pl)
    pl.name, pl.kind, pl.is_active, pl.note, pl.sort_order = p.name, p.kind, p.is_active, p.note, p.sort_order
    db.commit()
    return pl


def archive_platform(db: Session, pid: int, archive: bool) -> m.Platform:
    pl = db.get(m.Platform, pid)
    if pl is None:
        raise NotFoundError("پلتفرم یافت نشد.")
    pl.is_archived = archive
    pl.archived_at = now_local() if archive else None
    if archive:
        pl.is_active = False
    else:
        pl.is_active = True
    db.commit()
    return pl


def delete_platform(db: Session, pid: int) -> None:
    pl = db.get(m.Platform, pid)
    if pl is None:
        raise NotFoundError("پلتفرم یافت نشد.")
    d = platform_dict(db, pl)
    if d["transaction_count"]:
        raise ConflictError(f"این پلتفرم {d['transaction_count']} تراکنش دارد و فقط قابل بایگانی است.",
                            code="has_transactions", details=d)
    if d["asset_count"]:
        raise ConflictError(f"{d['asset_count']} دارایی به این پلتفرم وابسته است؛ ابتدا آن‌ها را حذف یا بایگانی کنید.",
                            code="has_dependencies", details=d)
    db.delete(pl)
    db.commit()
