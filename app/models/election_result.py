from decimal import Decimal

from sqlalchemy import Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ElectionResult(Base):
    __tablename__ = "election_results"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    fec_candidate_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        index=True,
    )

    cycle: Mapped[int] = mapped_column(
        Integer,
        index=True,
    )

    state: Mapped[str] = mapped_column(
        String(2),
        index=True,
    )

    office: Mapped[str] = mapped_column(
        String(1),
    )

    district: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    candidate_name: Mapped[str] = mapped_column(
        String,
    )

    party: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    general_votes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    general_percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 8),
        nullable=True,
    )

    general_winner: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )