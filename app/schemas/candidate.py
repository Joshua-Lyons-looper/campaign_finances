from pydantic import BaseModel


class CandidateResponse(BaseModel):
    candidate_id: str
    name: str
    party: str | None = None
    office: str
    state: str | None = None
    district: str | None = None