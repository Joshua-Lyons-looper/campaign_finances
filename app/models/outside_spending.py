from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OutsideSpending(Base):
    __tablename__ = "outside_spending"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id"),
        index=True,
    )

    cycle: Mapped[int] = mapped_column(
        Integer,
        index=True,
    )

    support: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
    )

    oppose: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
    )