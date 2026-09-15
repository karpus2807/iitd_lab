from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import AdminUser, CurrentUser, DbDep, OperatorUser, write_audit
from app.enums import MachineStatus
from app.models import Lab, Machine
from app.schemas.api import LabCreate, LabOut, LabUpdate

router = APIRouter(prefix="/api/labs", tags=["labs"])

UNASSIGNED = "Unassigned"


def _is_protected(lab: Lab) -> bool:
    return lab.name.strip().lower() == UNASSIGNED.lower()


async def _unassigned_lab(db) -> Lab:
    lab = (await db.execute(select(Lab).where(func.lower(Lab.name) == UNASSIGNED.lower()))).scalar_one_or_none()
    if lab:
        return lab
    lab = Lab(name=UNASSIGNED, description="Default lab for newly registered machines")
    db.add(lab)
    await db.flush()
    return lab


async def _lab_out(db, lab: Lab) -> LabOut:
    total = (await db.execute(select(func.count()).select_from(Machine).where(Machine.lab_id == lab.id))).scalar_one()
    online = (
        await db.execute(
            select(func.count())
            .select_from(Machine)
            .where(Machine.lab_id == lab.id, Machine.status == MachineStatus.ONLINE.value)
        )
    ).scalar_one()
    return LabOut(
        id=lab.id,
        name=lab.name,
        description=lab.description or "",
        building=getattr(lab, "building", None) or "",
        room=getattr(lab, "room", None) or "",
        machine_count=total,
        online_count=online,
        protected=_is_protected(lab),
    )


@router.get("", response_model=list[LabOut])
async def list_labs(db: DbDep, user: CurrentUser):
    labs = (await db.execute(select(Lab).order_by(Lab.name.asc()))).scalars().all()
    return [await _lab_out(db, lab) for lab in labs]


@router.post("", response_model=LabOut)
async def create_lab(body: LabCreate, db: DbDep, user: OperatorUser):
    existing = (await db.execute(select(Lab).where(func.lower(Lab.name) == body.name.strip().lower()))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Lab already exists")
    lab = Lab(
        name=body.name.strip(),
        description=body.description,
        building=body.building.strip(),
        room=body.room.strip(),
    )
    db.add(lab)
    await write_audit(db, "lab.create", user=user, details={"name": body.name})
    await db.commit()
    await db.refresh(lab)
    return await _lab_out(db, lab)


@router.patch("/{lab_id}", response_model=LabOut)
async def update_lab(lab_id: UUID, body: LabUpdate, db: DbDep, user: OperatorUser):
    lab = await db.get(Lab, lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        name = data["name"].strip()
        if _is_protected(lab) and name.lower() != UNASSIGNED.lower():
            raise HTTPException(400, "The Unassigned lab cannot be renamed")
        clash = (
            await db.execute(select(Lab).where(func.lower(Lab.name) == name.lower(), Lab.id != lab.id))
        ).scalar_one_or_none()
        if clash:
            raise HTTPException(409, "Lab already exists")
        lab.name = name
    if "description" in data and data["description"] is not None:
        lab.description = data["description"]
    if "building" in data and data["building"] is not None:
        lab.building = data["building"].strip()
    if "room" in data and data["room"] is not None:
        lab.room = data["room"].strip()
    await write_audit(db, "lab.update", user=user, details={"lab_id": str(lab_id), "name": lab.name})
    await db.commit()
    return await _lab_out(db, lab)


@router.delete("/{lab_id}")
async def delete_lab(lab_id: UUID, db: DbDep, user: AdminUser):
    lab = await db.get(Lab, lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    if _is_protected(lab):
        raise HTTPException(400, "The Unassigned lab cannot be deleted")
    fallback = await _unassigned_lab(db)
    machines = (await db.execute(select(Machine).where(Machine.lab_id == lab.id))).scalars().all()
    for machine in machines:
        machine.lab_id = fallback.id
    await db.delete(lab)
    await write_audit(db, "lab.delete", user=user, details={"name": lab.name})
    await db.commit()
    return {"ok": True, "moved_machines": len(machines)}
