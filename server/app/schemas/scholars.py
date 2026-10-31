from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ScholarOut(BaseModel):
    id: UUID
    lab_id: UUID
    lab_name: str = ""
    lab_room: str = ""
    full_name: str = ""
    scholar_id: str = ""
    bio_id: str = ""
    group_name: str = ""
    faculty: str = ""
    system_required: bool = False
    approved: bool = False
    approved_at: datetime | None = None
    no_dues: bool = False
    no_dues_at: datetime | None = None
    inventory_kind: str = "none"  # none | listed | non_list
    inventory_item_id: UUID | None = None
    inventory_label: str = ""
    inventory_item_name: str = ""
    inventory_assigned_at: datetime | None = None
    email: str = ""
    phone: str = ""
    has_photo: bool = False
    has_inv_verify_doc: bool = False
    status: str = "active"
    notes: str = ""
    removed_at: datetime | None = None
    removed_by: str | None = None
    removal_remark: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}

    @field_validator(
        "lab_name",
        "lab_room",
        "full_name",
        "scholar_id",
        "bio_id",
        "group_name",
        "faculty",
        "inventory_kind",
        "inventory_label",
        "inventory_item_name",
        "email",
        "phone",
        "status",
        "notes",
        mode="before",
    )
    @classmethod
    def _none_to_empty(cls, v):  # noqa: ANN001
        return "" if v is None else v

    @field_validator("has_photo", "has_inv_verify_doc", mode="before")
    @classmethod
    def _bool_flag(cls, v):  # noqa: ANN001
        if isinstance(v, bool):
            return v
        return False


class ScholarIdsBody(BaseModel):
    ids: list[UUID] = Field(min_length=1)


class ScholarRemoveBody(BaseModel):
    ids: list[UUID] = Field(min_length=1)
    remark: str = Field(min_length=1, max_length=2000)


class ScholarListOut(BaseModel):
    items: list[ScholarOut]
    total: int


class ScholarCreate(BaseModel):
    lab_id: UUID
    full_name: str = Field(min_length=1, max_length=255)
    scholar_id: str = Field(default="", max_length=120)
    group_name: str = Field(default="", max_length=120)
    faculty: str = Field(default="", max_length=255)
    system_required: bool = False
    inventory_kind: str = "none"
    inventory_item_id: UUID | None = None
    inventory_label: str = ""
    email: str = ""
    phone: str = ""
    notes: str = ""


class ScholarUpdate(BaseModel):
    lab_id: UUID | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    scholar_id: str | None = None
    group_name: str | None = None
    faculty: str | None = None
    system_required: bool | None = None
    inventory_kind: str | None = None
    inventory_item_id: UUID | None = None
    inventory_label: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    status: str | None = None
