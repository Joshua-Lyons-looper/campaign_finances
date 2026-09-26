from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ElectionResult(Base):
    __tablename__ = "election_results"

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

    election_type: Mapped[str] = mapped_column(
        String,
    )

    votes: Mapped[int] = mapped_column(
        Integer,
    )

    vote_share: Mapped[Decimal] = mapped_column(
        Numeric(6, 3),
    )