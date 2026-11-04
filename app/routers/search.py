"""جست‌وجوی سراسری بازار: فقط روی داده‌های ذخیره‌شدهٔ دیتابیس (بدون هیچ درخواست شبکه). عملیات فقط با تأیید صریح."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import search as svc

router = APIRouter(prefix="/api/search", tags=["search"])


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LinkIn(_Body):
    symbol: str = Field(min_length=1, max_length=120)
    asset_id: int
    confirm: bool = False
    ack_unit: bool = False


class CreateAssetIn(_Body):
    symbol: str = Field(min_length=1, max_length=120)
    platform_id: int
    portfolio_id: int | None = None
    name: str = Field(default="", max_length=120)
    asset_type: str = Field(default="", max_length=32)
    confirm: bool = False
    ack_unit: bool = False


class AddToPortfolioIn(_Body):
    asset_id: int
    portfolio_id: int
    confirm: bool = False


@router.get("")
def search(q: str = Query("", max_length=80), group: str = Query("all", max_length=20), page: int = Query(1, ge=1),
           page_size: int = Query(20, ge=1, le=100), per_group: int = Query(5, ge=1, le=20), db: Session = Depends(get_db)):
    """جست‌وجو در نمادها، دارایی‌ها، پلتفرم‌ها و بازارها؛ فقط‌خواندنی و بدون شبکه."""
    return svc.search(db, q, group=group, page=page, page_size=page_size, per_group=per_group)


@router.get("/suggestions")
def suggestions(db: Session = Depends(get_db)):
    return svc.suggestions(db)


@router.post("/link")
def link(payload: LinkIn, db: Session = Depends(get_db)):
    return svc.link_to_asset(db, payload.symbol, payload.asset_id, confirm=payload.confirm, ack_unit=payload.ack_unit)


@router.post("/create-asset", status_code=201)
def create_asset(payload: CreateAssetIn, db: Session = Depends(get_db)):
    return svc.create_asset_from_symbol(db, payload.symbol, platform_id=payload.platform_id, portfolio_id=payload.portfolio_id, name=payload.name,
                                        asset_type=payload.asset_type, confirm=payload.confirm, ack_unit=payload.ack_unit)


@router.post("/add-to-portfolio", status_code=201)
def add_to_portfolio(payload: AddToPortfolioIn, db: Session = Depends(get_db)):
    return svc.add_asset_to_portfolio(db, payload.asset_id, payload.portfolio_id, confirm=payload.confirm)
