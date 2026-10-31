from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import and_, func, or_, select

from app.api.deps import CurrentUser, DbDep, OperatorUser, write_audit
from app.models import InventoryItem, Lab, Machine, Scholar, utcnow
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
from app.services import email_otp
from app.services import inv_assign
from app.services import inv_mgmt as svc

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


def _truthy(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _out(
    row: InventoryItem,
    *,
    machine: Machine | None = None,
    lab_name: str | None = None,
) -> InventoryItemOut:
    base = InventoryItemOut.model_validate(row)
    registered = machine is not None
    lab = (lab_name or "").strip() or None
    if lab and lab.lower() == "unassigned":
        lab = None
    # Template location wins; else show registered machine's lab name.
    location = (base.inventory_location or "").strip()
    if not location and lab:
        location = lab
    # Template type wins; registered lab hosts default to Lab when blank.
    inv_type_col = (base.inventory_type or "").strip()
    if not inv_type_col and registered:
        inv_type_col = "Lab"
    return base.model_copy(
        update={
            "inventory_location": location,
            "inventory_type": inv_type_col,
            "registered": registered,
            "assigned": svc.is_assigned_item(row),
            "machine_id": machine.id if machine else None,
            "machine_hostname": (machine.hostname or machine.display_name or None) if machine else None,
            "machine_lab_name": lab,
            "assigned_scholar_id": getattr(row, "assigned_scholar_id", None),
            "assigned_at": getattr(row, "assigned_at", None),
            "assigned_by": getattr(row, "assigned_by", None) or "",
            "assign_verify_method": getattr(row, "assign_verify_method", None) or "",
            "has_assign_verify_doc": bool(getattr(row, "assign_verify_doc_path", None) or ""),
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


async def _machines_by_ic(db, ic_nos: list[str]) -> dict[str, tuple[Machine, str | None]]:
    """Map lower(ic_no) → (Machine, lab_name) where machines.inventory_id matches."""
    needles = sorted({(ic or "").strip().lower() for ic in ic_nos if (ic or "").strip()})
    if not needles:
        return {}
    rows = (
        await db.execute(
            select(Machine, Lab.name)
            .outerjoin(Lab, Machine.lab_id == Lab.id)
            .where(func.lower(Machine.inventory_id).in_(needles))
        )
    ).all()
    out: dict[str, tuple[Machine, str | None]] = {}
    for m, lab_name in rows:
        key = (m.inventory_id or "").strip().lower()
        if key and key not in out:
            name = (lab_name or "").strip()
            out[key] = (m, name or None)
    return out


def _link_out(row: InventoryItem, links: dict[str, tuple[Machine, str | None]]) -> InventoryItemOut:
    link = links.get((row.ic_no or "").strip().lower())
    if not link:
        return _out(row)
    machine, lab_name = link
    return _out(row, machine=machine, lab_name=lab_name)


def _apply_inventory_filters(
    stmt,
    count_stmt,
    *,
    q: str,
    inventory_type: str,
    inventory_location: str,
    inv_type: str,
    link: str,
):
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

    type_f = (inventory_type or "").strip()
    if type_f:
        if type_f.lower() == "__blank__":
            blank_type = or_(InventoryItem.inventory_type == "", InventoryItem.inventory_type.is_(None))
            registered_exists = (
                select(Machine.id)
                .where(func.lower(Machine.inventory_id) == func.lower(InventoryItem.ic_no))
                .exists()
            )
            # blank stored type, and not showing as Lab via registration
            filt_blank = and_(blank_type, ~registered_exists)
            stmt = stmt.where(filt_blank)
            count_stmt = count_stmt.where(filt_blank)
        else:
            stored_type = func.lower(InventoryItem.inventory_type) == type_f.lower()
            # Display fallback: blank type + registered machine → shown as "Lab"
            if type_f.lower() == "lab":
                blank_registered = and_(
                    or_(InventoryItem.inventory_type == "", InventoryItem.inventory_type.is_(None)),
                    (
                        select(Machine.id)
                        .where(func.lower(Machine.inventory_id) == func.lower(InventoryItem.ic_no))
                        .exists()
                    ),
                )
                filt_type = or_(stored_type, blank_registered)
            else:
                filt_type = stored_type
            stmt = stmt.where(filt_type)
            count_stmt = count_stmt.where(filt_type)

    inv_type_f = (inv_type or "").strip()
    if inv_type_f:
        if inv_type_f.lower() == "__blank__":
            blank_inv = or_(InventoryItem.inv_type == "", InventoryItem.inv_type.is_(None))
            stmt = stmt.where(blank_inv)
            count_stmt = count_stmt.where(blank_inv)
        else:
            stmt = stmt.where(func.lower(InventoryItem.inv_type) == inv_type_f.lower())
            count_stmt = count_stmt.where(func.lower(InventoryItem.inv_type) == inv_type_f.lower())

    loc_f = (inventory_location or "").strip()
    if loc_f:
        if loc_f.lower() == "__blank__":
            blank_loc = or_(InventoryItem.inventory_location == "", InventoryItem.inventory_location.is_(None))
            # blank stored location AND no non-Unassigned machine lab
            has_lab = (
                select(Machine.id)
                .outerjoin(Lab, Machine.lab_id == Lab.id)
                .where(
                    func.lower(Machine.inventory_id) == func.lower(InventoryItem.ic_no),
                    Lab.name.is_not(None),
                    func.lower(Lab.name) != "unassigned",
                )
                .exists()
            )
            filt_blank = and_(blank_loc, ~has_lab)
            stmt = stmt.where(filt_blank)
            count_stmt = count_stmt.where(filt_blank)
        else:
            stored = func.lower(InventoryItem.inventory_location) == loc_f.lower()
            via_lab = and_(
                or_(InventoryItem.inventory_location == "", InventoryItem.inventory_location.is_(None)),
                (
                    select(Machine.id)
                    .join(Lab, Machine.lab_id == Lab.id)
                    .where(
                        func.lower(Machine.inventory_id) == func.lower(InventoryItem.ic_no),
                        func.lower(Lab.name) == loc_f.lower(),
                    )
                    .exists()
                ),
            )
            filt_loc = or_(stored, via_lab)
            stmt = stmt.where(filt_loc)
            count_stmt = count_stmt.where(filt_loc)

    link_f = (link or "").strip().lower()
    if link_f and link_f != "any":
        registered_exists = (
            select(Machine.id)
            .where(func.lower(Machine.inventory_id) == func.lower(InventoryItem.ic_no))
            .exists()
        )
        assigned_expr = or_(
            and_(InventoryItem.assigned_to.is_not(None), InventoryItem.assigned_to != ""),
            func.lower(InventoryItem.inventory_type) == "personal",
        )
        if link_f == "registered":
            stmt = stmt.where(registered_exists)
            count_stmt = count_stmt.where(registered_exists)
        elif link_f == "assigned":
            stmt = stmt.where(assigned_expr)
            count_stmt = count_stmt.where(assigned_expr)
        elif link_f == "unlinked":
            stmt = stmt.where(~registered_exists)
            count_stmt = count_stmt.where(~registered_exists)
        elif link_f == "registered_assigned":
            stmt = stmt.where(and_(registered_exists, assigned_expr))
            count_stmt = count_stmt.where(and_(registered_exists, assigned_expr))

    return stmt, count_stmt


@router.get("/facets")
async def inventory_facets(
    db: DbDep,
    user: CurrentUser,
    status: str = Query(default="active", pattern="^(active|removed|all)$"),
):
    """Distinct filter values for the current Active/Removed tab."""
    type_stmt = select(InventoryItem.inventory_type).distinct().order_by(InventoryItem.inventory_type)
    loc_stmt = select(InventoryItem.inventory_location).distinct().order_by(InventoryItem.inventory_location)
    inv_stmt = select(InventoryItem.inv_type).distinct().order_by(InventoryItem.inv_type)
    if status != "all":
        type_stmt = type_stmt.where(InventoryItem.status == status)
        loc_stmt = loc_stmt.where(InventoryItem.status == status)
        inv_stmt = inv_stmt.where(InventoryItem.status == status)

    types = [r for (r,) in (await db.execute(type_stmt)).all() if (r or "").strip()]
    locations = {r for (r,) in (await db.execute(loc_stmt)).all() if (r or "").strip()}
    inv_types = [r for (r,) in (await db.execute(inv_stmt)).all() if (r or "").strip()]

    # Include lab names from registered machines linked to this tab's items
    lab_q = (
        select(Lab.name)
        .join(Machine, Machine.lab_id == Lab.id)
        .join(InventoryItem, func.lower(InventoryItem.ic_no) == func.lower(Machine.inventory_id))
        .where(Lab.name.is_not(None), func.lower(Lab.name) != "unassigned")
        .distinct()
        .order_by(Lab.name)
    )
    if status != "all":
        lab_q = lab_q.where(InventoryItem.status == status)
    for (name,) in (await db.execute(lab_q)).all():
        if (name or "").strip():
            locations.add(name.strip())

    return {
        "status": status,
        "inventory_types": sorted(types, key=str.lower),
        "inventory_locations": sorted(locations, key=str.lower),
        "inv_types": sorted(inv_types, key=str.lower),
        "links": [
            {"value": "any", "label": "Any status"},
            {"value": "registered", "label": "Registered"},
            {"value": "assigned", "label": "Assigned"},
            {"value": "registered_assigned", "label": "Registered + Assigned"},
            {"value": "unlinked", "label": "Not registered"},
        ],
    }


@router.get("", response_model=InventoryListOut)
async def list_inventory(
    db: DbDep,
    user: CurrentUser,
    q: str = "",
    status: str = Query(default="active", pattern="^(active|removed|all)$"),
    inventory_type: str = "",
    inventory_location: str = "",
    inv_type: str = "",
    link: str = Query(default="any", pattern="^(any|registered|assigned|registered_assigned|unlinked)$"),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(InventoryItem)
    count_stmt = select(func.count()).select_from(InventoryItem)
    if status != "all":
        stmt = stmt.where(InventoryItem.status == status)
        count_stmt = count_stmt.where(InventoryItem.status == status)
    stmt, count_stmt = _apply_inventory_filters(
        stmt,
        count_stmt,
        q=q,
        inventory_type=inventory_type,
        inventory_location=inventory_location,
        inv_type=inv_type,
        link=link,
    )
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        await db.execute(stmt.order_by(InventoryItem.ic_no.asc()).offset(offset).limit(limit))
    ).scalars().all()
    links = await _machines_by_ic(db, [r.ic_no for r in rows])
    items = [_link_out(r, links) for r in rows]
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


@router.get("/dashboard")
async def inventory_dashboard(db: DbDep, user: CurrentUser):
    """Per-lab inventory counts (similar to scholars dashboard)."""
    labs = (
        await db.execute(
            select(Lab).where(func.lower(Lab.name) != "unassigned").order_by(Lab.name.asc())
        )
    ).scalars().all()
    active = InventoryItem.status == "active"
    total = (await db.execute(select(func.count()).select_from(InventoryItem).where(active))).scalar_one()
    assigned = (
        await db.execute(
            select(func.count())
            .select_from(InventoryItem)
            .where(active, InventoryItem.assigned_scholar_id.is_not(None))
        )
    ).scalar_one()
    machines_total = (await db.execute(select(func.count()).select_from(Machine))).scalar_one()
    lab_rows = []
    for lab in labs:
        loc = lab.name.strip().lower()
        in_lab = or_(
            func.lower(InventoryItem.inventory_location) == loc,
            InventoryItem.ic_no.in_(
                select(Machine.inventory_id).where(
                    Machine.lab_id == lab.id,
                    Machine.inventory_id.is_not(None),
                    Machine.inventory_id != "",
                )
            ),
        )
        s_count = (
            await db.execute(select(func.count()).select_from(InventoryItem).where(active, in_lab))
        ).scalar_one()
        # "Assigned" = issued to a scholar (owner-held after revoke does not count here).
        s_assigned = (
            await db.execute(
                select(func.count())
                .select_from(InventoryItem)
                .where(active, in_lab, InventoryItem.assigned_scholar_id.is_not(None))
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
                "building": lab.building or "",
                "incharge": lab.incharge or "",
                "items": s_count,
                "assigned": s_assigned,
                "unassigned": max(0, s_count - s_assigned),
                "machines": m_count,
            }
        )
    return {
        "items": total,
        "assigned": assigned,
        "unassigned": max(0, total - assigned),
        "machines": machines_total,
        "labs": lab_rows,
    }


@router.get("/dashboard/{lab_id}")
async def inventory_dashboard_lab(lab_id: UUID, db: DbDep, user: CurrentUser):
    lab = await db.get(Lab, lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    loc = lab.name.strip().lower()
    in_lab = or_(
        func.lower(InventoryItem.inventory_location) == loc,
        InventoryItem.ic_no.in_(
            select(Machine.inventory_id).where(
                Machine.lab_id == lab.id,
                Machine.inventory_id.is_not(None),
                Machine.inventory_id != "",
            )
        ),
    )
    rows = (
        await db.execute(
            select(InventoryItem)
            .where(InventoryItem.status == "active", in_lab)
            .order_by(InventoryItem.ic_no.asc())
        )
    ).scalars().all()
    links = await _machines_by_ic(db, [r.ic_no for r in rows])
    items = [_link_out(r, links) for r in rows]
    issued = sum(1 for r in rows if getattr(r, "assigned_scholar_id", None))
    return {
        "lab": {
            "id": str(lab.id),
            "name": lab.name,
            "room": lab.room or "",
            "building": lab.building or "",
            "incharge": lab.incharge or "",
            "email": lab.email or "",
        },
        "items": [i.model_dump(mode="json") for i in items],
        "counts": {
            "items": len(items),
            "assigned": issued,
            "unassigned": max(0, len(items) - issued),
        },
    }


@router.get("/assignee-search")
async def inventory_assignee_search(
    db: DbDep,
    user: CurrentUser,
    q: str = Query("", min_length=0),
    limit: int = Query(20, ge=1, le=50),
):
    return await inv_assign.search_assignees(db, q, limit=limit)


def _parse_item_ids(item_ids: str | None, item_id: UUID | None) -> list[UUID]:
    """Accept JSON array, comma-separated UUIDs, and/or a legacy single item_id."""
    out: list[UUID] = []
    seen: set[UUID] = set()
    raw = (item_ids or "").strip()
    if raw:
        try:
            import json

            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for x in parsed:
                    uid = UUID(str(x))
                    if uid not in seen:
                        seen.add(uid)
                        out.append(uid)
            else:
                uid = UUID(str(parsed))
                out.append(uid)
        except Exception:
            for part in raw.replace(";", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                uid = UUID(part)
                if uid not in seen:
                    seen.add(uid)
                    out.append(uid)
    if item_id and item_id not in seen:
        out.append(item_id)
    if not out:
        raise HTTPException(400, "At least one inventory item_id is required")
    return out


@router.get("/assigned-search")
async def inventory_assigned_search(
    db: DbDep,
    user: CurrentUser,
    q: str = Query("", min_length=0),
    limit: int = Query(50, ge=1, le=200),
):
    return await inv_assign.search_assigned(db, q, limit=limit)


@router.get("/assigned-records")
async def inventory_assigned_records(
    db: DbDep,
    user: CurrentUser,
    q: str = Query("", min_length=0),
    limit: int = Query(25, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    """Inventory currently issued to scholars (Assign Inv page) — searchable + paged."""
    rows, total = await inv_assign.list_issued_assignments(db, q=q, limit=limit, offset=offset)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/revoked-records")
async def inventory_revoked_records(
    db: DbDep,
    user: CurrentUser,
    q: str = Query("", min_length=0),
    limit: int = Query(25, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    """Inventory with lab owner after revoke — searchable + paged."""
    rows, total = await inv_assign.list_revoked_assignments(db, q=q, limit=limit, offset=offset)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.post("/assign")
async def inventory_assign_start(
    db: DbDep,
    user: OperatorUser,
    request: Request,
    scholar_id: UUID = Form(...),
    verify_method: str = Form("otp"),
    item_ids: str = Form(""),
    item_id: UUID | None = Form(None),
    document: UploadFile | None = File(None),
):
    """Assign one or more inventory items to a scholar. OTP (scholar email) or PDF."""
    ids = _parse_item_ids(item_ids, item_id)
    scholar = await db.get(Scholar, scholar_id)
    if not scholar or scholar.status != "active":
        raise HTTPException(400, "Scholar not found or not active")
    method = (verify_method or "otp").strip().lower()
    if method not in {"otp", "document"}:
        raise HTTPException(400, "verify_method must be otp or document")

    items: list = []
    for iid in ids:
        item = await _get_or_404(db, iid)
        if item.status != "active":
            raise HTTPException(400, f"Cannot assign removed inventory {item.ic_no}")
        items.append(item)
    ic_list = [i.ic_no for i in items]
    label = ", ".join(ic_list[:5]) + (f" (+{len(ic_list) - 5} more)" if len(ic_list) > 5 else "")

    if method == "document":
        if not document or not document.filename:
            raise HTTPException(400, "Upload a PDF verification document")
        raw = await document.read()
        first_rel = ""
        for item in items:
            try:
                doc_rel = inv_assign.save_assign_doc(
                    item.id, raw, document.filename, document.content_type
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if not first_rel:
                first_rel = doc_rel
            await inv_assign.apply_assign_to_scholar(
                db, item, scholar, via="document", by=user.username, doc_path=doc_rel
            )
        await write_audit(
            db,
            "inventory.assign_doc",
            user=user,
            details={
                "item_ids": [str(i.id) for i in items],
                "ic_nos": ic_list,
                "scholar_id": str(scholar.id),
            },
            request=request,
        )
        await db.commit()
        links = await _machines_by_ic(db, ic_list)
        outs = [_link_out(i, links).model_dump(mode="json") for i in items]
        return {
            "ok": True,
            "pending_otp": False,
            "verify_method": "document",
            "count": len(items),
            "item": outs[0],
            "items": outs,
            "message": f"Assigned {len(items)} item(s) ({label}) to {scholar.full_name} (PDF verified).",
        }

    email = (scholar.email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(
            400,
            "Scholar email is required for OTP assign — add email on the scholar record, or use PDF verify",
        )
    payload = {
        "item_ids": [str(i.id) for i in items],
        "item_id": str(items[0].id),  # legacy single-field compat
        "scholar_id": str(scholar.id),
        "ic_nos": ic_list,
        "ic_no": items[0].ic_no,
    }
    await email_otp.expire_open_for_email(db, email_otp.PURPOSE_INV_ISSUE, email)
    challenge, code = await email_otp.create_challenge(
        db,
        purpose=email_otp.PURPOSE_INV_ISSUE,
        email=email,
        payload=payload,
        created_by=user.username,
    )
    try:
        await email_otp.send_otp_mail(
            db,
            to=email,
            code=code,
            context=f"inventory assign · {len(items)} item(s) ({label}) → {scholar.full_name}",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not send OTP email: {exc}") from exc
    await write_audit(
        db,
        "inventory.assign_otp_sent",
        user=user,
        details={
            "item_ids": [str(i.id) for i in items],
            "challenge_id": str(challenge.id),
            "email": email,
        },
        request=request,
    )
    await db.commit()
    return {
        "pending_otp": True,
        "challenge_id": str(challenge.id),
        "email": email,
        "verify_method": "otp",
        "count": len(items),
        "ic_nos": ic_list,
        "message": f"OTP sent to {email}. {len(items)} item(s) assign after the scholar shares the code.",
    }


@router.post("/assign/verify-otp")
async def inventory_assign_verify_otp(
    db: DbDep,
    user: OperatorUser,
    request: Request,
    challenge_id: UUID = Form(...),
    code: str = Form(...),
):
    try:
        challenge = await email_otp.verify_challenge(
            db, challenge_id=challenge_id, code=code, purpose=email_otp.PURPOSE_INV_ISSUE
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    payload = dict(challenge.payload or {})
    scholar = await db.get(Scholar, UUID(str(payload["scholar_id"])))
    if not scholar or scholar.status != "active":
        raise HTTPException(400, "Scholar no longer available")
    id_strs = payload.get("item_ids") or [payload.get("item_id")]
    items = []
    for raw_id in id_strs:
        if not raw_id:
            continue
        item = await _get_or_404(db, UUID(str(raw_id)))
        await inv_assign.apply_assign_to_scholar(
            db, item, scholar, via="otp", by=user.username
        )
        items.append(item)
    if not items:
        raise HTTPException(400, "OTP payload has no inventory items")
    await write_audit(
        db,
        "inventory.assign_otp_verified",
        user=user,
        details={"item_ids": [str(i.id) for i in items], "scholar_id": str(scholar.id)},
        request=request,
    )
    await db.commit()
    links = await _machines_by_ic(db, [i.ic_no for i in items])
    outs = [_link_out(i, links).model_dump(mode="json") for i in items]
    return {
        "ok": True,
        "count": len(items),
        "item": outs[0],
        "items": outs,
        "message": f"Assigned {len(items)} item(s) to {scholar.full_name}.",
    }


@router.post("/revoke")
async def inventory_revoke_start(
    db: DbDep,
    user: OperatorUser,
    request: Request,
    item_ids: str = Form(""),
    item_id: UUID | None = Form(None),
):
    """Start revoke for one or more items: OTP to lab owner who takes inventory back."""
    ids = _parse_item_ids(item_ids, item_id)
    items: list = []
    for iid in ids:
        item = await _get_or_404(db, iid)
        if item.status != "active":
            raise HTTPException(400, f"Cannot revoke removed inventory {item.ic_no}")
        if not item.assigned_scholar_id:
            raise HTTPException(
                400,
                f"{item.ic_no} is not issued to a scholar (already with lab owner, or never assigned)",
            )
        items.append(item)

    # All items in one revoke batch must resolve to the same lab owner email.
    labs = []
    for item in items:
        lab = await inv_assign.lab_for_inventory(db, item)
        if not lab:
            raise HTTPException(400, f"Could not resolve lab owner for {item.ic_no}")
        labs.append(lab)
    lab0 = labs[0]
    if any(lab.id != lab0.id for lab in labs):
        raise HTTPException(
            400,
            "Selected items belong to different labs — revoke one lab's inventory at a time",
        )
    email = (lab0.email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(
            400,
            f"Lab '{lab0.name}' has no owner email — set Lab incharge email under Labs first",
        )
    ic_list = [i.ic_no for i in items]
    label = ", ".join(ic_list[:5]) + (f" (+{len(ic_list) - 5} more)" if len(ic_list) > 5 else "")
    payload = {
        "item_ids": [str(i.id) for i in items],
        "item_id": str(items[0].id),
        "lab_id": str(lab0.id),
        "ic_nos": ic_list,
        "ic_no": items[0].ic_no,
        "owner_name": (lab0.incharge or "").strip(),
    }
    await email_otp.expire_open_for_email(db, email_otp.PURPOSE_INV_REVOKE, email)
    challenge, code = await email_otp.create_challenge(
        db,
        purpose=email_otp.PURPOSE_INV_REVOKE,
        email=email,
        payload=payload,
        created_by=user.username,
    )
    try:
        await email_otp.send_otp_mail(
            db,
            to=email,
            code=code,
            context=f"inventory revoke · {len(items)} item(s) ({label}) · {lab0.name}",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not send OTP email: {exc}") from exc
    await write_audit(
        db,
        "inventory.revoke_otp_sent",
        user=user,
        details={
            "item_ids": [str(i.id) for i in items],
            "lab_id": str(lab0.id),
            "challenge_id": str(challenge.id),
            "email": email,
        },
        request=request,
    )
    await db.commit()
    return {
        "pending_otp": True,
        "challenge_id": str(challenge.id),
        "email": email,
        "owner_name": lab0.incharge or "",
        "lab_name": lab0.name,
        "count": len(items),
        "ic_nos": ic_list,
        "message": (
            f"OTP sent to lab owner {lab0.incharge or email} ({email}). "
            f"Enter code to transfer {len(items)} item(s) to owner."
        ),
    }


@router.post("/revoke/verify-otp")
async def inventory_revoke_verify_otp(
    db: DbDep,
    user: OperatorUser,
    request: Request,
    challenge_id: UUID = Form(...),
    code: str = Form(...),
):
    try:
        challenge = await email_otp.verify_challenge(
            db, challenge_id=challenge_id, code=code, purpose=email_otp.PURPOSE_INV_REVOKE
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    payload = dict(challenge.payload or {})
    lab = await db.get(Lab, UUID(str(payload["lab_id"])))
    if not lab:
        raise HTTPException(400, "Lab no longer available")
    id_strs = payload.get("item_ids") or [payload.get("item_id")]
    items = []
    for raw_id in id_strs:
        if not raw_id:
            continue
        item = await _get_or_404(db, UUID(str(raw_id)))
        if not item.assigned_scholar_id:
            continue
        await inv_assign.apply_revoke_to_owner(db, item, lab, by=user.username)
        items.append(item)
    if not items:
        raise HTTPException(400, "No still-assigned inventory left to revoke for this OTP")
    await write_audit(
        db,
        "inventory.revoke_otp_verified",
        user=user,
        details={"item_ids": [str(i.id) for i in items], "lab_id": str(lab.id), "owner": lab.incharge},
        request=request,
    )
    await db.commit()
    links = await _machines_by_ic(db, [i.ic_no for i in items])
    outs = [_link_out(i, links).model_dump(mode="json") for i in items]
    return {
        "ok": True,
        "count": len(items),
        "item": outs[0],
        "items": outs,
        "message": f"{len(items)} item(s) transferred to lab owner {lab.incharge or lab.name}.",
    }


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
    links = await _machines_by_ic(db, [row.ic_no])
    return _link_out(row, links)


@router.get("/{item_id}", response_model=InventoryItemOut)
async def get_inventory(item_id: UUID, db: DbDep, user: CurrentUser):
    row = await _get_or_404(db, item_id)
    links = await _machines_by_ic(db, [row.ic_no])
    return _link_out(row, links)


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
    links = await _machines_by_ic(db, [row.ic_no])
    return _link_out(row, links)
