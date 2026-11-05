"""پشتیبان‌گیری، بازیابی و پاک‌سازی."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ValidationFailure
from ..schemas import ResetConfirmIn, ResetRequestIn
from ..services import backup, clock

router = APIRouter(prefix="/api", tags=["data"])
MAX_RESTORE_BYTES = 50_000_000


@router.get("/backup/export")
def export_backup(db: Session = Depends(get_db)):
    data = backup.export_json(db)
    name = f"capitalpilot-backup-{clock.now_local().strftime('%Y%m%d-%H%M%S')}.json"
    return Response(json.dumps(data, ensure_ascii=False, indent=1), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/backup/restore")
async def restore_backup(request: Request, confirm: bool = Query(False), db: Session = Depends(get_db)):
    if not confirm:
        raise ValidationFailure("بازیابی جایگزین تمام اطلاعات فعلی می‌شود؛ تأیید لازم است (confirm=true).")
    body = await request.body()
    if len(body) > MAX_RESTORE_BYTES:
        raise ValidationFailure("حجم فایل پشتیبان بیش از حد مجاز است.")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise ValidationFailure("فایل پشتیبان JSON معتبر نیست.")
    return backup.restore_json(db, data)


@router.post("/backup/db")
def backup_db(db: Session = Depends(get_db)):
    return backup.save_db_backup(db, "manual")


@router.get("/backup/list")
def list_backups():
    return backup.list_backups()


@router.post("/data/reset/request")
def reset_request(payload: ResetRequestIn):
    return backup.request_reset(payload.scope)


@router.post("/data/reset/confirm")
def reset_confirm(payload: ResetConfirmIn, db: Session = Depends(get_db)):
    return backup.confirm_reset(db, payload.token, payload.phrase, payload.scope)
