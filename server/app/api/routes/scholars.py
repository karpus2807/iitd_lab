from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbDep, OperatorUser, write_audit
from app.models import InventoryItem, Lab, Machine, Scholar, utcnow
from app.schemas.scholars import ScholarIdsBody, ScholarListOut, ScholarOut, ScholarRemoveBody
from app.services import email_otp
from app.services import inv_verify_docs as inv_docs
from app.services import scholar_mgmt as xls
from app.services import scholar_photos as photos

router = APIRouter(prefix="/api/scholars", tags=["scholars"])

DEFAULT_GROUPS = ["M.Tech", "Ph.D.", "Postdoc", "Project Staff", "Intern", "Faculty", "Other"]


def _truthy(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


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
        bio_id=getattr(row, "bio_id", None) or "",
        group_name=row.group_name or "",
        faculty=row.faculty or "",
        system_required=bool(row.system_required),
        approved=bool(getattr(row, "approved", False)),
        approved_at=getattr(row, "approved_at", None),
        no_dues=bool(getattr(row, "no_dues", False)),
        no_dues_at=getattr(row, "no_dues_at", None),
        inventory_kind=row.inventory_kind or "none",
        inventory_item_id=row.inventory_item_id,
        inventory_label=row.inventory_label or "",
        inventory_item_name=(inv_obj.item_name if inv_obj else "") or "",
        inventory_assigned_at=getattr(row, "inventory_assigned_at", None),
        email=row.email or "",
        phone=row.phone or "",
        has_photo=bool(row.photo_path),
        has_inv_verify_doc=bool(getattr(row, "inv_verify_doc_path", None) or ""),
        status=row.status or "active",
        notes=row.notes or "",
        removed_at=row.removed_at,
        removed_by=row.removed_by,
        removal_remark=row.removal_remark,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _assert_unique_scholar_id(db, scholar_id: str, *, exclude_id: UUID | None = None) -> None:
    sid = (scholar_id or "").strip()
    if not sid:
        return
    stmt = select(Scholar).where(
        func.lower(Scholar.scholar_id) == sid.lower(),
        Scholar.status.in_(["active", "pending"]),
    )
    if exclude_id:
        stmt = stmt.where(Scholar.id != exclude_id)
    clash = (await db.execute(stmt)).scalar_one_or_none()
    if clash:
        raise HTTPException(400, f"ID '{sid}' is already used school-wide (must be unique)")


async def _assert_unique_bio_id(
    db, lab_id: UUID, bio_id: str, *, exclude_id: UUID | None = None
) -> None:
    bid = (bio_id or "").strip()
    if not bid:
        return
    stmt = select(Scholar).where(
        Scholar.lab_id == lab_id,
        func.lower(Scholar.bio_id) == bid.lower(),
        Scholar.status.in_(["active", "pending"]),
    )
    if exclude_id:
        stmt = stmt.where(Scholar.id != exclude_id)
    clash = (await db.execute(stmt)).scalar_one_or_none()
    if clash:
        raise HTTPException(400, f"Bio-ID '{bid}' is already used in this lab")


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
        row.inventory_assigned_at = None
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
        row.inventory_assigned_at = utcnow()
        item.assigned_to = (row.full_name or "").strip()
    elif kind == "non_list":
        label = (inventory_label or "").strip()
        if not label:
            raise HTTPException(400, "Type a non-list inventory label / IC No.")
        row.inventory_kind = "non_list"
        row.inventory_item_id = None
        row.inventory_label = label
        row.inventory_assigned_at = utcnow()
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


@router.get("/dashboard")
async def scholars_dashboard(db: DbDep, user: CurrentUser):
    """Per-lab scholar counts + inventory/machine summary (fleet view)."""
    labs = (
        await db.execute(
            select(Lab).where(func.lower(Lab.name) != "unassigned").order_by(Lab.name.asc())
        )
    ).scalars().all()

    active = Scholar.status == "active"
    total = (await db.execute(select(func.count()).select_from(Scholar).where(active))).scalar_one()
    approved = (
        await db.execute(
            select(func.count()).select_from(Scholar).where(active, Scholar.approved.is_(True), Scholar.no_dues.is_(False))
        )
    ).scalar_one()
    pending = (
        await db.execute(
            select(func.count())
            .select_from(Scholar)
            .where(active, Scholar.approved.is_(False), Scholar.no_dues.is_(False))
        )
    ).scalar_one()
    no_dues = (
        await db.execute(select(func.count()).select_from(Scholar).where(active, Scholar.no_dues.is_(True)))
    ).scalar_one()
    with_inv = (
        await db.execute(
            select(func.count())
            .select_from(Scholar)
            .where(active, Scholar.inventory_kind.in_(["listed", "non_list"]))
        )
    ).scalar_one()
    machines_total = (await db.execute(select(func.count()).select_from(Machine))).scalar_one()

    lab_rows = []
    for lab in labs:
        base = [active, Scholar.lab_id == lab.id]
        s_count = (
            await db.execute(select(func.count()).select_from(Scholar).where(*base))
        ).scalar_one()
        s_approved = (
            await db.execute(
                select(func.count())
                .select_from(Scholar)
                .where(*base, Scholar.approved.is_(True), Scholar.no_dues.is_(False))
            )
        ).scalar_one()
        s_pending = (
            await db.execute(
                select(func.count())
                .select_from(Scholar)
                .where(*base, Scholar.approved.is_(False), Scholar.no_dues.is_(False))
            )
        ).scalar_one()
        s_no_dues = (
            await db.execute(
                select(func.count()).select_from(Scholar).where(*base, Scholar.no_dues.is_(True))
            )
        ).scalar_one()
        s_inv = (
            await db.execute(
                select(func.count())
                .select_from(Scholar)
                .where(*base, Scholar.inventory_kind.in_(["listed", "non_list"]))
            )
        ).scalar_one()
        m_count = (
            await db.execute(select(func.count()).select_from(Machine).where(Machine.lab_id == lab.id))
        ).scalar_one()
        lab_rows.append(
            {
                "id": str(lab.id),
                "name": lab.name,
                "room": lab.room or "",
                "building": getattr(lab, "building", None) or "",
                "scholars": s_count,
                "approved": s_approved,
                "pending": s_pending,
                "no_dues": s_no_dues,
                "with_inventory": s_inv,
                "machines": m_count,
            }
        )

    return {
        "scholars": total,
        "approved": approved,
        "pending": pending,
        "no_dues": no_dues,
        "with_inventory": with_inv,
        "machines": machines_total,
        "labs": lab_rows,
    }


@router.get("/dashboard/{lab_id}")
async def scholars_dashboard_lab(lab_id: UUID, db: DbDep, user: CurrentUser):
    """Scholars in one lab with assigned inventory details and dates."""
    lab = await db.get(Lab, lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    rows = (
        await db.execute(
            select(Scholar, InventoryItem)
            .outerjoin(InventoryItem, Scholar.inventory_item_id == InventoryItem.id)
            .where(Scholar.lab_id == lab.id, Scholar.status == "active")
            .order_by(Scholar.full_name.asc())
        )
    ).all()
    machines = (
        await db.execute(select(func.count()).select_from(Machine).where(Machine.lab_id == lab.id))
    ).scalar_one()
    items = []
    for row, inv in rows:
        out = _out(row, lab, inv)
        items.append(
            {
                **out.model_dump(mode="json"),
                "inventory": (
                    {
                        "id": str(inv.id),
                        "ic_no": inv.ic_no,
                        "item_name": inv.item_name or "",
                        "inventory_type": inv.inventory_type or "",
                        "inventory_location": inv.inventory_location or "",
                        "assigned_to": inv.assigned_to or "",
                    }
                    if inv
                    else (
                        {
                            "id": None,
                            "ic_no": row.inventory_label or "",
                            "item_name": "",
                            "inventory_type": "non_list",
                            "inventory_location": "",
                            "assigned_to": row.full_name or "",
                        }
                        if (row.inventory_kind or "") == "non_list"
                        else None
                    )
                ),
            }
        )
    return {
        "lab": {
            "id": str(lab.id),
            "name": lab.name,
            "room": lab.room or "",
            "building": getattr(lab, "building", None) or "",
        },
        "machines": machines,
        "scholars": items,
        "counts": {
            "scholars": len(items),
            "approved": sum(1 for s in items if s.get("approved") and not s.get("no_dues")),
            "pending": sum(1 for s in items if not s.get("approved") and not s.get("no_dues")),
            "no_dues": sum(1 for s in items if s.get("no_dues")),
            "with_inventory": sum(1 for s in items if s.get("inventory_kind") in {"listed", "non_list"}),
        },
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
    """Import scholars from Excel/CSV. No OTP — OTP is only for manual portal enrolment."""
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
    lab_by_name = {(l.name or "").strip().lower(): l for l in labs if (l.name or "").strip()}

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
            email = (parsed.get("email") or "").strip()
            sid = (parsed.get("scholar_id") or "").strip()
            bio = (parsed.get("bio_id") or "").strip()
            no_dues = bool(parsed.get("no_dues"))

            existing = None
            if sid:
                existing = (
                    await db.execute(
                        select(Scholar).where(
                            func.lower(Scholar.scholar_id) == sid.lower(),
                            Scholar.status.in_(["active", "pending"]),
                        )
                    )
                ).scalar_one_or_none()

            if existing:
                await _assert_unique_bio_id(db, lab.id, bio, exclude_id=existing.id)
                existing.lab_id = lab.id
                existing.full_name = parsed["full_name"]
                existing.bio_id = bio
                existing.group_name = parsed.get("group_name") or ""
                existing.faculty = parsed.get("faculty") or ""
                existing.email = email
                existing.phone = parsed.get("phone") or ""
                existing.notes = parsed.get("notes") or ""
                existing.status = "active"
                existing.approved = True
                if not existing.approved_at:
                    existing.approved_at = utcnow()
                existing.no_dues = no_dues
                existing.no_dues_at = utcnow() if no_dues else None
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
                await _assert_unique_scholar_id(db, sid)
                await _assert_unique_bio_id(db, lab.id, bio)
                row = Scholar(
                    lab_id=lab.id,
                    full_name=parsed["full_name"],
                    scholar_id=sid,
                    bio_id=bio,
                    group_name=parsed.get("group_name") or "",
                    faculty=parsed.get("faculty") or "",
                    email=email,
                    phone=parsed.get("phone") or "",
                    notes=parsed.get("notes") or "",
                    status="active",
                    approved=True,
                    approved_at=utcnow(),
                    no_dues=no_dues,
                    no_dues_at=utcnow() if no_dues else None,
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
        except HTTPException as exc:
            errors.append(f"{parsed.get('full_name')}: {exc.detail}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{parsed.get('full_name')}: {exc}")

    await write_audit(
        db,
        "scholar.import",
        user=user,
        details={
            "filename": file.filename,
            "created": created,
            "updated": updated,
            "errors": errors[:20],
        },
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
        if getattr(row, "inv_verify_doc_path", None):
            inv_docs.delete_doc(row.inv_verify_doc_path)
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
        if getattr(row, "inv_verify_doc_path", None):
            inv_docs.delete_doc(row.inv_verify_doc_path)
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
    status: str = Query(default="active", pattern="^(active|removed|pending|all)$"),
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
            Scholar.bio_id.ilike(like),
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
                Scholar.bio_id.ilike(like),
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


async def _finalize_enroll_payload(db, payload: dict, *, photo_path: str = "") -> Scholar:
    lab = await _lab_or_404(db, UUID(str(payload["lab_id"])))
    inv_raw = str(payload.get("inventory_item_id") or "").strip()
    inv_id = UUID(inv_raw) if inv_raw else None
    sid = str(payload.get("scholar_id") or "").strip()
    bio = str(payload.get("bio_id") or "").strip()
    # Portal enrol creates a new row — school-wide ID must not already exist.
    # Use Edit / Import to update an existing scholar.
    await _assert_unique_scholar_id(db, sid)
    await _assert_unique_bio_id(db, lab.id, bio)
    row = Scholar(
        lab_id=lab.id,
        full_name=str(payload.get("full_name") or "").strip(),
        scholar_id=sid,
        bio_id=bio,
        group_name=str(payload.get("group_name") or "").strip(),
        faculty=str(payload.get("faculty") or "").strip(),
        email=str(payload.get("email") or "").strip(),
        phone=str(payload.get("phone") or "").strip(),
        notes=str(payload.get("notes") or "").strip(),
        status="active",
        approved=False,
        no_dues=False,
        photo_path=photo_path or str(payload.get("photo_path") or ""),
    )
    db.add(row)
    await _apply_inventory_link(
        db,
        row,
        system_required=bool(payload.get("system_required")),
        inventory_kind=str(payload.get("inventory_kind") or "none"),
        inventory_item_id=inv_id,
        inventory_label=str(payload.get("inventory_label") or ""),
    )
    await db.flush()
    return row


@router.post("")
async def enroll_scholar(
    db: DbDep,
    user: OperatorUser,
    request: Request,
    lab_id: UUID = Form(...),
    full_name: str = Form(...),
    scholar_id: str = Form(""),
    bio_id: str = Form(""),
    group_name: str = Form(""),
    faculty: str = Form(""),
    system_required: str = Form("false"),
    inventory_kind: str = Form("none"),
    inventory_item_id: str = Form(""),
    inventory_label: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    require_otp: str = Form("false"),
    verify_method: str = Form("otp"),
    photo: UploadFile | None = File(None),
    document: UploadFile | None = File(None),
):
    """Enrol a scholar via the portal (manual).

    - Plain enrol: OTP optional (require_otp).
    - Inventory assign: verification required — primary OTP, or secondary PDF document.
    - Import path has no OTP; only this portal enrolment uses OTP/PDF verify.
    - New portal enrolments start unapproved until Approve is clicked.
    """
    lab = await _lab_or_404(db, lab_id)
    name = (full_name or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")
    sys_req = _truthy(system_required)
    kind = (inventory_kind or "none").strip().lower()
    inv_id = None
    if (inventory_item_id or "").strip():
        try:
            inv_id = UUID(inventory_item_id.strip())
        except ValueError as exc:
            raise HTTPException(400, "Invalid inventory item id") from exc
    if sys_req and kind not in {"listed", "non_list"}:
        raise HTTPException(400, "System required needs listed or non-list inventory")

    assigning_inv = bool(sys_req and kind in {"listed", "non_list"})
    method = (verify_method or "otp").strip().lower()
    if method not in {"otp", "document"}:
        raise HTTPException(400, "verify_method must be otp or document")
    if assigning_inv and method == "document":
        want_otp = False
        want_doc = True
    elif assigning_inv:
        want_otp = True
        want_doc = False
    else:
        want_otp = _truthy(require_otp)
        want_doc = False
    email_norm = (email or "").strip()

    payload = {
        "lab_id": str(lab.id),
        "full_name": name,
        "scholar_id": (scholar_id or "").strip(),
        "bio_id": (bio_id or "").strip(),
        "group_name": (group_name or "").strip(),
        "faculty": (faculty or "").strip(),
        "email": email_norm,
        "phone": (phone or "").strip(),
        "notes": (notes or "").strip(),
        "system_required": sys_req,
        "inventory_kind": kind if sys_req else "none",
        "inventory_item_id": str(inv_id) if inv_id else "",
        "inventory_label": (inventory_label or "").strip(),
    }

    if assigning_inv:
        if kind == "listed":
            if not inv_id:
                raise HTTPException(400, "Select an inventory item from the list")
            item = await db.get(InventoryItem, inv_id)
            if not item or item.status != "active":
                raise HTTPException(400, "Inventory item not found or removed")
            payload["inventory_label"] = item.ic_no
        elif kind == "non_list" and not (inventory_label or "").strip():
            raise HTTPException(400, "Type a non-list inventory label / IC No.")

    if want_otp:
        if not email_norm:
            raise HTTPException(400, "Email is required for OTP verification")

        await email_otp.expire_open_for_email(db, email_otp.PURPOSE_ENROLL, email_norm)
        challenge, code = await email_otp.create_challenge(
            db,
            purpose=email_otp.PURPOSE_ENROLL,
            email=email_norm,
            payload=payload,
            created_by=user.username,
        )
        if photo and photo.filename:
            raw = await photo.read()
            if raw:
                try:
                    payload["photo_path"] = photos.save_photo(
                        challenge.id, raw, photo.filename, photo.content_type
                    )
                    from sqlalchemy.orm.attributes import flag_modified

                    challenge.payload = dict(payload)
                    flag_modified(challenge, "payload")
                except ValueError as exc:
                    raise HTTPException(400, str(exc)) from exc
        try:
            ctx = "inventory assign" if assigning_inv else "scholar enrolment"
            await email_otp.send_otp_mail(db, to=email_norm, code=code, context=f"{ctx} · {name}")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Could not send OTP email: {exc}") from exc
        await write_audit(
            db,
            "scholar.enroll_otp_sent",
            user=user,
            details={"challenge_id": str(challenge.id), "email": email_norm, "assigning_inv": assigning_inv},
            request=request,
        )
        await db.commit()
        return {
            "pending_otp": True,
            "challenge_id": str(challenge.id),
            "email": email_norm,
            "purpose": email_otp.PURPOSE_ENROLL,
            "assigning_inventory": assigning_inv,
            "verify_method": "otp",
            "message": f"OTP sent to {email_norm}. Enrolment completes after verification.",
        }

    if want_doc:
        if not document or not document.filename:
            raise HTTPException(400, "Upload a PDF verification document for inventory assign")
        doc_raw = await document.read()

    row = await _finalize_enroll_payload(db, payload)
    if photo and photo.filename:
        raw = await photo.read()
        if raw:
            try:
                row.photo_path = photos.save_photo(row.id, raw, photo.filename, photo.content_type)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
    if want_doc:
        try:
            row.inv_verify_doc_path = inv_docs.save_doc(
                row.id, doc_raw, document.filename, document.content_type
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    await write_audit(
        db,
        "scholar.enroll" if not want_doc else "scholar.enroll_doc_verified",
        user=user,
        details={
            "id": str(row.id),
            "lab": lab.name,
            "name": name,
            "scholar_id": row.scholar_id,
            "verify_method": "document" if want_doc else "none",
        },
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    inv = await db.get(InventoryItem, row.inventory_item_id) if row.inventory_item_id else None
    return _out(row, lab, inv)


@router.post("/verify-otp")
async def verify_scholar_otp(
    db: DbDep,
    user: OperatorUser,
    request: Request,
    challenge_id: UUID = Form(...),
    code: str = Form(...),
):
    try:
        challenge = await email_otp.verify_challenge(db, challenge_id=challenge_id, code=code)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    payload = dict(challenge.payload or {})
    if challenge.purpose == email_otp.PURPOSE_ENROLL:
        row = await _finalize_enroll_payload(db, payload)
        # photo may already be stored under challenge id
        if payload.get("photo_path") and not row.photo_path:
            row.photo_path = str(payload["photo_path"])
        await write_audit(
            db,
            "scholar.enroll_verified",
            user=user,
            details={"id": str(row.id), "challenge_id": str(challenge.id)},
            request=request,
        )
        await db.commit()
        await db.refresh(row)
        lab = await db.get(Lab, row.lab_id)
        inv = await db.get(InventoryItem, row.inventory_item_id) if row.inventory_item_id else None
        return {"ok": True, "purpose": challenge.purpose, "scholar": _out(row, lab, inv)}

    if challenge.purpose == email_otp.PURPOSE_IMPORT:
        row = await _finalize_enroll_payload(db, payload)
        await write_audit(
            db,
            "scholar.import_verified",
            user=user,
            details={"id": str(row.id), "challenge_id": str(challenge.id)},
            request=request,
        )
        await db.commit()
        await db.refresh(row)
        lab = await db.get(Lab, row.lab_id)
        inv = await db.get(InventoryItem, row.inventory_item_id) if row.inventory_item_id else None
        return {"ok": True, "purpose": challenge.purpose, "scholar": _out(row, lab, inv)}

    if challenge.purpose == email_otp.PURPOSE_INV_ASSIGN:
        scholar_id = UUID(str(payload["scholar_id"]))
        row = await _get_or_404(db, scholar_id)
        inv_raw = str(payload.get("inventory_item_id") or "").strip()
        inv_id = UUID(inv_raw) if inv_raw else None
        await _apply_inventory_link(
            db,
            row,
            system_required=True,
            inventory_kind=str(payload.get("inventory_kind") or "non_list"),
            inventory_item_id=inv_id,
            inventory_label=str(payload.get("inventory_label") or ""),
        )
        await write_audit(
            db,
            "scholar.inv_assign_verified",
            user=user,
            details={"id": str(row.id), "challenge_id": str(challenge.id)},
            request=request,
        )
        await db.commit()
        await db.refresh(row)
        lab = await db.get(Lab, row.lab_id)
        inv = await db.get(InventoryItem, row.inventory_item_id) if row.inventory_item_id else None
        return {"ok": True, "purpose": challenge.purpose, "scholar": _out(row, lab, inv)}

    raise HTTPException(400, f"Unsupported OTP purpose: {challenge.purpose}")


@router.post("/{scholar_id}/assign-inventory")
async def assign_inventory_with_verification(
    scholar_id: UUID,
    db: DbDep,
    user: OperatorUser,
    request: Request,
    inventory_kind: str = Form(...),
    inventory_item_id: str = Form(""),
    inventory_label: str = Form(""),
    verify_method: str = Form("otp"),
    document: UploadFile | None = File(None),
):
    """Assign inventory with verification.

    Primary: email OTP. Secondary: upload a PDF proof (faculty mail attachment, etc.).
    """
    row = await _get_or_404(db, scholar_id)
    if row.status == "removed":
        raise HTTPException(400, "Cannot assign inventory to a removed scholar")
    method = (verify_method or "otp").strip().lower()
    if method not in {"otp", "document"}:
        raise HTTPException(400, "verify_method must be otp or document")
    kind = (inventory_kind or "").strip().lower()
    if kind not in {"listed", "non_list"}:
        raise HTTPException(400, "inventory_kind must be listed or non_list")
    inv_id = None
    if (inventory_item_id or "").strip():
        try:
            inv_id = UUID(inventory_item_id.strip())
        except ValueError as exc:
            raise HTTPException(400, "Invalid inventory item id") from exc
    label = (inventory_label or "").strip()
    if kind == "listed":
        if not inv_id:
            raise HTTPException(400, "Select an inventory item from the list")
        item = await db.get(InventoryItem, inv_id)
        if not item or item.status != "active":
            raise HTTPException(400, "Inventory item not found or removed")
        label = item.ic_no
    elif not label:
        raise HTTPException(400, "Type a non-list inventory label / IC No.")

    if method == "document":
        if not document or not document.filename:
            raise HTTPException(400, "Upload a PDF verification document")
        raw = await document.read()
        try:
            doc_rel = inv_docs.save_doc(row.id, raw, document.filename, document.content_type)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        await _apply_inventory_link(
            db,
            row,
            system_required=True,
            inventory_kind=kind,
            inventory_item_id=inv_id,
            inventory_label=label,
        )
        row.inv_verify_doc_path = doc_rel
        await write_audit(
            db,
            "scholar.inv_assign_doc_verified",
            user=user,
            details={"scholar_id": str(row.id), "doc": doc_rel, "inventory_kind": kind, "label": label},
            request=request,
        )
        await db.commit()
        await db.refresh(row)
        lab = await db.get(Lab, row.lab_id)
        inv = await db.get(InventoryItem, row.inventory_item_id) if row.inventory_item_id else None
        return {
            "ok": True,
            "pending_otp": False,
            "verify_method": "document",
            "scholar": _out(row, lab, inv),
            "message": "Inventory assigned — verified via uploaded PDF.",
        }

    email_norm = (row.email or "").strip()
    if not email_norm:
        raise HTTPException(
            400,
            "Scholar email is required for OTP — or choose document verify and upload a PDF",
        )
    payload = {
        "scholar_id": str(row.id),
        "inventory_kind": kind,
        "inventory_item_id": str(inv_id) if inv_id else "",
        "inventory_label": label,
    }
    await email_otp.expire_open_for_email(db, email_otp.PURPOSE_INV_ASSIGN, email_norm)
    challenge, code = await email_otp.create_challenge(
        db,
        purpose=email_otp.PURPOSE_INV_ASSIGN,
        email=email_norm,
        payload=payload,
        created_by=user.username,
    )
    try:
        await email_otp.send_otp_mail(
            db, to=email_norm, code=code, context=f"inventory assign · {row.full_name}"
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not send OTP email: {exc}") from exc
    await write_audit(
        db,
        "scholar.inv_assign_otp_sent",
        user=user,
        details={"scholar_id": str(row.id), "challenge_id": str(challenge.id)},
        request=request,
    )
    await db.commit()
    return {
        "pending_otp": True,
        "challenge_id": str(challenge.id),
        "email": email_norm,
        "purpose": email_otp.PURPOSE_INV_ASSIGN,
        "verify_method": "otp",
        "message": f"OTP sent to {email_norm}. Inventory assigns after verification.",
    }


@router.get("/{scholar_id}/inv-verify-doc")
async def scholar_inv_verify_doc(scholar_id: UUID, db: DbDep, user: CurrentUser):
    row = await _get_or_404(db, scholar_id)
    path = inv_docs.resolve_doc(getattr(row, "inv_verify_doc_path", "") or "")
    if not path:
        raise HTTPException(404, "No inventory verification document")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"inv-verify-{row.scholar_id or row.id}.pdf",
    )


@router.post("/{scholar_id}/approve", response_model=ScholarOut)
async def approve_scholar(scholar_id: UUID, db: DbDep, user: OperatorUser, request: Request):
    """Mark scholar active in lab (green)."""
    row = await _get_or_404(db, scholar_id)
    if row.status == "removed":
        raise HTTPException(400, "Cannot approve a removed scholar — restore first")
    row.approved = True
    row.approved_at = utcnow()
    await write_audit(
        db,
        "scholar.approve",
        user=user,
        details={"id": str(row.id), "name": row.full_name},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    lab = await db.get(Lab, row.lab_id)
    inv = await db.get(InventoryItem, row.inventory_item_id) if row.inventory_item_id else None
    return _out(row, lab, inv)


@router.post("/{scholar_id}/no-dues", response_model=ScholarOut)
async def set_scholar_no_dues(
    scholar_id: UUID,
    db: DbDep,
    user: OperatorUser,
    request: Request,
    no_dues: str = Form("true"),
):
    """Mark no-dues signed (red) or revoke no-dues (clear red)."""
    row = await _get_or_404(db, scholar_id)
    if row.status == "removed":
        raise HTTPException(400, "Cannot change no-dues on a removed scholar")
    flag = _truthy(no_dues)
    row.no_dues = flag
    row.no_dues_at = utcnow() if flag else None
    await write_audit(
        db,
        "scholar.no_dues" if flag else "scholar.no_dues_revoked",
        user=user,
        details={"id": str(row.id), "no_dues": flag},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    lab = await db.get(Lab, row.lab_id)
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

    if "scholar_id" in data and data["scholar_id"] is not None:
        new_sid = str(data["scholar_id"]).strip()
        await _assert_unique_scholar_id(db, new_sid, exclude_id=row.id)
        row.scholar_id = new_sid
    if "bio_id" in data and data["bio_id"] is not None:
        new_bio = str(data["bio_id"]).strip()
        await _assert_unique_bio_id(db, row.lab_id, new_bio, exclude_id=row.id)
        row.bio_id = new_bio

    for key in ("full_name", "group_name", "faculty", "email", "phone", "notes"):
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
