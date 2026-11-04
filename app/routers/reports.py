from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import NotFoundError, ValidationFailure
from ..services import clock, reports as svc
from ..services.exports import EXPORTERS
from ..services.repository import get_settings_row, load_dataset

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
def catalog():
    return svc.catalog()


def _params(date_: date | None, year: int | None, month: int | None, quarter: int | None,
            date_from: date | None, date_to: date | None) -> dict:
    return {"date": date_, "year": year, "month": month, "quarter": quarter, "date_from": date_from, "date_to": date_to}


@router.get("/{key}")
def get_report(key: str, date: date | None = None, year: int | None = Query(None, ge=1000, le=3000),
               month: int | None = Query(None, ge=1, le=12), quarter: int | None = Query(None, ge=1, le=4),
               date_from: date | None = None, date_to: date | None = None, db: Session = Depends(get_db)):
    if key not in svc.TITLES:
        raise NotFoundError("گزارش یافت نشد.")
    return svc.build_report(load_dataset(db), key, _params(date, year, month, quarter, date_from, date_to), clock.now_local())


@router.get("/{key}/export")
def export_report(key: str, format: str = Query("xlsx", pattern="^(csv|xlsx|pdf)$"), date: date | None = None,
                  year: int | None = Query(None, ge=1000, le=3000), month: int | None = Query(None, ge=1, le=12),
                  quarter: int | None = Query(None, ge=1, le=4), date_from: date | None = None, date_to: date | None = None,
                  db: Session = Depends(get_db)):
    if key not in svc.TITLES:
        raise NotFoundError("گزارش یافت نشد.")
    ds = load_dataset(db)
    report = svc.build_report(ds, key, _params(date, year, month, quarter, date_from, date_to), clock.now_local())
    fn, media, ext = EXPORTERS[format]
    unit = get_settings_row(db).currency_label
    body = fn(report, ds.config.calendar, unit)
    name = f"capitalpilot-{key}-{clock.today_local().isoformat()}.{ext}"
    return Response(content=body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})
