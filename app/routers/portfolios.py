from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..schemas import PortfolioIn, PortfolioMemberIn, PortfolioTargetsIn
from ..services import portfolios as svc

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


@router.get("")
def list_portfolios(include_archived: bool = True, db: Session = Depends(get_db)):
    stmt = select(m.Portfolio).order_by(m.Portfolio.sort_order, m.Portfolio.id)
    if not include_archived:
        stmt = stmt.where(m.Portfolio.is_archived.is_(False))
    return [svc.portfolio_dict(db, p) for p in db.scalars(stmt)]


@router.post("", status_code=201)
def create_portfolio(payload: PortfolioIn, db: Session = Depends(get_db)):
    return svc.portfolio_dict(db, svc.save_portfolio(db, payload), with_members=True)


@router.get("/{pid}")
def get_portfolio(pid: int, db: Session = Depends(get_db)):
    return svc.portfolio_dict(db, svc.get_portfolio(db, pid), with_members=True)


@router.put("/{pid}")
def update_portfolio(pid: int, payload: PortfolioIn, db: Session = Depends(get_db)):
    return svc.portfolio_dict(db, svc.save_portfolio(db, payload, pid), with_members=True)


@router.put("/{pid}/targets")
def set_targets(pid: int, payload: PortfolioTargetsIn, db: Session = Depends(get_db)):
    pf = svc.get_portfolio(db, pid)
    warnings = svc.set_targets(db, pf, payload.members)
    return {"portfolio": svc.portfolio_dict(db, pf, with_members=True), "warnings": warnings}


@router.post("/{pid}/assets", status_code=201)
def add_asset(pid: int, payload: PortfolioMemberIn, db: Session = Depends(get_db)):
    pf = svc.get_portfolio(db, pid)
    svc.add_member(db, pf, payload.asset_id, payload.target_weight, payload.target_amount)
    return svc.portfolio_dict(db, pf, with_members=True)


@router.delete("/{pid}/assets/{asset_id}")
def remove_asset(pid: int, asset_id: int, db: Session = Depends(get_db)):
    pf = svc.get_portfolio(db, pid)
    res = svc.remove_member(db, pf, asset_id)
    return {**res, "portfolio": svc.portfolio_dict(db, pf, with_members=True)}


@router.post("/{pid}/archive")
def archive(pid: int, db: Session = Depends(get_db)):
    return svc.portfolio_dict(db, svc.archive_portfolio(db, svc.get_portfolio(db, pid), True))


@router.post("/{pid}/restore")
def restore(pid: int, db: Session = Depends(get_db)):
    return svc.portfolio_dict(db, svc.archive_portfolio(db, svc.get_portfolio(db, pid), False))


@router.post("/{pid}/make-default")
def make_default(pid: int, db: Session = Depends(get_db)):
    return svc.portfolio_dict(db, svc.make_default(db, svc.get_portfolio(db, pid)))


@router.delete("/{pid}")
def delete(pid: int, db: Session = Depends(get_db)):
    svc.delete_portfolio(db, svc.get_portfolio(db, pid))
    return {"ok": True}
