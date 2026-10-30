from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbDep, OperatorUser, write_audit
from app.models import InventoryItem, Lab, Scholar, utcnow
from app.schemas.scholars import ScholarIdsBody, ScholarListOut, ScholarOut, ScholarRemoveBody
from app.services import scholar_mgmt as xls
from app.services import scholar_photos as photos

router = APIRouter(prefix="/api/scholars", tags=["scholars"])

DEFAULT_GROUPS = ["M.Tech", "Ph.D.", "Postdoc", "Project Staff", "Intern", "Faculty", "Other"]


def _out(row: Scholar, lab: Lab | None = None, inv: InventoryItem | None = None) -> ScholarOut:
    lab_obj = lab or getattr(row, "lab", None)
    inv_obj = inv or getattr(row, "inventory_item", None)
    return ScholarOut(
        id=row.id,
        lab_id=row.lab_id,
        lab_name=(lab_obj.name if lab_obj else "") or "",
        lab_room=(getattr(lab_obj, "room", None) or "") if lab_obj else "",
        full_name=row.full_name or "",
        scholar_id=row.scholar_id or "",
        group_name=row.group_name or "",
        faculty=row.faculty or "",
        system_required=bool(row.system_required),
        inventory_kind=row.inventory_kind or "none",
        inventory_item_id=row.inventory_item_id,
        inventory_label=row.inventory_label or "",
        inventory_item_name=(inv_obj.item_name if inv_obj else "") or "",
        email=row.email or "",
        phone=row.phone or "",
        has_photo=bool(row.photo_path),
        status=row.status or "active",
        notes=row.notes or "",
        removed_at=row.removed_at,
        removed_by=row.removed_by,
        removal_remark=row.removal_remark,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _get_or_404(db, scholar_id: UUID) -> Scholar:
    row = await db.get(Scholar, scholar_id)
    if not row:
        raise HTTPException(404, "Scholar not found")
    return row


async def _lab_or_404(db, lab_id: UUID) -> Lab:
    lab = await db.get(Lab, lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    if lab.name.strip().lower() == "unassigned":
        raise HTTPException(400, "Cannot enrol into Unassigned")
    return lab


async def _clear_inv_assignment(db, row: Scholar) -> None:
    if row.inventory_item_id:
        item = await db.get(InventoryItem, row.inventory_item_id)
        if item and (item.assigned_to or "").strip() == (row.full_name or "").strip():
            item.assigned_to = ""


async def _apply_inventory_link(
    db,
    row: Scholar,
    *,
    system_required: bool,
    inventory_kind: str,
    inventory_item_id: UUID | None,
    inventory_label: str,
) -> None:
    await _clear_inv_assignment(db, row)

    kind = (inventory_kind or "none").strip().lower()
    if not system_required:
        row.system_required = False
        row.inventory_kind = "none"
        row.inventory_item_id = None
        row.inventory_label = ""
        return

    row.system_required = True
    if kind == "listed":
        if not inventory_item_id:
            raise HTTPException(400, "Select an inventory item from the list")
        item = await db.get(InventoryItem, inventory_item_id)
        if not item or item.status != "active":
            raise HTTPException(400, "Inventory item not found or removed")
        row.inventory_kind = "listed"
        row.inventory_item_id = item.id
        row.inventory_label = item.ic_no
        item.assigned_to = (row.full_name or "").strip()
    elif kind == "non_list":
        label = (inventory_label or "").strip()
        if not label:
            raise HTTPException(400, "Type a non-list inventory label / IC No.")
        row.inventory_kind = "non_list"
        row.inventory_item_id = None
        row.inventory_label = label
    else:
        raise HTTPException(400, "When system is required, choose listed inventory or non-list")


async def _resolve_import_inventory(db, label: str, system_required: bool) -> tuple[str, UUID | None, str]:
    """Return (kind, item_id, label)."""
    text = (label or "").strip()
    if not system_required:
        return "none", None, ""
    if not text:
        raise ValueError("System Required=Yes needs Inventory IC/Label")
    item = (
        await db.execute(
            select(InventoryItem).where(
                func.lower(InventoryItem.ic_no) == text.lower(),
                InventoryItem.status == "active",
            )
        )
    ).scalar_one_or_none()
    if item:
        return "listed", item.id, item.ic_no
    return "non_list", None, text


@router.get("/facets")
async def scholar_facets(
    db: DbDep,
    user: CurrentUser,
    lab_id: UUID | None = None,
    status: str = Query(default="active", pattern="^(active|removed|all)$"),
):
    group_q = select(Scholar.group_name).distinct()
    faculty_q = select(Scholar.faculty).distinct()
    if status != "all":
        group_q = group_q.where(Scholar.status == status)
        faculty_q = faculty_q.where(Scholar.status == status)
    if lab_id:
        group_q = group_q.where(Scholar.lab_id == lab_id)
        faculty_q = faculty_q.where(Scholar.lab_id == lab_id)
    groups = {g for (g,) in (await db.execute(group_q)).all() if (g or "").strip()}
    groups.update(DEFAULT_GROUPS)
    faculties = sorted({f for (f,) in (await db.execute(faculty_q)).all() if (f or "").strip()}, key=str.lower)
    return {
        "groups": sorted(groups, key=str.lower),
        "faculties": faculties,
    }


@router.get("/template.xlsx")
async def download_template_xlsx(user: CurrentUser):
    return Response(
        content=xls.build_template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="labwatch-scholars-template.xlsx"'},
    )


@router.get("/template.csv")
async def download_template_csv(user: CurrentUser):
    return Response(
        content=xls.build_template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="labwatch-scholars-template.csv"'},
    )


@router.get("/export.xlsx")
async def export_xlsx(
    db: DbDep,
    user: CurrentUser,
    status: str = Query(default="active", pattern="^(active|removed|all)$"),
    lab_id: UUID | None = None,
):
    stmt = (
        select(Scholar, Lab)
        .join(Lab, Scholar.lab_id == Lab.id)
        .order_by(Lab.name.asc(), Scholar.full_name.asc())
    )
    if status != "all":
        stmt = stmt.where(Scholar.status == status)
    if lab_id:
        stmt = stmt.where(Scholar.lab_id == lab_id)
    rows = [(s, lab.name) for s, lab in (await db.execute(stmt)).all()]
    return Response(
        content=xls.build_export_xlsx(rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="labwatch-scholars-{status}.xlsx"'},
    )


@router.post("/import")
async def import_scholars(
    db: DbDep,
    user: OperatorUser,
    request: Request,
    file: UploadFile = File(...),
):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    try:
        parsed_rows = xls.parse_import_bytes(raw, file.filename or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not parse file: {exc}") from exc

    labs = (await db.execute(select(Lab))).scalars().all()
    lab_by_name = { (l.name or "").strip().lower(): l for l in labs if (l.name or "").strip() }

    created = 0
    updated = 0
    errors: list[str] = []
    for parsed in parsed_rows:
        lab_key = parsed["lab_name"].lower()
        lab = lab_by_name.get(lab_key)
        if not lab or lab.name.strip().lower() == "unassigned":
            errors.append(f"{parsed['full_name']}: unknown lab '{parsed['lab_name']}'")
            continue
        try:
            kind, inv_id, inv_label = await _resolve_import_inventory(
                db, parsed.get("inventory_label") or "", bool(parsed.get("system_required"))
            )
            existing = None
            sid = (parsed.get("scholar_id") or "").strip()
            if sid:
                existing = (
                    await db.execute(
                        select(Scholar).where(
                            Scholar.lab_id == lab.id,
                            func.lower(Scholar.scholar_id) == sid.lower(),
                            Scholar.status == "active",
                        )
                    )
                ).scalar_one_or_none()
            if existing:
                existing.full_name = parsed["full_name"]
                existing.group_name = parsed.get("group_name") or ""
                existing.faculty = parsed.get("faculty") or ""
                existing.email = parsed.get("email") or ""
                existing.phone = parsed.get("phone") or ""
                existing.notes = parsed.get("notes") or ""
                await _apply_inventory_link(
                    db,
                    existing,
                    system_required=bool(parsed.get("system_required")),
                    inventory_kind=kind,
                    inventory_item_id=inv_id,
                    inventory_label=inv_label,
                )
                updated += 1
            else:
                row = Scholar(
                    lab_id=lab.id,
                    full_name=parsed["full_name"],
                    scholar_id=sid,
                    group_name=parsed.get("group_name") or "",
                    faculty=parsed.get("faculty") or "",
                    email=parsed.get("email") or "",
                    phone=parsed.get("phone") or "",
                    notes=parsed.get("notes") or "",
                    status="active",
                )
                await _apply_inventory_link(
                    db,
                    row,
                    system_required=bool(parsed.get("system_required")),
                    inventory_kind=kind,
                    inventory_item_id=inv_id,
                    inventory_label=inv_label,
                )
                db.add(row)
                created += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{parsed.get('full_name')}: {exc}")

    await write_audit(
        db,
        "scholar.import",
        user=user,
        details={"filename": file.filename, "created": created, "updated": updated, "errors": errors[:20]},
        request=request,
    )
    await db.commit()
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "errors": errors,
        "total_rows": len(parsed_rows),
    }


@router.post("/remove", response_model=dict)
async def remove_scholars(body: ScholarRemoveBody, db: DbDep, user: OperatorUser, request: Request):
    remark = body.remark.strip()
    if not remark:
        raise HTTPException(400, "Removal remark is required")
    removed = 0
    missing: list[str] = []
    now = utcnow()
    for sid in body.ids:
        row = await db.get(Scholar, sid)
        if not row:
            missing.append(str(sid))
            continue
        await _clear_inv_assignment(db, row)
        row.status = "removed"
        row.removed_at = now
        row.removed_by = user.username
        row.removal_remark = remark
        row.inventory_kind = "none"
        row.inventory_item_id = None
        row.inventory_label = ""
        row.system_required = False
        removed += 1
    await write_audit(
        db,
        "scholar.remove",
        user=user,
        details={"removed": removed, "missing": missing, "remark": remark},
        request=request,
    )
    await db.commit()
    return {"ok": True, "removed": removed, "missing": missing}


@router.post("/restore", response_model=dict)
async def restore_scholars(body: ScholarIdsBody, db: DbDep, user: OperatorUser, request: Request):
    restored = 0
    missing: list[str] = []
    skipped: list[str] = []
    for sid in body.ids:
        row = await db.get(Scholar, sid)
        if not row:
            missing.append(str(sid))
            continue
        if row.status != "removed":
            skipped.append(row.full_name or str(sid))
            continue
        row.status = "active"
        row.removed_at = None
        row.removed_by = None
        row.removal_remark = None
        restored += 1
    await write_audit(
        db,
        "scholar.restore",
        user=user,
        details={"restored": restored, "missing": missing, "skipped": skipped},
        request=request,
    )
    await db.commit()
    return {"ok": True, "restored": restored, "missing": missing, "skipped": skipped}


@router.post("/purge", response_model=dict)
async def purge_scholars(body: ScholarIdsBody, db: DbDep, user: OperatorUser, request: Request):
    deleted = 0
    missing: list[str] = []
    skipped: list[str] = []
    for sid in body.ids:
        row = await db.get(Scholar, sid)
        if not row:
            missing.append(str(sid))
            continue
        if row.status != "removed":
            skipped.append(row.full_name or str(sid))
            continue
        if row.photo_path:
            photos.delete_photo(row.photo_path)
        await db.delete(row)
        deleted += 1
    await write_audit(
        db,
        "scholar.purge",
        user=user,
        details={"deleted": deleted, "missing": missing, "skipped": skipped},
        request=request,
    )
    await db.commit()
    return {"ok": True, "deleted": deleted, "missing": missing, "skipped": skipped}


@router.post("/empty-removed", response_model=dict)
async def empty_removed_scholars(db: DbDep, user: OperatorUser, request: Request):
    rows = (await db.execute(select(Scholar).where(Scholar.status == "removed"))).scalars().all()
    for row in rows:
        if row.photo_path:
            photos.delete_photo(row.photo_path)
        await db.delete(row)
    deleted = len(rows)
    await write_audit(db, "scholar.empty_removed", user=user, details={"deleted": deleted}, request=request)
    await db.commit()
    return {"ok": True, "deleted": deleted}


@router.get("", response_model=ScholarListOut)
async def list_scholars(
    db: DbDep,
    user: CurrentUser,
    lab_id: UUID | None = None,
    q: str = "",
    status: str = Query(default="active", pattern="^(active|removed|all)$"),
    group_name: str = "",
    faculty: str = "",
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(Scholar, Lab, InventoryItem).join(Lab, Scholar.lab_id == Lab.id).outerjoin(
        InventoryItem, Scholar.inventory_item_id == InventoryItem.id
    )
    count_stmt = select(func.count()).select_from(Scholar)
    if status != "all":
        stmt = stmt.where(Scholar.status == status)
        count_stmt = count_stmt.where(Scholar.status == status)
    if lab_id:
        stmt = stmt.where(Scholar.lab_id == lab_id)
        count_stmt = count_stmt.where(Scholar.lab_id == lab_id)
    g = (group_name or "").strip()
    if g:
        stmt = stmt.where(func.lower(Scholar.group_name) == g.lower())
        count_stmt = count_stmt.where(func.lower(Scholar.group_name) == g.lower())
    f = (faculty or "").strip()
    if f:
        stmt = stmt.where(func.lower(Scholar.faculty) == f.lower())
        count_stmt = count_stmt.where(func.lower(Scholar.faculty) == f.lower())
    needle = (q or "").strip()
    if needle:
        like = f"%{needle}%"
        filt = or_(
            Scholar.full_name.ilike(like),
            Scholar.scholar_id.ilike(like),
            Scholar.group_name.ilike(like),
            Scholar.faculty.ilike(like),
            Scholar.email.ilike(like),
            Scholar.phone.ilike(like),
            Scholar.inventory_label.ilike(like),
            Lab.name.ilike(like),
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(
            or_(
                Scholar.full_name.ilike(like),
                Scholar.scholar_id.ilike(like),
                Scholar.group_name.ilike(like),
                Scholar.faculty.ilike(like),
                Scholar.email.ilike(like),
                Scholar.phone.ilike(like),
                Scholar.inventory_label.ilike(like),
            )
        )
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(Lab.name.asc(), Scholar.full_name.asc()).offset(offset).limit(limit)
        )
    ).all()
    return ScholarListOut(items=[_out(s, lab, inv) for s, lab, inv in rows], total=total)


@router.post("", response_model=ScholarOut)
async def enroll_scholar(
    db: DbDep,
    user: OperatorUser,
    request: Request,
    lab_id: UUID = Form(...),
    full_name: str = Form(...),
    scholar_id: str = Form(""),
    group_name: str = Form(""),
    faculty: str = Form(""),
    system_required: str = Form("false"),
    inventory_kind: str = Form("none"),
    inventory_item_id: str = Form(""),
    inventory_label: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
):
    lab = await _lab_or_404(db, lab_id)
    name = (full_name or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")
    sys_req = str(system_required).strip().lower() in {"1", "true", "yes", "y"}
    inv_id = None
    if (inventory_item_id or "").strip():
        try:
            inv_id = UUID(inventory_item_id.strip())
        except ValueError as exc:
            raise HTTPException(400, "Invalid inventory item id") from exc

    row = Scholar(
        lab_id=lab.id,
        full_name=name,
        scholar_id=(scholar_id or "").strip(),
        group_name=(group_name or "").strip(),
        faculty=(faculty or "").strip(),
        email=(email or "").strip(),
        phone=(phone or "").strip(),
        notes=(notes or "").strip(),
        status="active",
    )
    await _apply_inventory_link(
        db,
        row,
        system_required=sys_req,
        inventory_kind=(inventory_kind or "none").strip().lower(),
        inventory_item_id=inv_id,
        inventory_label=(inventory_label or "").strip(),
    )
    db.add(row)
    await db.flush()

    if photo and photo.filename:
        raw = await photo.read()
        if raw:
            try:
                row.photo_path = photos.save_photo(row.id, raw, photo.filename, photo.content_type)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

    await write_audit(
        db,
        "scholar.enroll",
        user=user,
        details={"id": str(row.id), "lab": lab.name, "name": name, "scholar_id": row.scholar_id},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    inv = await db.get(InventoryItem, row.inventory_item_id) if row.inventory_item_id else None
    return _out(row, lab, inv)


@router.get("/{scholar_id}", response_model=ScholarOut)
async def get_scholar(scholar_id: UUID, db: DbDep, user: CurrentUser):
    row = await _get_or_404(db, scholar_id)
    lab = await db.get(Lab, row.lab_id)
    inv = await db.get(InventoryItem, row.inventory_item_id) if row.inventory_item_id else None
    return _out(row, lab, inv)


@router.patch("/{scholar_id}", response_model=ScholarOut)
async def update_scholar(
    scholar_id: UUID,
    db: DbDep,
    user: OperatorUser,
    request: Request,
    payload: str = Form("{}"),
    photo: UploadFile | None = File(None),
):
    row = await _get_or_404(db, scholar_id)
    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid payload JSON") from exc

    if "lab_id" in data and data["lab_id"]:
        lab = await _lab_or_404(db, UUID(str(data["lab_id"])))
        row.lab_id = lab.id
    else:
        lab = await db.get(Lab, row.lab_id)

    for key in ("full_name", "scholar_id", "group_name", "faculty", "email", "phone", "notes"):
        if key in data and data[key] is not None:
            setattr(row, key, str(data[key]).strip())

    touch_inv = any(k in data for k in ("system_required", "inventory_kind", "inventory_item_id", "inventory_label"))
    if touch_inv or "system_required" in data:
        sys_req = bool(data["system_required"]) if "system_required" in data else bool(row.system_required)
        kind = str(data.get("inventory_kind", row.inventory_kind or "none"))
        inv_id = row.inventory_item_id
        if "inventory_item_id" in data:
            raw_id = data.get("inventory_item_id")
            inv_id = UUID(str(raw_id)) if raw_id else None
        label = str(data.get("inventory_label", row.inventory_label or ""))
        await _apply_inventory_link(
            db,
            row,
            system_required=sys_req,
            inventory_kind=kind,
            inventory_item_id=inv_id,
            inventory_label=label,
        )

    if photo and photo.filename:
        raw = await photo.read()
        if raw:
            try:
                if row.photo_path:
                    photos.delete_photo(row.photo_path)
                row.photo_path = photos.save_photo(row.id, raw, photo.filename, photo.content_type)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

    await write_audit(
        db,
        "scholar.update",
        user=user,
        details={"id": str(row.id), "fields": list(data.keys())},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    inv = await db.get(InventoryItem, row.inventory_item_id) if row.inventory_item_id else None
    return _out(row, lab, inv)


@router.get("/{scholar_id}/photo")
async def scholar_photo(scholar_id: UUID, db: DbDep, user: CurrentUser):
    row = await _get_or_404(db, scholar_id)
    path = photos.resolve_photo(row.photo_path)
    if not path:
        raise HTTPException(404, "No photo")
    media = "image/jpeg"
    if path.suffix.lower() == ".png":
        media = "image/png"
    elif path.suffix.lower() == ".webp":
        media = "image/webp"
    elif path.suffix.lower() == ".gif":
        media = "image/gif"
    return FileResponse(path, media_type=media)
