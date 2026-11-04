"""ثبت قیمت‌ها و نرخ ارز (دستی یا از طریق ارائه‌دهندگان) — بدون اختلال در صورت خطای منبع."""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..errors import NotFoundError, ValidationFailure
from .clock import now_local
from .price_providers import ProviderError, get_provider

log = logging.getLogger("capitalpilot.prices")


def _check_time(rec_at):
    now = now_local()
    if rec_at is None:
        return now
    if rec_at.tzinfo is not None:
        rec_at = rec_at.replace(tzinfo=None)
    if rec_at > now + timedelta(minutes=5):
        raise ValidationFailure("زمان ثبت قیمت نمی‌تواند در آینده باشد.")
    return rec_at


def create_price(db: Session, p: dict) -> m.Price:
    asset = db.get(m.Asset, p["asset_id"])
    if asset is None:
        raise NotFoundError("دارایی یافت نشد.")
    currency = (p.get("currency") or asset.price_currency).upper()
    if currency != asset.price_currency:
        raise ValidationFailure(f"واحد پول قیمت باید «{asset.price_currency}» (واحد پول دارایی) باشد.")
    row = m.Price(asset_id=asset.id, price=p["price"], currency=currency, recorded_at=_check_time(p.get("recorded_at")),
                  source=p.get("source") or "manual", is_approved=p.get("is_approved", True), note=p.get("note", ""))
    db.add(row)
    db.commit()
    return row


def update_price(db: Session, price_id: int, p: dict) -> m.Price:
    row = db.get(m.Price, price_id)
    if row is None:
        raise NotFoundError("قیمت یافت نشد.")
    asset = db.get(m.Asset, p["asset_id"])
    if asset is None:
        raise NotFoundError("دارایی یافت نشد.")
    currency = (p.get("currency") or asset.price_currency).upper()
    if currency != asset.price_currency:
        raise ValidationFailure(f"واحد پول قیمت باید «{asset.price_currency}» باشد.")
    row.asset_id, row.price, row.currency = asset.id, p["price"], currency
    row.recorded_at = _check_time(p.get("recorded_at")) if p.get("recorded_at") else row.recorded_at
    row.source, row.is_approved, row.note = p.get("source") or row.source, p.get("is_approved", True), p.get("note", "")
    db.commit()
    return row


def create_fx(db: Session, p: dict) -> m.FxRate:
    cur = db.get(m.Currency, p["currency"].upper())
    if cur is None:
        raise NotFoundError("واحد پول یافت نشد؛ ابتدا آن را در تنظیمات اضافه کنید.")
    if cur.is_base:
        raise ValidationFailure("نرخ تبدیل برای واحد پایه (تومان) معنا ندارد.")
    row = m.FxRate(currency=cur.code, rate=p["rate"], recorded_at=_check_time(p.get("recorded_at")),
                   source=p.get("source") or "manual", is_approved=p.get("is_approved", True), note=p.get("note", ""))
    db.add(row)
    db.commit()
    return row


def fetch_all(db: Session, asset_ids: list[int] | None = None, auto_approve: bool = False) -> list[dict]:
    """دریافت خودکار قیمت برای دارایی‌هایی که منبع دارند. هر خطا فقط در نتیجه همان دارایی گزارش می‌شود."""
    q = select(m.Asset).where(m.Asset.is_active.is_(True), m.Asset.price_provider != "")
    if asset_ids:
        q = q.where(m.Asset.id.in_(asset_ids))
    results = []
    for a in db.scalars(q):
        try:
            params = json.loads(a.price_provider_params or "{}")
            quote = get_provider(a.price_provider).fetch(params)
            cur = (quote.currency or a.price_currency).upper()
            if cur != a.price_currency:
                raise ProviderError("واحد پول قیمت دریافتی با واحد پول دارایی یکسان نیست.")
            db.add(m.Price(asset_id=a.id, price=quote.price, currency=cur, recorded_at=quote.recorded_at or now_local(),
                           source=f"api:{a.price_provider}", is_approved=auto_approve,
                           note="دریافت خودکار — نیازمند تأیید" if not auto_approve else "دریافت خودکار"))
            db.commit()
            results.append({"asset_id": a.id, "asset": a.name, "ok": True, "price": quote.price,
                            "message": "قیمت دریافت شد" + ("" if auto_approve else " (در انتظار تأیید)")})
        except (ProviderError, ValueError, json.JSONDecodeError) as e:
            db.rollback()
            log.warning("price fetch failed for asset %s: %s", a.id, e)
            results.append({"asset_id": a.id, "asset": a.name, "ok": False, "message": str(e)})
    return results
