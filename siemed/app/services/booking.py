from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.events import bus
from app.models import Booking, Group, Lesson, Slot
from app.timeutil import as_local, now, tz


def active_booking_for_slot(db: Session, slot: Slot) -> Booking | None:
    if slot.booking and slot.booking.cancelled_at is None:
        return slot.booking
    return None


def free_slots(db: Session, after: datetime | None = None) -> list[Slot]:
    t = after or now()
    rows = (
        db.query(Slot)
        .options(joinedload(Slot.lesson), joinedload(Slot.bookings).joinedload(Booking.group))
        .filter(Slot.closed.is_(False), Slot.starts_at > t)
        .order_by(Slot.starts_at)
        .all()
    )
    return [s for s in rows if s.lesson.published and active_booking_for_slot(db, s) is None]


def create_booking(db: Session, slot_id: int, group_id: int, fio: str) -> Booking:
    fio = " ".join(fio.split())
    if len(fio) < 5:
        raise ValueError("Укажите фамилию, имя и отчество")
    group = db.get(Group, group_id)
    if not group or group.hidden:
        raise ValueError("Группа недоступна")
    slot = db.get(Slot, slot_id)
    if not slot or slot.closed:
        raise ValueError("Слот недоступен")
    if as_local(slot.starts_at) <= now():
        raise ValueError("Этот слот уже начался")
    if not slot.lesson.published:
        raise ValueError("Занятие скрыто")
    if active_booking_for_slot(db, slot):
        raise ValueError("Слот уже занят")
    code = booking_code()
    while db.query(Booking).filter(Booking.code == code).first():
        code = booking_code()
    row = Booking(
        slot_id=slot.id,
        group_id=group.id,
        fio=fio,
        code=code,
        created_at=now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def find_booking(db: Session, code: str | None = None, group_id: int | None = None, fio: str | None = None) -> Booking | None:
    q = db.query(Booking).options(
        joinedload(Booking.slot).joinedload(Slot.lesson),
        joinedload(Booking.group),
    )
    if code:
        return q.filter(Booking.code == code.strip().upper(), Booking.cancelled_at.is_(None)).first()
    if group_id and fio:
        needle = " ".join(fio.split()).lower()
        rows = q.filter(Booking.group_id == group_id, Booking.cancelled_at.is_(None)).all()
        for r in rows:
            if r.fio.lower() == needle:
                return r
    return None


def can_cancel(db: Session, booking: Booking) -> tuple[bool, str]:
    if booking.cancelled_at:
        return False, "Запись уже отменена"
    start = as_local(booking.slot.starts_at)
    lead = get_int(db, "cancel_lead_hours", 24)
    if now() > start - timedelta(hours=lead):
        return False, f"Отмена возможна не позднее чем за {lead} ч. до начала. Обратитесь к администратору."
    return True, ""


def cancel_booking(db: Session, booking: Booking, reason: str = "student") -> None:
    ok, msg = can_cancel(db, booking)
    if reason == "student" and not ok:
        raise ValueError(msg)
    booking.cancelled_at = now()
    booking.cancel_reason = reason
    db.commit()


def booking_in_grace(db: Session, booking: Booking) -> bool:
    if booking.cancelled_at:
        return False
    start = as_local(booking.slot.starts_at)
    end = as_local(booking.slot.ends_at)
    grace = timedelta(minutes=get_int(db, "slot_grace_minutes", 5))
    t = now()
    return (start - grace) <= t <= (end + grace)
