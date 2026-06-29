"""MG-VMS — Modèles SQLAlchemy (PRODUCTION / PostgreSQL).

⚠️ Artefact de migration. Le backend de dev utilise MongoDB ; ces modèles sont
fournis pour la cible PostgreSQL (avec Alembic). SQLAlchemy 2.x style.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import (
    String, Integer, SmallInteger, Boolean, Float, BigInteger, Text,
    DateTime, ForeignKey, func,
)
from sqlalchemy.dialects.postgresql import UUID, INET, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    level: Mapped[int] = mapped_column(SmallInteger)


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str] = mapped_column(String(60))
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cameras: Mapped[list["Camera"]] = relationship(back_populates="site", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(160))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    twofa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    twofa_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSite(Base):
    __tablename__ = "user_sites"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True)


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[uuid.UUID] = pk()
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    port: Mapped[int] = mapped_column(Integer, default=554)
    protocol: Mapped[str] = mapped_column(String(10), default="RTSP")
    codec: Mapped[str] = mapped_column(String(10), default="H264")
    rtsp_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    ptz_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="offline", index=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    site: Mapped["Site"] = relationship(back_populates="cameras")


class Plate(Base):
    __tablename__ = "plates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[uuid.UUID] = pk()
    type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(12), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class Plugin(Base):
    __tablename__ = "plugins"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    core: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
