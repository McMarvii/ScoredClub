"""SQLAlchemy ORM models.

Queryable/filterable fields get typed columns; the full nested profile is
stored in a portable JSON column (works on SQLite and PostgreSQL alike).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"

    entity_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="club")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    district: Mapped[str | None] = mapped_column(String(128))
    tier: Mapped[str | None] = mapped_column(String(32))
    current_score: Mapped[float | None] = mapped_column(Float)
    last_event_date: Mapped[date | None] = mapped_column(Date)
    profile: Mapped[dict] = mapped_column(JSON, nullable=False)
    first_seen_run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    aliases: Mapped[list["EntityAlias"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list["ScoreSnapshot"]] = relationship(back_populates="entity")


class EntityAlias(Base):
    __tablename__ = "entity_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.entity_id"), nullable=False)
    alias_normalized: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)

    entity: Mapped[Entity] = relationship(back_populates="aliases")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    entities_tracked: Mapped[int] = mapped_column(Integer, default=0)
    new_entities_found: Mapped[int] = mapped_column(Integer, default=0)
    report_md_path: Mapped[str | None] = mapped_column(String(512))
    report_json_path: Mapped[str | None] = mapped_column(String(512))

    snapshots: Mapped[list["ScoreSnapshot"]] = relationship(back_populates="run")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="run")


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"
    __table_args__ = (UniqueConstraint("run_id", "entity_id", name="uq_snapshot_run_entity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.entity_id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    tier: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)

    run: Mapped[Run] = relationship(back_populates="snapshots")
    entity: Mapped[Entity] = relationship(back_populates="snapshots")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.entity_id"), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(64))
    new_value: Mapped[str | None] = mapped_column(String(64))
    delta: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str] = mapped_column(String(512), nullable=False)
    webhook_delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    run: Mapped[Run] = relationship(back_populates="alerts")
