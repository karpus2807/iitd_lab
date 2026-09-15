from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import AdminUser, CurrentUser, DbDep, OperatorUser, write_audit
from app.enums import MachineStatus
from app.models import Lab, Machine
from app.schemas.api import LabCreate, LabOut, LabUpdate

router = APIRouter(prefix="/api/labs", tags=["labs"])


async def _lab_out(db, lab: Lab) -> LabOut:
    total = (await db.execute(select(func.count()).select_from(Machine).where(Machine.lab_id == lab.id))).scalar_one()
    online = (
        await db.execute(
            select(func.count())
            .select_from(Machine)
            .where(Machine.lab_id == lab.id, Machine.status == MachineStatus.ONLINE.value)
        )
    ).scalar_one()
    return LabOut(id=lab.id, name=lab.name, description=lab.description, machine_count=total, online_count=online)


@router.get("", response_model=list[LabOut])
async def list_labs(db: DbDep, user: CurrentUser):
    labs = (await db.execute(select(Lab).order_by(Lab.name.asc()))).scalars().all()
    return [await _lab_out(db, lab) for lab in labs]


@router.post("", response_model=LabOut)
async def create_lab(body: LabCreate, db: DbDep, user: OperatorUser):
    existing = (await db.execute(select(Lab).where(Lab.name == body.name))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Lab already exists")
    lab = Lab(name=body.name, description=body.description)
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
    if body.name is not None:
        lab.name = body.name
    if body.description is not None:
        lab.description = body.description
    await write_audit(db, "lab.update", user=user, details={"lab_id": str(lab_id)})
    await db.commit()
    return await _lab_out(db, lab)


@router.delete("/{lab_id}")
async def delete_lab(lab_id: UUID, db: DbDep, user: AdminUser):
    lab = await db.get(Lab, lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    await db.delete(lab)
    await write_audit(db, "lab.delete", user=user, details={"name": lab.name})
    await db.commit()
    return {"ok": True}
