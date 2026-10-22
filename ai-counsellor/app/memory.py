"""SQLite memory (SQLAlchemy 2.x). Profile lists, mood log, messages, crisis state, clinician review queue."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    age_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    minor_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    onboarding_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    opened: Mapped[bool] = mapped_column(Boolean, default=False)          # opening message sent
    spiritual_pref: Mapped[str] = mapped_column(String(120), default="")
    what_helps: Mapped[str] = mapped_column(Text, default="[]")
    supports: Mapped[str] = mapped_column(Text, default="[]")
    triggers: Mapped[str] = mapped_column(Text, default="[]")
    safety_plan: Mapped[str] = mapped_column(Text, default="{}")
    crisis_state: Mapped[str] = mapped_column(Text, default="{}")
    last_risk: Mapped[str] = mapped_column(String(12), default="NONE")
    followup_due: Mapped[bool] = mapped_column(Boolean, default=False)   # proactive check-in next session
    session_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nudged_this_session: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list["Message"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    moods: Mapped[list["MoodLog"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    # ---- JSON helpers
    def get_list(self, field: str) -> list[str]:
        try:
            return list(json.loads(getattr(self, field) or "[]"))
        except json.JSONDecodeError:
            return []

    def add_to_list(self, field: str, items: list[str], cap: int = 12) -> None:
        cur = self.get_list(field)
        for it in items or []:
            it = (it or "").strip()
            if it and it.lower() not in {c.lower() for c in cur}:
                cur.append(it[:160])
        setattr(self, field, json.dumps(cur[-cap:], ensure_ascii=False))

    def get_safety_plan(self) -> dict:
        try:
            return dict(json.loads(self.safety_plan or "{}"))
        except json.JSONDecodeError:
            return {}

    def set_safety_plan(self, plan: dict) -> None:
        self.safety_plan = json.dumps(plan, ensure_ascii=False)

    def get_crisis_state(self) -> dict:
        try:
            return dict(json.loads(self.crisis_state or "{}"))
        except json.JSONDecodeError:
            return {}

    def set_crisis_state(self, d: dict) -> None:
        self.crisis_state = json.dumps(d, ensure_ascii=False)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))               # user | assistant
    content: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(12), default="NONE")
    mode: Mapped[str] = mapped_column(String(24), default="companion")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship(back_populates="messages")


class MoodLog(Base):
    __tablename__ = "mood_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    score: Mapped[float] = mapped_column(Float)                  # 1-10
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship(back_populates="moods")


class ReviewItem(Base):
    """Clinician review queue: every flagged turn lands here (Phase 3 builds the console on top)."""
    __tablename__ = "review_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    risk_level: Mapped[str] = mapped_column(String(12))
    categories: Mapped[str] = mapped_column(Text, default="[]")
    user_text: Mapped[str] = mapped_column(Text)
    reply_text: Mapped[str] = mapped_column(Text)
    handoff_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_or_create_user(db: Session, external_id: str) -> User:
    u = db.scalar(select(User).where(User.external_id == external_id))
    if not u:
        u = User(external_id=external_id)
        db.add(u)
        db.commit()
    return u


def recent_messages(db: Session, user: User, limit: int = 20) -> list[dict]:
    rows = db.scalars(select(Message).where(Message.user_id == user.id).order_by(Message.id.desc()).limit(limit)).all()
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


def mood_summary(db: Session, user: User, limit: int = 7) -> str:
    rows = db.scalars(select(MoodLog).where(MoodLog.user_id == user.id).order_by(MoodLog.id.desc()).limit(limit)).all()
    if not rows:
        return "(no mood entries yet)"
    parts = [f"{r.created_at.date() if r.created_at else ''}: {r.score:g}/10" + (f" ({r.note})" if r.note else "") for r in reversed(rows)]
    return "; ".join(parts)


def delete_user_data(db: Session, external_id: str) -> bool:
    """DPDP: the user can delete everything."""
    u = db.scalar(select(User).where(User.external_id == external_id))
    if not u:
        return False
    for r in db.scalars(select(ReviewItem).where(ReviewItem.user_id == u.id)).all():
        db.delete(r)
    db.delete(u)
    db.commit()
    return True
