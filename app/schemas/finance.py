from pydantic import BaseModel
from decimal import Decimal


class CandidateFinanceResponse(BaseModel):
    candidate_id: str
    cycle: int

    receipts: Decimal
    disbursements: Decimal
    cash_on_hand: Decimal

    individual_contributions: Decimal
    contributions_from_other_committees: Decimal