"""SQLAlchemy models. SQLite for the pilot; set DATABASE_URL=postgresql+psycopg://... for production."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Engine, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite drops tzinfo on round-trip; normalise before comparing."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class Patient(Base):
    __tablename__ = "patients"
    wa_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(120))
    consent_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    opted_out: Mapped[int] = mapped_column(Integer, default=0)
    doctor_last_reply_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wa_message_id: Mapped[Optional[str]] = mapped_column(String(128), unique=True, index=True)
    patient_wa_id: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(8))          # in | out | echo (doctor's own app reply)
    body: Mapped[str] = mapped_column(Text, default="")
    media_type: Mapped[Optional[str]] = mapped_column(String(32))
    media_id: Mapped[Optional[str]] = mapped_column(String(128))
    classification: Mapped[Optional[str]] = mapped_column(String(16))
    action: Mapped[Optional[str]] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_wa_id: Mapped[str] = mapped_column(String(32), index=True)
    patient_text: Mapped[str] = mapped_column(Text)
    proposed_reply: Mapped[str] = mapped_column(Text)
    note_for_doctor: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")   # pending | approved | edited | discarded
    final_reply: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256))


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(String(64))
    patient_wa_id: Mapped[Optional[str]] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def normalize_database_url(database_url: str) -> str:
    """Map bare `postgres://` / `postgresql://` URLs onto the psycopg 3 driver (the only Postgres driver we ship)."""
    for prefix in ("postgres://", "postgresql://"):
        if database_url.startswith(prefix):
            return "postgresql+psycopg://" + database_url[len(prefix):]
    return database_url


def make_engine(database_url: str) -> Engine:
    """Build an engine without touching the database. SQLite gets thread-sharing; Postgres gets pool health checks."""
    url = normalize_database_url(database_url)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False}, future=True)
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, future=True)


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = make_engine(database_url)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_setting(db: Session, key: str, default: str) -> str:
    row = db.get(Setting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.commit()


def audit(db: Session, event: str, patient_wa_id: Optional[str] = None, detail: str = "") -> None:
    db.add(AuditLog(event=event, patient_wa_id=patient_wa_id, detail=detail[:4000]))
    db.commit()


def recent_history(db: Session, patient_wa_id: str, limit: int = 20) -> list[Message]:
    rows = db.scalars(
        select(Message)
        .where(Message.patient_wa_id == patient_wa_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))
