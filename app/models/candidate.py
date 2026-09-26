from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    fec_candidate_id: Mapped[str] = mapped_column(
        String,
        unique=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String)

    party: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    office: Mapped[str] = mapped_column(String)

    state: Mapped[str | None] = mapped_column(
        String(2),
        nullable=True,
    )

    district: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )