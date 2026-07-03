"""Modèles SQLAlchemy 2.0 — schéma PostgreSQL MG-VMS (source de vérité, migré par Alembic)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, SmallInteger,
    String, Text, func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(160), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    level: Mapped[int] = mapped_column(SmallInteger)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(160))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    role: Mapped["Role"] = relationship(lazy="joined")


class UserSite(Base):
    __tablename__ = "user_sites"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True)


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str] = mapped_column(String(60), default="site")
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[uuid.UUID] = _uuid_pk()
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    port: Mapped[int] = mapped_column(Integer, default=554)
    protocol: Mapped[str] = mapped_column(String(10), default="RTSP")
    codec: Mapped[str] = mapped_column(String(10), default="H264")
    rtsp_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    onvif_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    ptz_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="offline", index=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    streams: Mapped[list["Stream"]] = relationship(back_populates="camera", cascade="all, delete-orphan")


class Stream(Base):
    __tablename__ = "streams"
    id: Mapped[uuid.UUID] = _uuid_pk()
    camera_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    profile: Mapped[str] = mapped_column(String(10), default="main")  # main | sub
    url: Mapped[str] = mapped_column(Text)
    codec: Mapped[str] = mapped_column(String(10), default="H264")
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="stopped")
    camera: Mapped["Camera"] = relationship(back_populates="streams")


class Recording(Base):
    __tablename__ = "recordings"
    id: Mapped[uuid.UUID] = _uuid_pk()
    camera_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    path: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    codec: Mapped[str] = mapped_column(String(10), default="H264")
    status: Mapped[str] = mapped_column(String(12), default="recording")  # recording|closed|archived
    storage_volume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("storage_volumes.id"), nullable=True)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    type: Mapped[str] = mapped_column(String(40), index=True)  # motion|intrusion|line_crossing|object|anpr...
    camera_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(12), default="info")
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Plate(Base):
    __tablename__ = "plates"
    id: Mapped[uuid.UUID] = _uuid_pk()
    plate: Mapped[str] = mapped_column(String(16), index=True)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    country: Mapped[str | None] = mapped_column(String(4), nullable=True)
    vehicle_color: Mapped[str | None] = mapped_column(String(24), nullable=True)
    vehicle_make: Mapped[str | None] = mapped_column(String(40), nullable=True)
    vehicle_model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    vehicle_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    list_status: Mapped[str] = mapped_column(String(8), default="none")
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class AIRule(Base):
    __tablename__ = "ai_rules"
    id: Mapped[uuid.UUID] = _uuid_pk()
    camera_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(30))  # intrusion|line_crossing|object_detection|anpr
    name: Mapped[str] = mapped_column(String(120))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)  # zones, lignes, classes, seuils
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationChannel(Base):
    __tablename__ = "notification_channels"
    id: Mapped[uuid.UUID] = _uuid_pk()
    type: Mapped[str] = mapped_column(String(20))  # email|discord|telegram|webhook
    name: Mapped[str] = mapped_column(String(120))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class StorageVolume(Base):
    __tablename__ = "storage_volumes"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(10), default="local")  # local | s3
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    capacity_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    used_gb: Mapped[float] = mapped_column(Float, default=0)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)


class FloorPlan(Base):
    __tablename__ = "floor_plans"
    id: Mapped[uuid.UUID] = _uuid_pk()
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_positions: Mapped[dict] = mapped_column(JSONB, default=dict)  # {camera_id: {x, y, angle}}


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    identifier: Mapped[str] = mapped_column(String(320), primary_key=True)  # "{ip}:{email}"
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)
