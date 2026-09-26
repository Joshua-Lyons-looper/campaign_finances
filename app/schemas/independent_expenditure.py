from pydantic import BaseModel


class IndependentExpenditureSummary(BaseModel):
    candidate_id: str
    cycle: int
    support: float
    oppose: float
    total: float