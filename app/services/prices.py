"""ثبت قیمت‌ها و نرخ ارز (دستی یا از طریق ارائه‌دهندگان) — بدون اختلال در صورت خطای منبع."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..errors import NotFoundError, ValidationFailure
from .clock import now_local
from ..errors import ConflictError

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
    when = _check_time(p.get("recorded_at"))
    dup = db.scalar(select(m.Price.id).where(m.Price.asset_id == asset.id, m.Price.provider_id.is_(None),
                                             m.Price.price == p["price"], m.Price.recorded_at == when))
    if dup:
        raise ConflictError("این قیمت با همین زمان قبلاً برای این دارایی ثبت شده است (جلوگیری از ثبت تکراری).", code="duplicate_price")
    row = m.Price(asset_id=asset.id, price=p["price"], currency=currency, recorded_at=when, price_kind="manual",
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
