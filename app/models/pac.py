"""PAC identities, explicit taxonomy, and direct candidate transactions."""
from decimal import Decimal
from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PACCommittee(Base):
    __tablename__ = "pac_committees"
    __table_args__ = (UniqueConstraint("committee_id", "cycle"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    committee_id: Mapped[str] = mapped_column(String(9), index=True)
    cycle: Mapped[int] = mapped_column(Integer, index=True)
    committee_name: Mapped[str | None] = mapped_column(String, nullable=True)
    committee_type: Mapped[str | None] = mapped_column(String, nullable=True)


class PACCategory(Base):
    __tablename__ = "pac_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    committee_id: Mapped[str] = mapped_column(String(9), unique=True, index=True)
    committee_name: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str] = mapped_column(String, index=True)
    subcategory: Mapped[str | None] = mapped_column(String, nullable=True)


class PACContribution(Base):
    __tablename__ = "pac_contributions"
    __table_args__ = (UniqueConstraint("cycle", "sub_id"), {"sqlite_autoincrement": True})
    id: Mapped[int] = mapped_column(primary_key=True)
    committee_id: Mapped[str] = mapped_column(String(9), index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), nullable=True)
    fec_candidate_id: Mapped[str | None] = mapped_column(String(9), nullable=True, index=True)
    recipient_committee_id: Mapped[str | None] = mapped_column(String(9), nullable=True)
    cycle: Mapped[int] = mapped_column(Integer, index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    candidate_party: Mapped[str | None] = mapped_column(String, nullable=True)
    candidate_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    sub_id: Mapped[str] = mapped_column(String, index=True)
    transaction_id: Mapped[str | None] = mapped_column(String, nullable=True)
    file_number: Mapped[str | None] = mapped_column(String, nullable=True)
    amendment_indicator: Mapped[str | None] = mapped_column(String, nullable=True)
    transaction_type: Mapped[str] = mapped_column(String)
    memo_code: Mapped[str | None] = mapped_column(String, nullable=True)
    # Explicit record-level resolution also handles partial paper amendments.
    status: Mapped[str] = mapped_column(String, default="unresolved")
    resolution_source: Mapped[str | None] = mapped_column(String, nullable=True)


class PACImport(Base):
    __tablename__ = "pac_imports"
    cycle: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String)
