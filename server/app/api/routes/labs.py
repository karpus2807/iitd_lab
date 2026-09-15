from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from sqlalchemy.exc import OperationalError, ProgrammingError

from app.api.deps import AdminUser, CurrentUser, DbDep, OperatorUser, write_audit
from app.db import ensure_lab_columns, get_engine
from app.enums import MachineStatus
from app.models import Lab, Machine
from app.schemas.api import LabCreate, LabOut, LabUpdate

router = APIRouter(prefix="/api/labs", tags=["labs"])

UNASSIGNED = "Unassigned"
STR_FIELDS = ("code", "department", "building", "floor", "room", "incharge", "phone", "email", "description")


def _is_protected(lab: Lab) -> bool:
    return lab.name.strip().lower() == UNASSIGNED.lower()


def _text(lab: Lab, key: str) -> str:
    return getattr(lab, key, None) or ""


def _apply_fields(lab: Lab, data: dict) -> None:
    for key in STR_FIELDS:
        if key in data and data[key] is not None:
            setattr(lab, key, str(data[key]).strip())
    if "capacity" in data and data["capacity"] is not None:
        lab.capacity = max(0, int(data["capacity"]))


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
        code=_text(lab, "code"),
        department=_text(lab, "department"),
        building=_text(lab, "building"),
        floor=_text(lab, "floor"),
        room=_text(lab, "room"),
        capacity=int(getattr(lab, "capacity", 0) or 0),
        incharge=_text(lab, "incharge"),
        phone=_text(lab, "phone"),
        email=_text(lab, "email"),
        description=_text(lab, "description"),
        machine_count=total,
        online_count=online,
        protected=_is_protected(lab),
    )


@router.get("", response_model=list[LabOut])
async def list_labs(db: DbDep, user: CurrentUser):
    try:
        labs = (await db.execute(select(Lab).order_by(Lab.name.asc()))).scalars().all()
    except (ProgrammingError, OperationalError):
        await db.rollback()
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(ensure_lab_columns)
        labs = (await db.execute(select(Lab).order_by(Lab.name.asc()))).scalars().all()
    return [await _lab_out(db, lab) for lab in labs]


@router.get("/{lab_id}", response_model=LabOut)
async def get_lab(lab_id: UUID, db: DbDep, user: CurrentUser):
    lab = await db.get(Lab, lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    return await _lab_out(db, lab)


@router.post("", response_model=LabOut)
async def create_lab(body: LabCreate, db: DbDep, user: OperatorUser):
    existing = (await db.execute(select(Lab).where(func.lower(Lab.name) == body.name.strip().lower()))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Lab already exists")
    lab = Lab(name=body.name.strip())
    _apply_fields(lab, body.model_dump())
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
    _apply_fields(lab, data)
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
