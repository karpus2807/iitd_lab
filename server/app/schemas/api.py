from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    username: str
    user_id: UUID


class RefreshRequest(BaseModel):
    refresh_token: str


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = ""
    role: str = "VIEWER"


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


class UserOut(BaseModel):
    id: UUID
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}


class LabCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class LabUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class LabOut(BaseModel):
    id: UUID
    name: str
    description: str
    machine_count: int = 0
    online_count: int = 0

    model_config = {"from_attributes": True}


class MachineUpdate(BaseModel):
    display_name: str | None = None
    lab_id: UUID | None = None
    approved: bool | None = None


class MachineListItem(BaseModel):
    id: UUID
    hostname: str
    display_name: str
    lab_id: UUID | None
    lab_name: str | None = None
    status: str
    os_name: str
    architecture: str
    current_ip: str | None
    current_ips: list[str] = []
    previous_ip: str | None = None
    last_seen_at: datetime | None
    gpu_count: int
    has_open_alerts: bool
    is_virtual: bool
    last_hardware_change_at: datetime | None
    approved: bool


class AlertRuleIn(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    severity: str = "WARNING"
    rule_type: str
    event_type: str | None = None
    metric_name: str | None = None
    operator: str = ">"
    threshold: float | None = None
    cooldown_seconds: int = 900


class RegistrationTokenCreate(BaseModel):
    label: str = ""
    lab_id: UUID | None = None
    expires_hours: int | None = 168
    max_uses: int | None = None
