from decimal import Decimal

from sqlalchemy import (
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CandidateFinance(Base):
    __tablename__ = "candidate_finances"

    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "cycle",
            name="uq_candidate_finance_candidate_cycle",
        ),
    )

    id: Mapped[int] = mapped_column(Integer,primary_key=True,)

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id"),
        index=True,
    )

    cycle: Mapped[int] = mapped_column(
        Integer,
        index=True,
    )

    receipts: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
    )

    disbursements: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
    )

    cash_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
    )

    individual_contributions: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
    )

    contributions_from_other_committees: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
    )