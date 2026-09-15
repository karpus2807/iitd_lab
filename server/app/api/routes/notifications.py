from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep
from app.models import Notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(db: DbDep, user: CurrentUser, unread: bool | None = None):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread:
        stmt = stmt.where(Notification.read.is_(False))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(100)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(n.id),
            "title": n.title,
            "body": n.body,
            "read": n.read,
            "payload": n.payload,
            "created_at": n.created_at,
        }
        for n in rows
    ]


@router.post("/{notification_id}/read")
async def mark_read(notification_id: UUID, db: DbDep, user: CurrentUser):
    row = await db.get(Notification, notification_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Not found")
    row.read = True
    await db.commit()
    return {"ok": True}


@router.post("/read-all")
async def mark_all(db: DbDep, user: CurrentUser):
    rows = (await db.execute(select(Notification).where(Notification.user_id == user.id, Notification.read.is_(False)))).scalars().all()
    for row in rows:
        row.read = True
    await db.commit()
    return {"ok": True, "updated": len(rows)}
