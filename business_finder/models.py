from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from business_finder.database import Base


class WebsiteStatus(str, Enum):
    NO_SITE = "no_site"
    SOCIAL_ONLY = "social_only"
    THIRD_PARTY_PLATFORM = "third_party_platform"
    BROKEN = "broken"
    LIVE = "live"
    UNKNOWN = "unknown"


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    SKIP = "skip"


class OutreachStatus(str, Enum):
    NOT_CONTACTED = "not_contacted"
    CONTACTED = "contacted"
    REPLIED = "replied"
    NOT_INTERESTED = "not_interested"
    CONVERTED = "converted"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(120))
    included_type: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(12))
    max_pages: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    results_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    high_priority_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    leads: Mapped[list["Lead"]] = relationship(back_populates="scan", cascade="all, delete-orphan")

    def __str__(self) -> str:
        return f"{self.query} ({self.created_at:%Y-%m-%d})"


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("scan_id", "place_id", name="uq_leads_scan_place"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id"), nullable=False)
    place_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(255))
    email_source: Mapped[str | None] = mapped_column(String(80))
    google_maps_uri: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    website_final_url: Mapped[str | None] = mapped_column(Text)
    website_status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    http_status_code: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)
    business_status: Mapped[str | None] = mapped_column(String(80))
    primary_type: Mapped[str | None] = mapped_column(String(120))
    types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="low", nullable=False)
    outreach_status: Mapped[str] = mapped_column(String(40), default="not_contacted", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    redirect_chain: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    scan: Mapped[Scan] = relationship(back_populates="leads")

    def __str__(self) -> str:
        return self.name
