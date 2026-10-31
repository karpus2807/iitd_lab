"""Assign / revoke inventory items to scholars with OTP or PDF verification."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InventoryItem, Lab, Machine, Scholar, utcnow
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
    sid = getattr(item, "assigned_scholar_id", None)
    if sid:
        scholar = await db.get(Scholar, sid)
        if scholar:
            lab = await db.get(Lab, scholar.lab_id)
            if lab and lab.name.strip().lower() != "unassigned":
                return lab
    return None


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


async def search_assigned(db: AsyncSession, q: str, *, limit: int = 20) -> list[dict]:
    """Find inventory currently issued to a scholar (for revoke)."""
    needle = (q or "").strip()
    like = f"%{needle}%" if needle else None
    # Only items still issued to a scholar (not already taken back by lab owner).
    stmt = (
        select(InventoryItem, Scholar, Lab)
        .join(Scholar, InventoryItem.assigned_scholar_id == Scholar.id)
        .outerjoin(Lab, Scholar.lab_id == Lab.id)
        .where(
            InventoryItem.status == "active",
            InventoryItem.assigned_scholar_id.is_not(None),
        )
        .order_by(InventoryItem.ic_no.asc())
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
            )
        )
    rows = (await db.execute(stmt.limit(limit))).all()
    out = []
    for item, scholar, lab in rows:
        owner_lab = lab or await lab_for_inventory(db, item)
        out.append(
            {
                "item_id": str(item.id),
                "ic_no": item.ic_no,
                "item_name": item.item_name or "",
                "assigned_to": item.assigned_to or "",
                "assigned_at": item.assigned_at.isoformat() if getattr(item, "assigned_at", None) else None,
                "scholar": (
                    {
                        "id": str(scholar.id),
                        "full_name": scholar.full_name,
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
        )
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
) -> None:
    # Detach previous scholar on this item
    prev_id = getattr(item, "assigned_scholar_id", None)
    if prev_id and prev_id != scholar.id:
        prev = await db.get(Scholar, prev_id)
        await clear_scholar_inventory_link(db, prev, item)
    # Detach this scholar from any other item
    if scholar.inventory_item_id and scholar.inventory_item_id != item.id:
        other = await db.get(InventoryItem, scholar.inventory_item_id)
        if other and other.assigned_scholar_id == scholar.id:
            other.assigned_scholar_id = None
            if (other.assigned_to or "").strip() == (scholar.full_name or "").strip():
                other.assigned_to = ""
            other.assigned_at = None
            other.assign_verify_method = ""

    item.assigned_to = (scholar.full_name or "").strip()
    item.assigned_scholar_id = scholar.id
    item.assigned_at = utcnow()
    item.assigned_by = by or ""
    item.assign_verify_method = via
    item.assign_verify_doc_path = doc_path or ""
    item.revoked_from = ""
    item.revoked_from_scholar_id = ""
    item.revoked_from_bio_id = ""
    item.revoked_from_email = ""
    item.revoked_lab_name = ""

    scholar.system_required = True
    scholar.inventory_kind = "listed"
    scholar.inventory_item_id = item.id
    scholar.inventory_label = item.ic_no
    scholar.inventory_assigned_at = item.assigned_at
    scholar.inv_verify_doc_path = doc_path or ""


async def apply_revoke_to_owner(
    db: AsyncSession,
    item: InventoryItem,
    lab: Lab,
    *,
    by: str,
) -> None:
    scholar = None
    if item.assigned_scholar_id:
        scholar = await db.get(Scholar, item.assigned_scholar_id)
    from_name = (scholar.full_name if scholar else None) or (item.assigned_to or "").strip()
    from_sid = (scholar.scholar_id if scholar else "") or ""
    from_bio = (getattr(scholar, "bio_id", None) if scholar else "") or ""
    from_email = (scholar.email if scholar else "") or ""
    await clear_scholar_inventory_link(db, scholar, item)
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


def save_assign_doc(item_id: UUID, data: bytes, filename: str | None, content_type: str | None) -> str:
    return inv_docs.save_doc(item_id, data, filename, content_type)


async def list_issued_assignments(db: AsyncSession, *, limit: int = 500) -> list[dict]:
    """Inventory currently issued to a scholar (Assign Inv records)."""
    rows = (
        await db.execute(
            select(InventoryItem, Scholar, Lab)
            .join(Scholar, InventoryItem.assigned_scholar_id == Scholar.id)
            .outerjoin(Lab, Scholar.lab_id == Lab.id)
            .where(
                InventoryItem.status == "active",
                InventoryItem.assigned_scholar_id.is_not(None),
            )
            .order_by(InventoryItem.assigned_at.desc(), InventoryItem.ic_no.asc())
            .limit(limit)
        )
    ).all()
    out = []
    for item, scholar, lab in rows:
        out.append(
            {
                "item_id": str(item.id),
                "ic_no": item.ic_no,
                "item_name": item.item_name or "",
                "assigned_to": item.assigned_to or scholar.full_name or "",
                "assigned_at": item.assigned_at.isoformat() if item.assigned_at else None,
                "assigned_by": item.assigned_by or "",
                "verify_method": item.assign_verify_method or "",
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
    return out


async def list_revoked_assignments(db: AsyncSession, *, limit: int = 500) -> list[dict]:
    """Inventory taken back by lab owner after revoke (still marked method=owner)."""
    rows = (
        await db.execute(
            select(InventoryItem)
            .where(
                InventoryItem.status == "active",
                InventoryItem.assign_verify_method == "owner",
            )
            .order_by(InventoryItem.assigned_at.desc(), InventoryItem.ic_no.asc())
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
    return out
