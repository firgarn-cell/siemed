from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)


class StaffUser(Base):
    __tablename__ = "staff_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="staff")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    video_path: Mapped[str] = mapped_column(String(500), default="")
    practice_limit_min: Mapped[int] = mapped_column(Integer, default=15)
    slot_minutes: Mapped[int] = mapped_column(Integer, default=30)
    published: Mapped[bool] = mapped_column(Boolean, default=False)


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)

    lesson: Mapped[Lesson] = relationship()
    bookings: Mapped[List["Booking"]] = relationship(back_populates="slot")

    @property
    def booking(self) -> Optional["Booking"]:
        for item in self.bookings:
            if item.cancelled_at is None:
                return item
        return None


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (UniqueConstraint("code", name="uq_booking_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), nullable=False)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    fio: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cancelled_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    cancel_reason: Mapped[str] = mapped_column(String(64), default="")

    slot: Mapped[Slot] = relationship(back_populates="bookings")
    group: Mapped[Group] = relationship()


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    user: Mapped[str] = mapped_column(String(64), default="")
    password: Mapped[str] = mapped_column(String(128), default="")
    rtsp: Mapped[str] = mapped_column(String(500), nullable=False)
    record_mode: Mapped[str] = mapped_column(String(32), default="practice")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PracticeSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    instruction_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="instruction")
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(64), default="")
    grade: Mapped[str] = mapped_column(String(8), default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    booking: Mapped[Booking] = relationship()
    files: Mapped[List["SessionFile"]] = relationship(back_populates="session")


class SessionFile(Base):
    __tablename__ = "session_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    camera_key: Mapped[str] = mapped_column(String(16), nullable=False)
    camera_title: Mapped[str] = mapped_column(String(80), default="")
    path: Mapped[str] = mapped_column(String(700), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    missing: Mapped[bool] = mapped_column(Boolean, default=False)
    lost_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    session: Mapped[PracticeSession] = relationship(back_populates="files")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    actor: Mapped[str] = mapped_column(String(80), default="system")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
