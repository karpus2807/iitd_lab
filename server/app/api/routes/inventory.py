from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbDep, OperatorUser, write_audit
from app.models import InventoryItem, Machine, utcnow
from app.schemas.inv_mgmt import (
    InventoryBatchUpdate,
    InventoryIdsBody,
    InventoryItemCreate,
    InventoryItemOut,
    InventoryItemUpdate,
    InventoryListOut,
    InventoryRemoveBody,
    InventorySuggestItem,
)
from app.services import inv_mgmt as svc

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


def _out(
    row: InventoryItem,
    *,
    machine: Machine | None = None,
) -> InventoryItemOut:
    base = InventoryItemOut.model_validate(row)
    registered = machine is not None
    return base.model_copy(
        update={
            "registered": registered,
            "assigned": svc.is_assigned_item(row),
            "machine_id": machine.id if machine else None,
            "machine_hostname": (machine.hostname or machine.display_name or None) if machine else None,
        }
    )


def _apply_fields(row: InventoryItem, data: dict) -> None:
    for key in svc.MUTABLE_FIELDS:
        if key not in data:
            continue
        val = data[key]
        if key == "ic_no" and val is not None:
            setattr(row, key, str(val).strip())
        elif key in {
            "item_name",
            "item_description",
            "inventory_type",
            "inventory_location",
            "inv_type",
            "remark",
            "assigned_to",
        }:
            if val is not None:
                setattr(row, key, str(val).strip())
        elif key in {"net_effective_value", "gis_date"}:
            setattr(row, key, val)


async def _get_or_404(db, item_id: UUID) -> InventoryItem:
    row = await db.get(InventoryItem, item_id)
    if not row:
        raise HTTPException(404, "Inventory item not found")
    return row


async def _machines_by_ic(db, ic_nos: list[str]) -> dict[str, Machine]:
    """Map lower(ic_no) → Machine where machines.inventory_id matches."""
    needles = sorted({(ic or "").strip().lower() for ic in ic_nos if (ic or "").strip()})
    if not needles:
        return {}
    rows = (
        await db.execute(select(Machine).where(func.lower(Machine.inventory_id).in_(needles)))
    ).scalars().all()
    out: dict[str, Machine] = {}
    for m in rows:
        key = (m.inventory_id or "").strip().lower()
        if key and key not in out:
            out[key] = m
    return out


@router.get("", response_model=InventoryListOut)
async def list_inventory(
    db: DbDep,
    user: CurrentUser,
    q: str = "",
    status: str = Query(default="active", pattern="^(active|removed|all)$"),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(InventoryItem)
    count_stmt = select(func.count()).select_from(InventoryItem)
    if status != "all":
        stmt = stmt.where(InventoryItem.status == status)
        count_stmt = count_stmt.where(InventoryItem.status == status)
    needle = (q or "").strip()
    if needle:
        like = f"%{needle}%"
        filt = or_(
            InventoryItem.ic_no.ilike(like),
            InventoryItem.item_name.ilike(like),
            InventoryItem.item_description.ilike(like),
            InventoryItem.inventory_location.ilike(like),
            InventoryItem.inventory_type.ilike(like),
            InventoryItem.inv_type.ilike(like),
            InventoryItem.remark.ilike(like),
            InventoryItem.assigned_to.ilike(like),
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        await db.execute(stmt.order_by(InventoryItem.ic_no.asc()).offset(offset).limit(limit))
    ).scalars().all()
    machines = await _machines_by_ic(db, [r.ic_no for r in rows])
    items = [
        _out(r, machine=machines.get((r.ic_no or "").strip().lower()))
        for r in rows
    ]
    return InventoryListOut(items=items, total=total, status=status)


@router.get("/suggest", response_model=list[InventorySuggestItem])
async def suggest_inventory(
    db: DbDep,
    user: CurrentUser,
    q: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
):
    like = f"%{q.strip()}%"
    rows = (
        await db.execute(
            select(InventoryItem)
            .where(
                InventoryItem.status == "active",
                or_(
                    InventoryItem.ic_no.ilike(like),
                    InventoryItem.item_name.ilike(like),
                    InventoryItem.inventory_location.ilike(like),
                ),
            )
            .order_by(InventoryItem.ic_no.asc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        InventorySuggestItem(
            id=r.id,
            ic_no=r.ic_no,
            item_name=r.item_name or "",
            inventory_location=r.inventory_location or "",
            inv_type=r.inv_type or "",
        )
        for r in rows
    ]


@router.get("/template.xlsx")
async def download_template_xlsx(user: CurrentUser):
    return Response(
        content=svc.build_template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="labwatch-inventory-template.xlsx"'},
    )


@router.get("/template.csv")
async def download_template_csv(user: CurrentUser):
    return Response(
        content=svc.build_template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="labwatch-inventory-template.csv"'},
    )


@router.get("/export.xlsx")
async def export_xlsx(
    db: DbDep,
    user: CurrentUser,
    status: str = Query(default="active", pattern="^(active|removed|all)$"),
):
    stmt = select(InventoryItem).order_by(InventoryItem.ic_no.asc())
    if status != "all":
        stmt = stmt.where(InventoryItem.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return Response(
        content=svc.build_export_xlsx(rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="labwatch-inventory-{status}.xlsx"'},
    )


@router.get("/export.csv")
async def export_csv(
    db: DbDep,
    user: CurrentUser,
    status: str = Query(default="active", pattern="^(active|removed|all)$"),
):
    stmt = select(InventoryItem).order_by(InventoryItem.ic_no.asc())
    if status != "all":
        stmt = stmt.where(InventoryItem.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return Response(
        content=svc.build_export_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="labwatch-inventory-{status}.csv"'},
    )


@router.post("/import")
async def import_inventory(
    db: DbDep,
    user: OperatorUser,
    request: Request,
    file: UploadFile = File(...),
):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    try:
        rows = svc.parse_import_bytes(raw, file.filename or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not parse file: {exc}") from exc

    created = 0
    updated = 0
    restored = 0
    errors: list[str] = []
    for parsed in rows:
        ic = parsed["ic_no"]
        try:
            existing = (
                await db.execute(select(InventoryItem).where(InventoryItem.ic_no == ic))
            ).scalar_one_or_none()
            if existing:
                was_removed = existing.status == "removed"
                for key in svc.MUTABLE_FIELDS:
                    if key == "ic_no":
                        continue
                    setattr(existing, key, parsed.get(key))
                if was_removed:
                    existing.status = "active"
                    existing.removed_at = None
                    existing.removed_by = None
                    existing.removal_remark = None
                    restored += 1
                else:
                    updated += 1
            else:
                db.add(
                    InventoryItem(
                        ic_no=ic,
                        item_name=parsed.get("item_name") or "",
                        item_description=parsed.get("item_description") or "",
                        net_effective_value=parsed.get("net_effective_value"),
                        inventory_type=parsed.get("inventory_type") or "",
                        inventory_location=parsed.get("inventory_location") or "",
                        gis_date=parsed.get("gis_date"),
                        inv_type=parsed.get("inv_type") or "",
                        remark=parsed.get("remark") or "",
                        status="active",
                    )
                )
                created += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{ic}: {exc}")
    await write_audit(
        db,
        "inventory.import",
        user=user,
        details={
            "filename": file.filename,
            "created": created,
            "updated": updated,
            "restored": restored,
            "errors": errors[:20],
        },
        request=request,
    )
    await db.commit()
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "restored": restored,
        "errors": errors,
        "total_rows": len(rows),
    }


@router.post("/batch", response_model=dict)
async def batch_update(body: InventoryBatchUpdate, db: DbDep, user: OperatorUser, request: Request):
    data = body.fields.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    if "ic_no" in data:
        raise HTTPException(400, "Batch update cannot change IC No.; edit items individually")
    updated = 0
    missing: list[str] = []
    for item_id in body.ids:
        row = await db.get(InventoryItem, item_id)
        if not row:
            missing.append(str(item_id))
            continue
        _apply_fields(row, data)
        updated += 1
    await write_audit(
        db,
        "inventory.batch_update",
        user=user,
        details={"updated": updated, "missing": missing, "fields": list(data.keys())},
        request=request,
    )
    await db.commit()
    return {"ok": True, "updated": updated, "missing": missing}


@router.post("/remove", response_model=dict)
async def remove_inventory(body: InventoryRemoveBody, db: DbDep, user: OperatorUser, request: Request):
    remark = body.remark.strip()
    if not remark:
        raise HTTPException(400, "Removal remark is required")
    removed = 0
    missing: list[str] = []
    now = utcnow()
    for item_id in body.ids:
        row = await db.get(InventoryItem, item_id)
        if not row:
            missing.append(str(item_id))
            continue
        row.status = "removed"
        row.removed_at = now
        row.removed_by = user.username
        row.removal_remark = remark
        removed += 1
    await write_audit(
        db,
        "inventory.remove",
        user=user,
        details={"removed": removed, "missing": missing, "remark": remark},
        request=request,
    )
    await db.commit()
    return {"ok": True, "removed": removed, "missing": missing}


@router.post("/restore", response_model=dict)
async def restore_inventory(body: InventoryIdsBody, db: DbDep, user: OperatorUser, request: Request):
    restored = 0
    missing: list[str] = []
    skipped: list[str] = []
    for item_id in body.ids:
        row = await db.get(InventoryItem, item_id)
        if not row:
            missing.append(str(item_id))
            continue
        if row.status != "removed":
            skipped.append(row.ic_no)
            continue
        row.status = "active"
        row.removed_at = None
        row.removed_by = None
        row.removal_remark = None
        restored += 1
    await write_audit(
        db,
        "inventory.restore",
        user=user,
        details={"restored": restored, "missing": missing, "skipped": skipped},
        request=request,
    )
    await db.commit()
    return {"ok": True, "restored": restored, "missing": missing, "skipped": skipped}


@router.post("/purge", response_model=dict)
async def purge_inventory(body: InventoryIdsBody, db: DbDep, user: OperatorUser, request: Request):
    """Permanently delete soft-removed inventory rows. Active items are skipped."""
    deleted = 0
    missing: list[str] = []
    skipped: list[str] = []
    deleted_ics: list[str] = []
    for item_id in body.ids:
        row = await db.get(InventoryItem, item_id)
        if not row:
            missing.append(str(item_id))
            continue
        if row.status != "removed":
            skipped.append(row.ic_no)
            continue
        deleted_ics.append(row.ic_no)
        await db.delete(row)
        deleted += 1
    await write_audit(
        db,
        "inventory.purge",
        user=user,
        details={"deleted": deleted, "ic_nos": deleted_ics[:50], "missing": missing, "skipped": skipped},
        request=request,
    )
    await db.commit()
    return {"ok": True, "deleted": deleted, "missing": missing, "skipped": skipped}


@router.post("/empty-removed", response_model=dict)
async def empty_removed_inventory(db: DbDep, user: OperatorUser, request: Request):
    """Permanently delete every soft-removed inventory row."""
    rows = (
        await db.execute(select(InventoryItem).where(InventoryItem.status == "removed"))
    ).scalars().all()
    deleted_ics = [r.ic_no for r in rows]
    for row in rows:
        await db.delete(row)
    deleted = len(deleted_ics)
    await write_audit(
        db,
        "inventory.empty_removed",
        user=user,
        details={"deleted": deleted, "ic_nos": deleted_ics[:50]},
        request=request,
    )
    await db.commit()
    return {"ok": True, "deleted": deleted}


@router.post("", response_model=InventoryItemOut)
async def create_inventory(body: InventoryItemCreate, db: DbDep, user: OperatorUser, request: Request):
    ic = body.ic_no.strip()
    if not ic:
        raise HTTPException(400, "IC No. is required")
    exists = (
        await db.execute(select(InventoryItem).where(InventoryItem.ic_no == ic))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(409, f"IC No. {ic} already exists")
    row = InventoryItem(
        ic_no=ic,
        item_name=(body.item_name or "").strip(),
        item_description=(body.item_description or "").strip(),
        net_effective_value=body.net_effective_value,
        inventory_type=(body.inventory_type or "").strip(),
        inventory_location=(body.inventory_location or "").strip(),
        gis_date=body.gis_date,
        inv_type=(body.inv_type or "").strip(),
        remark=(body.remark or "").strip(),
        assigned_to=(body.assigned_to or "").strip(),
        status="active",
    )
    db.add(row)
    await write_audit(db, "inventory.create", user=user, details={"ic_no": ic}, request=request)
    await db.commit()
    await db.refresh(row)
    machines = await _machines_by_ic(db, [row.ic_no])
    return _out(row, machine=machines.get(row.ic_no.strip().lower()))


@router.get("/{item_id}", response_model=InventoryItemOut)
async def get_inventory(item_id: UUID, db: DbDep, user: CurrentUser):
    row = await _get_or_404(db, item_id)
    machines = await _machines_by_ic(db, [row.ic_no])
    return _out(row, machine=machines.get((row.ic_no or "").strip().lower()))


@router.patch("/{item_id}", response_model=InventoryItemOut)
async def update_inventory(
    item_id: UUID, body: InventoryItemUpdate, db: DbDep, user: OperatorUser, request: Request
):
    row = await _get_or_404(db, item_id)
    data = body.model_dump(exclude_unset=True)
    if "ic_no" in data and data["ic_no"] is not None:
        new_ic = str(data["ic_no"]).strip()
        if new_ic != row.ic_no:
            clash = (
                await db.execute(
                    select(InventoryItem).where(InventoryItem.ic_no == new_ic, InventoryItem.id != row.id)
                )
            ).scalar_one_or_none()
            if clash:
                raise HTTPException(409, f"IC No. {new_ic} already exists")
            data["ic_no"] = new_ic
    _apply_fields(row, data)
    await write_audit(
        db,
        "inventory.update",
        user=user,
        details={"id": str(row.id), "ic_no": row.ic_no, "fields": list(data.keys())},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    machines = await _machines_by_ic(db, [row.ic_no])
    return _out(row, machine=machines.get((row.ic_no or "").strip().lower()))
