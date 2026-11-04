"""خطاهای دامنه و مدیریت یکپارچه خطا."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

log = logging.getLogger("capitalpilot.errors")


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, details=None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ValidationFailure(AppError):
    status_code = 422
    code = "validation_error"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


def _payload(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


_FIELD_FA = {
    "quantity": "تعداد واحد", "unit_price": "قیمت هر واحد", "fee": "کارمزد", "amount": "مبلغ", "tx_date": "تاریخ",
    "price": "قیمت", "name": "نام", "rate": "نرخ", "target_weight": "وزن هدف",
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_payload(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        items = []
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
            field = ".".join(loc)
            items.append({"field": field, "message": err.get("msg", "")})
        first = items[0] if items else {"field": "", "message": "ورودی نامعتبر است"}
        label = _FIELD_FA.get(first["field"], first["field"])
        msg = f"ورودی نامعتبر است ({label}): {first['message']}" if label else "ورودی نامعتبر است"
        return JSONResponse(status_code=422, content=_payload("validation_error", msg, items))

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError):
        log.warning("Integrity error: %s", exc)
        return JSONResponse(status_code=409, content=_payload("integrity_error", "این عملیات با داده‌های موجود تداخل دارد (مثلاً نام تکراری)."))

    @app.exception_handler(SQLAlchemyError)
    async def _db(_: Request, exc: SQLAlchemyError):
        log.exception("Database error")
        return JSONResponse(status_code=500, content=_payload("database_error", "خطای دیتابیس رخ داد. جزئیات در لاگ ثبت شد."))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content=_payload("internal_error", "خطای داخلی سرور. جزئیات در لاگ ثبت شد."))
