from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InventoryItemOut(BaseModel):
    id: UUID
    ic_no: str
    item_name: str = ""
    item_description: str = ""
    net_effective_value: float | None = None
    inventory_type: str = ""
    inventory_location: str = ""
    gis_date: date | None = None
    inv_type: str = ""
    remark: str = ""
    assigned_to: str = ""
    assigned_scholar_id: UUID | None = None
    assigned_at: datetime | None = None
    assigned_by: str = ""
    assign_verify_method: str = ""
    has_assign_verify_doc: bool = False
    status: str = "active"
    removed_at: datetime | None = None
    removed_by: str | None = None
    removal_remark: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Link to LabWatch machines (machine.inventory_id == ic_no)
    registered: bool = False
    assigned: bool = False
    machine_id: UUID | None = None
    machine_hostname: str | None = None
    machine_lab_name: str | None = None

    model_config = {"from_attributes": True}


class InventoryItemCreate(BaseModel):
    ic_no: str = Field(min_length=1, max_length=120)
    item_name: str = ""
    item_description: str = ""
    net_effective_value: float | None = None
    inventory_type: str = ""
    inventory_location: str = ""
    gis_date: date | None = None
    inv_type: str = ""
    remark: str = ""
    assigned_to: str = ""


class InventoryItemUpdate(BaseModel):
    ic_no: str | None = Field(default=None, min_length=1, max_length=120)
    item_name: str | None = None
    item_description: str | None = None
    net_effective_value: float | None = None
    inventory_type: str | None = None
    inventory_location: str | None = None
    gis_date: date | None = None
    inv_type: str | None = None
    remark: str | None = None
    assigned_to: str | None = None


class InventoryBatchUpdate(BaseModel):
    ids: list[UUID] = Field(min_length=1)
    fields: InventoryItemUpdate


class InventoryRemoveBody(BaseModel):
    ids: list[UUID] = Field(min_length=1)
    remark: str = Field(min_length=1, max_length=2000)


class InventoryIdsBody(BaseModel):
    """Restore or permanently delete removed inventory items."""

    ids: list[UUID] = Field(min_length=1)


class InventorySuggestItem(BaseModel):
    id: UUID
    ic_no: str
    item_name: str = ""
    inventory_location: str = ""
    inv_type: str = ""


class InventoryListOut(BaseModel):
    items: list[InventoryItemOut]
    total: int
    status: str = "active"
