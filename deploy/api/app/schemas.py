"""Schémas Pydantic v2 — entrées/sorties API MG-VMS."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

DEFAULT_PERMISSIONS = {
    "view_live": True,
    "view_recordings": True,
    "read_anpr": True,
    "stream_hd": True,
    "ptz_control": False,
    "export_files": False,
}


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth ----------
class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class RegisterIn(LoginIn):
    name: str = Field(min_length=2, max_length=160)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str


# ---------- Users ----------
class UserOut(ORMModel):
    id: UUID
    email: EmailStr
    name: str
    role_id: int
    permissions: dict
    active: bool
    org_id: UUID | None = None
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str
    role_id: int = 3
    permissions: dict = Field(default_factory=lambda: dict(DEFAULT_PERMISSIONS))
    site_ids: list[UUID] = Field(default_factory=list)


class UserUpdate(BaseModel):
    name: str | None = None
    role_id: int | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8)
    permissions: dict | None = None
    site_ids: list[UUID] | None = None


# ---------- Organizations / Sites ----------
class OrgIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)


class OrgOut(ORMModel):
    id: UUID
    name: str
    created_at: datetime


class SiteIn(BaseModel):
    name: str
    type: str = "site"
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    org_id: UUID | None = None


class SiteOut(ORMModel):
    id: UUID
    name: str
    type: str
    address: str | None
    lat: float | None
    lng: float | None
    org_id: UUID | None
    created_at: datetime


# ---------- Cameras / Streams ----------
class CameraIn(BaseModel):
    site_id: UUID
    name: str
    ip: str | None = None
    port: int = 554
    protocol: str = "RTSP"
    codec: str = "H264"
    rtsp_url: str | None = None
    onvif_url: str | None = None
    model: str | None = None
    username: str | None = None
    ptz_enabled: bool = False
    lat: float | None = None
    lng: float | None = None


class CameraUpdate(BaseModel):
    name: str | None = None
    rtsp_url: str | None = None
    onvif_url: str | None = None
    ptz_enabled: bool | None = None
    status: str | None = None
    lat: float | None = None
    lng: float | None = None


class CameraOut(ORMModel):
    id: UUID
    site_id: UUID
    name: str
    ip: str | None
    port: int
    protocol: str
    codec: str
    rtsp_url: str | None
    onvif_url: str | None
    model: str | None
    ptz_enabled: bool
    lat: float | None
    lng: float | None
    status: str
    last_seen: datetime | None
    created_at: datetime


class StreamIn(BaseModel):
    camera_id: UUID
    profile: str = "main"
    url: str
    codec: str = "H264"
    resolution: str | None = None
    fps: int | None = None


class StreamOut(ORMModel):
    id: UUID
    camera_id: UUID
    profile: str
    url: str
    codec: str
    resolution: str | None
    fps: int | None
    status: str


# ---------- Recordings / Events ----------
class RecordingOut(ORMModel):
    id: UUID
    camera_id: UUID
    start_ts: datetime
    end_ts: datetime | None
    path: str
    size_bytes: int
    codec: str
    status: str


class EventOut(ORMModel):
    id: UUID
    type: str
    camera_id: UUID | None
    site_id: UUID | None
    severity: str
    data: dict
    thumbnail_url: str | None
    acknowledged: bool
    ts: datetime


class EventIn(BaseModel):
    type: str
    camera_id: UUID | None = None
    site_id: UUID | None = None
    severity: str = "info"
    data: dict = Field(default_factory=dict)
    thumbnail_url: str | None = None


# ---------- AI ----------
class AIRuleIn(BaseModel):
    camera_id: UUID
    type: str
    name: str
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class AIRuleOut(ORMModel):
    id: UUID
    camera_id: UUID
    type: str
    name: str
    config: dict
    enabled: bool
    created_at: datetime


# ---------- Notifications ----------
class ChannelIn(BaseModel):
    type: str
    name: str
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class ChannelOut(ORMModel):
    id: UUID
    type: str
    name: str
    config: dict
    enabled: bool


# ---------- Storage ----------
class VolumeIn(BaseModel):
    name: str
    type: str = "local"
    path: str | None = None
    capacity_gb: float | None = None
    config: dict = Field(default_factory=dict)


class VolumeOut(ORMModel):
    id: UUID
    name: str
    type: str
    path: str | None
    capacity_gb: float | None
    used_gb: float
    config: dict


# ---------- Maps ----------
class FloorPlanIn(BaseModel):
    site_id: UUID
    name: str
    image_url: str | None = None
    camera_positions: dict = Field(default_factory=dict)


class FloorPlanOut(ORMModel):
    id: UUID
    site_id: UUID
    name: str
    image_url: str | None
    camera_positions: dict


# ---------- Settings / Audit ----------
class SettingIn(BaseModel):
    value: dict


class SettingOut(ORMModel):
    key: str
    value: dict
    updated_at: datetime


class AuditOut(ORMModel):
    id: int
    user_email: str | None
    action: str
    target: str | None
    details: str | None
    ip: str | None
    ts: datetime
