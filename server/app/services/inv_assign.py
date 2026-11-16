"""Assign / revoke inventory items to scholars with OTP or PDF verification.

Supports many-to-many: one IC → many scholars, one scholar → many ICs.
Active issues live in ``inventory_assignments``; denormalized fields on
``inventory_items`` stay in sync for list/dashboard compatibility.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InventoryAssignment, InventoryItem, Lab, Machine, Scholar, utcnow
from app.services import inv_verify_docs as inv_docs


async def lab_for_inventory(db: AsyncSession, item: InventoryItem) -> Lab | None:
    """Resolve owning lab: location name → registered machine lab → assignee scholar lab."""
    loc = (item.inventory_location or "").strip()
    if loc:
        lab = (
            await db.execute(select(Lab).where(func.lower(Lab.name) == loc.lower()))
        ).scalar_one_or_none()
        if lab and lab.name.strip().lower() != "unassigned":
            return lab
    ic = (item.ic_no or "").strip().lower()
    if ic:
        row = (
            await db.execute(
                select(Lab)
                .join(Machine, Machine.lab_id == Lab.id)
                .where(func.lower(Machine.inventory_id) == ic)
            )
        ).scalar_one_or_none()
        if row and row.name.strip().lower() != "unassigned":
            return row
    # Prefer any active assignment's scholar lab.
    asg = (
        await db.execute(
            select(InventoryAssignment, Scholar)
            .join(Scholar, InventoryAssignment.scholar_id == Scholar.id)
            .where(
                InventoryAssignment.inventory_item_id == item.id,
                InventoryAssignment.status == "active",
            )
            .order_by(InventoryAssignment.assigned_at.desc())
            .limit(1)
        )
    ).first()
    if asg:
        _asg, scholar = asg
        lab = await db.get(Lab, scholar.lab_id)
        if lab and lab.name.strip().lower() != "unassigned":
            return lab
    sid = getattr(item, "assigned_scholar_id", None)
    if sid:
        scholar = await db.get(Scholar, sid)
        if scholar:
            lab = await db.get(Lab, scholar.lab_id)
            if lab and lab.name.strip().lower() != "unassigned":
                return lab
    return None


async def active_assignments_for_item(
    db: AsyncSession, item_id: UUID
) -> list[InventoryAssignment]:
    return list(
        (
            await db.execute(
                select(InventoryAssignment)
                .where(
                    InventoryAssignment.inventory_item_id == item_id,
                    InventoryAssignment.status == "active",
                )
                .order_by(InventoryAssignment.assigned_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def _sync_item_assignees(db: AsyncSession, item: InventoryItem) -> None:
    """Refresh denormalized assignee fields from active junction rows."""
    rows = (
        await db.execute(
            select(InventoryAssignment, Scholar)
            .join(Scholar, InventoryAssignment.scholar_id == Scholar.id)
            .where(
                InventoryAssignment.inventory_item_id == item.id,
                InventoryAssignment.status == "active",
            )
            .order_by(InventoryAssignment.assigned_at.desc(), Scholar.full_name.asc())
        )
    ).all()
    if not rows:
        # Keep owner-held snapshot if last action was revoke-to-owner.
        if (item.assign_verify_method or "") == "owner":
            return
        item.assigned_scholar_id = None
        if (item.assigned_to or "").strip() and not (item.revoked_from or "").strip():
            item.assigned_to = ""
        item.assign_verify_method = item.assign_verify_method or ""
        item.assign_verify_doc_path = ""
        return

    names = [(s.full_name or "").strip() or (s.scholar_id or "scholar") for _a, s in rows]
    primary_asg, primary_scholar = rows[0]
    item.assigned_scholar_id = primary_scholar.id
    if len(names) == 1:
        item.assigned_to = names[0]
    else:
        item.assigned_to = f"{names[0]} (+{len(names) - 1} more)"
    item.assigned_at = primary_asg.assigned_at
    item.assigned_by = primary_asg.assigned_by or ""
    item.assign_verify_method = primary_asg.verify_method or ""
    item.assign_verify_doc_path = primary_asg.verify_doc_path or ""
    item.revoked_from = ""
    item.revoked_from_scholar_id = ""
    item.revoked_from_bio_id = ""
    item.revoked_from_email = ""
    item.revoked_lab_name = ""


async def search_assignees(db: AsyncSession, q: str, *, limit: int = 20) -> list[dict]:
    """Typeahead: scholars (ID/bio/name/email) + machines (inventory_id/hostname)."""
    needle = (q or "").strip()
    if len(needle) < 1:
        return []
    like = f"%{needle}%"
    out: list[dict] = []
    scholars = (
        await db.execute(
            select(Scholar, Lab)
            .join(Lab, Scholar.lab_id == Lab.id)
            .where(
                Scholar.status == "active",
                or_(
                    Scholar.scholar_id.ilike(like),
                    Scholar.bio_id.ilike(like),
                    Scholar.full_name.ilike(like),
                    Scholar.email.ilike(like),
                ),
            )
            .order_by(Scholar.full_name.asc())
            .limit(limit)
        )
    ).all()
    for s, lab in scholars:
        out.append(
            {
                "type": "scholar",
                "id": str(s.id),
                "label": s.full_name or "",
                "scholar_id": s.scholar_id or "",
                "bio_id": s.bio_id or "",
                "email": s.email or "",
                "lab_id": str(lab.id),
                "lab_name": lab.name or "",
                "has_email": bool((s.email or "").strip() and "@" in (s.email or "")),
            }
        )
    machines = (
        await db.execute(
            select(Machine, Lab)
            .outerjoin(Lab, Machine.lab_id == Lab.id)
            .where(
                or_(
                    Machine.inventory_id.ilike(like),
                    Machine.hostname.ilike(like),
                    Machine.display_name.ilike(like),
                )
            )
            .order_by(Machine.hostname.asc())
            .limit(limit)
        )
    ).all()
    for m, lab in machines:
        out.append(
            {
                "type": "machine",
                "id": str(m.id),
                "label": m.hostname or m.display_name or "",
                "inventory_id": m.inventory_id or "",
                "lab_id": str(lab.id) if lab else "",
                "lab_name": (lab.name if lab else "") or "",
            }
        )
    return out[: limit + 5]


def _assignment_hit(item: InventoryItem, asg: InventoryAssignment, scholar: Scholar, owner_lab: Lab | None) -> dict:
    return {
        "assignment_id": str(asg.id),
        "item_id": str(item.id),
        "ic_no": item.ic_no,
        "item_name": item.item_name or "",
        "assigned_to": (scholar.full_name if scholar else "") or item.assigned_to or "",
        "assigned_at": asg.assigned_at.isoformat() if asg.assigned_at else None,
        "assigned_by": asg.assigned_by or "",
        "verify_method": asg.verify_method or "",
        "has_verify_doc": bool(asg.verify_doc_path),
        "scholar": (
            {
                "id": str(scholar.id),
                "full_name": scholar.full_name or "",
                "scholar_id": scholar.scholar_id or "",
                "bio_id": scholar.bio_id or "",
                "email": scholar.email or "",
            }
            if scholar
            else None
        ),
        "owner": (
            {
                "lab_id": str(owner_lab.id),
                "lab_name": owner_lab.name,
                "incharge": owner_lab.incharge or "",
                "email": owner_lab.email or "",
                "phone": owner_lab.phone or "",
            }
            if owner_lab
            else None
        ),
    }


async def search_assigned(db: AsyncSession, q: str, *, limit: int = 50) -> list[dict]:
    """Find active assignment rows (for revoke). One hit per item↔scholar pair."""
    needle = (q or "").strip()
    like = f"%{needle}%" if needle else None
    stmt = (
        select(InventoryAssignment, InventoryItem, Scholar, Lab)
        .join(InventoryItem, InventoryAssignment.inventory_item_id == InventoryItem.id)
        .join(Scholar, InventoryAssignment.scholar_id == Scholar.id)
        .outerjoin(Lab, Scholar.lab_id == Lab.id)
        .where(
            InventoryAssignment.status == "active",
            InventoryItem.status == "active",
        )
        .order_by(InventoryAssignment.assigned_at.desc(), InventoryItem.ic_no.asc())
    )
    if like:
        stmt = stmt.where(
            or_(
                InventoryItem.ic_no.ilike(like),
                InventoryItem.item_name.ilike(like),
                InventoryItem.assigned_to.ilike(like),
                Scholar.scholar_id.ilike(like),
                Scholar.full_name.ilike(like),
                Scholar.bio_id.ilike(like),
                Scholar.email.ilike(like),
                Lab.name.ilike(like),
            )
        )
    rows = (await db.execute(stmt.limit(limit))).all()

    if like and rows:
        scholar_ids = {scholar.id for _, _, scholar, _ in rows if scholar}
        if scholar_ids:
            extra = (
                await db.execute(
                    select(InventoryAssignment, InventoryItem, Scholar, Lab)
                    .join(InventoryItem, InventoryAssignment.inventory_item_id == InventoryItem.id)
                    .join(Scholar, InventoryAssignment.scholar_id == Scholar.id)
                    .outerjoin(Lab, Scholar.lab_id == Lab.id)
                    .where(
                        InventoryAssignment.status == "active",
                        InventoryItem.status == "active",
                        InventoryAssignment.scholar_id.in_(scholar_ids),
                    )
                    .order_by(InventoryItem.ic_no.asc())
                    .limit(limit)
                )
            ).all()
            seen = {asg.id for asg, _, _, _ in rows}
            for row in extra:
                if row[0].id not in seen:
                    rows.append(row)
                    seen.add(row[0].id)

    out = []
    for asg, item, scholar, lab in rows[:limit]:
        owner_lab = lab or await lab_for_inventory(db, item)
        out.append(_assignment_hit(item, asg, scholar, owner_lab))
    return out


async def clear_scholar_inventory_link(db: AsyncSession, scholar: Scholar | None, item: InventoryItem) -> None:
    if not scholar:
        return
    if scholar.inventory_item_id == item.id:
        scholar.inventory_kind = "none"
        scholar.inventory_item_id = None
        scholar.inventory_label = ""
        scholar.inventory_assigned_at = None
        scholar.system_required = False


async def apply_assign_to_scholar(
    db: AsyncSession,
    item: InventoryItem,
    scholar: Scholar,
    *,
    via: str,
    by: str,
    doc_path: str = "",
) -> InventoryAssignment:
    """Add (or refresh) an active assignment — does not remove other scholars on this item."""
    existing = (
        await db.execute(
            select(InventoryAssignment).where(
                InventoryAssignment.inventory_item_id == item.id,
                InventoryAssignment.scholar_id == scholar.id,
                InventoryAssignment.status == "active",
            )
        )
    ).scalar_one_or_none()
    now = utcnow()
    if existing:
        existing.assigned_at = now
        existing.assigned_by = by or ""
        existing.verify_method = via
        if doc_path:
            existing.verify_doc_path = doc_path
        asg = existing
    else:
        asg = InventoryAssignment(
            inventory_item_id=item.id,
            scholar_id=scholar.id,
            status="active",
            assigned_at=now,
            assigned_by=by or "",
            verify_method=via,
            verify_doc_path=doc_path or "",
        )
        db.add(asg)
        await db.flush()

    if doc_path:
        scholar.inv_verify_doc_path = doc_path

    await _sync_item_assignees(db, item)
    await _refresh_scholar_inventory_pointer(db, scholar)
    return asg


async def _refresh_scholar_inventory_pointer(db: AsyncSession, scholar: Scholar | None) -> None:
    """Point scholar.inventory_* at active issued items (or clear if none)."""
    if not scholar:
        return
    rows = (
        await db.execute(
            select(InventoryAssignment, InventoryItem)
            .join(InventoryItem, InventoryAssignment.inventory_item_id == InventoryItem.id)
            .where(
                InventoryAssignment.scholar_id == scholar.id,
                InventoryAssignment.status == "active",
                InventoryItem.status == "active",
            )
            .order_by(InventoryAssignment.assigned_at.desc(), InventoryItem.ic_no.asc())
        )
    ).all()
    if not rows:
        scholar.inventory_kind = "none"
        scholar.inventory_item_id = None
        scholar.inventory_label = ""
        scholar.inventory_assigned_at = None
        scholar.system_required = False
        return
    primary_asg, primary = rows[0]
    scholar.system_required = True
    scholar.inventory_kind = "listed"
    scholar.inventory_item_id = primary.id
    if len(rows) == 1:
        scholar.inventory_label = primary.ic_no
    else:
        scholar.inventory_label = f"{primary.ic_no} (+{len(rows) - 1} more)"
    scholar.inventory_assigned_at = primary_asg.assigned_at


async def apply_revoke_assignment(
    db: AsyncSession,
    asg: InventoryAssignment,
    lab: Lab | None,
    *,
    by: str,
) -> InventoryItem:
    """Revoke one assignment row. If item has no remaining assignees, mark owner-held."""
    item = await db.get(InventoryItem, asg.inventory_item_id)
    if not item:
        raise ValueError("Inventory item missing for assignment")
    scholar = await db.get(Scholar, asg.scholar_id)
    from_name = (scholar.full_name if scholar else None) or ""
    from_sid = (scholar.scholar_id if scholar else "") or ""
    from_bio = (getattr(scholar, "bio_id", None) if scholar else "") or ""
    from_email = (scholar.email if scholar else "") or ""

    asg.status = "revoked"
    asg.revoked_at = utcnow()
    asg.revoked_by = by or ""

    remaining = await active_assignments_for_item(db, item.id)
    # Exclude the one we just revoked if still visible before flush.
    remaining = [r for r in remaining if r.id != asg.id and r.status == "active"]

    if remaining:
        await _sync_item_assignees(db, item)
    elif lab is not None:
        owner_name = (lab.incharge or "").strip() or f"Lab owner · {lab.name}"
        item.revoked_from = from_name
        item.revoked_from_scholar_id = from_sid
        item.revoked_from_bio_id = from_bio
        item.revoked_from_email = from_email
        item.revoked_lab_name = lab.name or ""
        item.assigned_to = owner_name
        item.assigned_scholar_id = None
        item.assigned_at = utcnow()
        item.assigned_by = by or ""
        item.assign_verify_method = "owner"
        item.assign_verify_doc_path = ""
    else:
        item.assigned_to = ""
        item.assigned_scholar_id = None
        item.assigned_at = utcnow()
        item.assigned_by = by or ""
        item.assign_verify_method = ""
        item.assign_verify_doc_path = ""

    if scholar:
        await clear_scholar_inventory_link(db, scholar, item)
        await _refresh_scholar_inventory_pointer(db, scholar)
    return item


async def apply_revoke_to_owner(
    db: AsyncSession,
    item: InventoryItem,
    lab: Lab | None,
    *,
    by: str,
    scholar_id: UUID | None = None,
) -> None:
    """Revoke active assignment(s) on an item.

    If scholar_id is set, only that scholar is removed; otherwise all active
    assignees on the item are revoked (lab-owner takeover).
    """
    q = select(InventoryAssignment).where(
        InventoryAssignment.inventory_item_id == item.id,
        InventoryAssignment.status == "active",
    )
    if scholar_id:
        q = q.where(InventoryAssignment.scholar_id == scholar_id)
    rows = list((await db.execute(q)).scalars().all())
    if not rows:
        # Legacy fallback: single denormalized assignee, no junction row yet.
        if item.assigned_scholar_id and (not scholar_id or item.assigned_scholar_id == scholar_id):
            scholar = await db.get(Scholar, item.assigned_scholar_id)
            from_name = (scholar.full_name if scholar else None) or (item.assigned_to or "").strip()
            from_sid = (scholar.scholar_id if scholar else "") or ""
            from_bio = (getattr(scholar, "bio_id", None) if scholar else "") or ""
            from_email = (scholar.email if scholar else "") or ""
            await clear_scholar_inventory_link(db, scholar, item)
            if lab is not None:
                owner_name = (lab.incharge or "").strip() or f"Lab owner · {lab.name}"
                item.revoked_from = from_name
                item.revoked_from_scholar_id = from_sid
                item.revoked_from_bio_id = from_bio
                item.revoked_from_email = from_email
                item.revoked_lab_name = lab.name or ""
                item.assigned_to = owner_name
                item.assign_verify_method = "owner"
            else:
                item.assigned_to = ""
                item.assign_verify_method = ""
            item.assigned_scholar_id = None
            item.assigned_at = utcnow()
            item.assigned_by = by or ""
            item.assign_verify_doc_path = ""
            await _refresh_scholar_inventory_pointer(db, scholar)
        return

    for asg in rows:
        await apply_revoke_assignment(db, asg, lab, by=by)


def save_assign_doc(entity_id: UUID, data: bytes, filename: str | None, content_type: str | None) -> str:
    """Store PDF keyed by assignment (or temporary item) UUID."""
    return inv_docs.save_doc(entity_id, data, filename, content_type)


async def list_issued_assignments(
    db: AsyncSession,
    *,
    q: str = "",
    lab_id: UUID | None = None,
    verify_method: str = "",
    scholar_id: UUID | None = None,
    item_id: UUID | None = None,
    assigned_from: datetime | None = None,
    assigned_to: datetime | None = None,
    limit: int = 500,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Active assignment rows for the Assigned tab (one row per item↔scholar)."""
    needle = (q or "").strip()
    like = f"%{needle}%" if needle else None
    base = (
        select(InventoryAssignment, InventoryItem, Scholar, Lab)
        .join(InventoryItem, InventoryAssignment.inventory_item_id == InventoryItem.id)
        .join(Scholar, InventoryAssignment.scholar_id == Scholar.id)
        .outerjoin(Lab, Scholar.lab_id == Lab.id)
        .where(
            InventoryAssignment.status == "active",
            InventoryItem.status == "active",
        )
    )
    if like:
        base = base.where(
            or_(
                InventoryItem.ic_no.ilike(like),
                InventoryItem.item_name.ilike(like),
                InventoryItem.assigned_to.ilike(like),
                InventoryItem.inventory_type.ilike(like),
                InventoryItem.inventory_location.ilike(like),
                InventoryItem.inv_type.ilike(like),
                Scholar.scholar_id.ilike(like),
                Scholar.full_name.ilike(like),
                Scholar.bio_id.ilike(like),
                Scholar.email.ilike(like),
                Scholar.faculty.ilike(like),
                Scholar.group_name.ilike(like),
                Scholar.phone.ilike(like),
                Lab.name.ilike(like),
                InventoryAssignment.verify_method.ilike(like),
                InventoryAssignment.assigned_by.ilike(like),
            )
        )
    if lab_id:
        base = base.where(Scholar.lab_id == lab_id)
    if scholar_id:
        base = base.where(InventoryAssignment.scholar_id == scholar_id)
    if item_id:
        base = base.where(InventoryAssignment.inventory_item_id == item_id)
    method = (verify_method or "").strip().lower()
    if method in {"otp", "document"}:
        base = base.where(func.lower(InventoryAssignment.verify_method) == method)
    if assigned_from is not None:
        base = base.where(InventoryAssignment.assigned_at >= assigned_from)
    if assigned_to is not None:
        base = base.where(InventoryAssignment.assigned_at <= assigned_to)

    count = (
        await db.execute(select(func.count()).select_from(base.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(InventoryAssignment.assigned_at.desc(), InventoryItem.ic_no.asc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    out = []
    for asg, item, scholar, lab in rows:
        out.append(
            {
                "assignment_id": str(asg.id),
                "item_id": str(item.id),
                "ic_no": item.ic_no,
                "item_name": item.item_name or "",
                "inventory_type": item.inventory_type or "",
                "inventory_location": item.inventory_location or "",
                "inv_type": item.inv_type or "",
                "assigned_to": scholar.full_name or item.assigned_to or "",
                "assigned_at": asg.assigned_at.isoformat() if asg.assigned_at else None,
                "assigned_by": asg.assigned_by or "",
                "verify_method": asg.verify_method or "",
                "has_verify_doc": bool(asg.verify_doc_path),
                "scholar": {
                    "id": str(scholar.id),
                    "full_name": scholar.full_name or "",
                    "scholar_id": scholar.scholar_id or "",
                    "bio_id": scholar.bio_id or "",
                    "email": scholar.email or "",
                    "phone": scholar.phone or "",
                    "group_name": scholar.group_name or "",
                    "faculty": scholar.faculty or "",
                },
                "lab": (
                    {
                        "id": str(lab.id),
                        "name": lab.name or "",
                        "room": lab.room or "",
                    }
                    if lab
                    else None
                ),
            }
        )
    return out, int(count or 0)


async def list_item_assignees(db: AsyncSession, item_ids: list[UUID]) -> dict[UUID, list[dict]]:
    """Map item_id → active assignee summaries (for Active table)."""
    if not item_ids:
        return {}
    rows = (
        await db.execute(
            select(InventoryAssignment, Scholar)
            .join(Scholar, InventoryAssignment.scholar_id == Scholar.id)
            .where(
                InventoryAssignment.inventory_item_id.in_(item_ids),
                InventoryAssignment.status == "active",
            )
            .order_by(InventoryAssignment.assigned_at.desc())
        )
    ).all()
    out: dict[UUID, list[dict]] = {iid: [] for iid in item_ids}
    for asg, scholar in rows:
        out.setdefault(asg.inventory_item_id, []).append(
            {
                "assignment_id": str(asg.id),
                "scholar_id": str(scholar.id),
                "full_name": scholar.full_name or "",
                "entry_no": scholar.scholar_id or "",
                "assigned_at": asg.assigned_at.isoformat() if asg.assigned_at else None,
                "verify_method": asg.verify_method or "",
                "has_verify_doc": bool(asg.verify_doc_path),
            }
        )
    return out


async def list_revoked_assignments(
    db: AsyncSession, *, q: str = "", limit: int = 500, offset: int = 0
) -> tuple[list[dict], int]:
    """Inventory taken back by lab owner after revoke (still marked method=owner)."""
    needle = (q or "").strip()
    like = f"%{needle}%" if needle else None
    base = select(InventoryItem).where(
        InventoryItem.status == "active",
        InventoryItem.assign_verify_method == "owner",
    )
    if like:
        base = base.where(
            or_(
                InventoryItem.ic_no.ilike(like),
                InventoryItem.item_name.ilike(like),
                InventoryItem.assigned_to.ilike(like),
                InventoryItem.revoked_from.ilike(like),
                InventoryItem.revoked_from_scholar_id.ilike(like),
                InventoryItem.revoked_from_bio_id.ilike(like),
                InventoryItem.revoked_from_email.ilike(like),
                InventoryItem.revoked_lab_name.ilike(like),
                InventoryItem.assigned_by.ilike(like),
            )
        )
    count = (await db.execute(select(func.count()).select_from(base.order_by(None).subquery()))).scalar_one()
    rows = (
        await db.execute(
            base.order_by(InventoryItem.assigned_at.desc(), InventoryItem.ic_no.asc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    out = []
    for item in rows:
        owner_lab = await lab_for_inventory(db, item)
        out.append(
            {
                "item_id": str(item.id),
                "ic_no": item.ic_no,
                "item_name": item.item_name or "",
                "revoked_at": item.assigned_at.isoformat() if item.assigned_at else None,
                "revoked_by": item.assigned_by or "",
                "revoked_from": getattr(item, "revoked_from", None) or "",
                "revoked_from_scholar_id": getattr(item, "revoked_from_scholar_id", None) or "",
                "revoked_from_bio_id": getattr(item, "revoked_from_bio_id", None) or "",
                "revoked_from_email": getattr(item, "revoked_from_email", None) or "",
                "revoked_lab_name": getattr(item, "revoked_lab_name", None) or (owner_lab.name if owner_lab else ""),
                "now_with": item.assigned_to or "",
                "owner": (
                    {
                        "lab_id": str(owner_lab.id),
                        "lab_name": owner_lab.name,
                        "incharge": owner_lab.incharge or "",
                        "email": owner_lab.email or "",
                    }
                    if owner_lab
                    else None
                ),
            }
        )
    return out, int(count or 0)


async def item_has_active_assignment(db: AsyncSession, item: InventoryItem) -> bool:
    row = (
        await db.execute(
            select(InventoryAssignment.id).where(
                InventoryAssignment.inventory_item_id == item.id,
                InventoryAssignment.status == "active",
            ).limit(1)
        )
    ).scalar_one_or_none()
    if row:
        return True
    return bool(getattr(item, "assigned_scholar_id", None))
