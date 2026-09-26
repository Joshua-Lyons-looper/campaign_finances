from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.candidate import Candidate
from app.models.outside_spending import OutsideSpending
from app.schemas import finance
from app.schemas.candidate import CandidateResponse
from app.models.candidate_finance import CandidateFinance
from app.schemas.finance import CandidateFinanceResponse
from app.schemas.independent_expenditure import (
    IndependentExpenditureSummary,
)
from app.services.fec_client import FECClient

class IngestionService:
    def __init__(self, db: Session):
        self.db = db

    def upsert_candidate(self,candidate_data: CandidateResponse,) -> Candidate:

        candidate = self.db.scalar(
            select(Candidate).where(
                Candidate.fec_candidate_id
                == candidate_data.candidate_id
            )
        )

        if candidate is None:
            candidate = Candidate(
                fec_candidate_id=candidate_data.candidate_id,
                name=candidate_data.name,
                party=candidate_data.party,
                office=candidate_data.office,
                state=candidate_data.state,
                district=candidate_data.district,
            )

            self.db.add(candidate)

        else:
            candidate.name = candidate_data.name
            candidate.party = candidate_data.party
            candidate.office = candidate_data.office
            candidate.state = candidate_data.state
            candidate.district = candidate_data.district

        self.db.commit()
        self.db.refresh(candidate)

        return candidate

    def upsert_candidate_finance(self,candidate: Candidate,finance_data: CandidateFinanceResponse,) -> CandidateFinance:

        finance = self.db.scalar(
            select(CandidateFinance).where(
                CandidateFinance.candidate_id == candidate.id,
                CandidateFinance.cycle == finance_data.cycle,
            )
        )

        if finance is None:
            finance = CandidateFinance(
                candidate_id=candidate.id,
                cycle=finance_data.cycle,
                receipts=finance_data.receipts,
                disbursements=finance_data.disbursements,
                cash_on_hand=finance_data.cash_on_hand,
                individual_contributions=(
                    finance_data.individual_contributions
                ),
                contributions_from_other_committees=(
                    finance_data.contributions_from_other_committees
                ),
            )

            self.db.add(finance)

        else:
            finance.receipts = finance_data.receipts
            finance.disbursements = finance_data.disbursements
            finance.cash_on_hand = finance_data.cash_on_hand
            finance.individual_contributions = (
                finance_data.individual_contributions
            )
            finance.contributions_from_other_committees = (
                finance_data.contributions_from_other_committees
            )

        self.db.commit()
        self.db.refresh(finance)

        return finance

    def upsert_outside_spending(
    self,
    candidate: Candidate,
    spending_data: IndependentExpenditureSummary,
) -> OutsideSpending:

        spending = self.db.scalar(
            select(OutsideSpending).where(
                OutsideSpending.candidate_id == candidate.id,
                OutsideSpending.cycle == spending_data.cycle,
            )
        )

        if spending is None:
            spending = OutsideSpending(
                candidate_id=candidate.id,
                cycle=spending_data.cycle,
                support=spending_data.support,
                oppose=spending_data.oppose,
            )

            self.db.add(spending)

        else:
            spending.support = spending_data.support
            spending.oppose = spending_data.oppose

        self.db.commit()
        self.db.refresh(spending)

        return spending

    def ingest_candidate_cycle(
    self,
    fec_candidate_id: str,
    cycle: int,
    fec: FECClient,
) -> dict:

        candidate = self.db.scalar(
            select(Candidate).where(
                Candidate.fec_candidate_id == fec_candidate_id
            )
        )

        if candidate is None:
            raise ValueError(
                f"Candidate {fec_candidate_id} has not been ingested"
            )

        finance_data = fec.get_candidate_finances(
            candidate_id=fec_candidate_id,
            cycle=cycle,
        )

        if finance_data is None:
            raise ValueError(
                f"No finance data found for {fec_candidate_id}"
            )

        spending_data = fec.get_independent_expenditures(
            candidate_id=fec_candidate_id,
            cycle=cycle,
        )

        finance = self.upsert_candidate_finance(
            candidate=candidate,
            finance_data=finance_data,
        )

        spending = self.upsert_outside_spending(
            candidate=candidate,
            spending_data=spending_data,
        )

        return {
            "candidate": candidate,
            "finance": finance,
            "outside_spending": spending,
        }

    def ingest_race(
    self,
    state: str,
    office: str,
    cycle: int,
    fec: FECClient,
) -> dict:

        candidates = fec.get_candidates(
            state=state,
            office=office,
            cycle=cycle,
        )

        saved = []
        skipped = []

        for candidate_data in candidates:

            # Save/update candidate first
            candidate = self.upsert_candidate(
                candidate_data
            )

            # Get candidate-controlled finances
            finance_data = fec.get_candidate_finances(
                candidate_id=candidate.fec_candidate_id,
                cycle=cycle,
            )

            # Some FEC candidate records may not have finance data
            if finance_data is None:
                skipped.append({
                    "fec_candidate_id": candidate.fec_candidate_id,
                    "name": candidate.name,
                    "reason": "No finance data",
                })
                continue

            finance = self.upsert_candidate_finance(
                candidate=candidate,
                finance_data=finance_data,
            )

            # Get outside spending
            spending_data = fec.get_independent_expenditures(
                candidate_id=candidate.fec_candidate_id,
                cycle=cycle,
            )

            spending = self.upsert_outside_spending(
                candidate=candidate,
                spending_data=spending_data,
            )

            saved.append({
                "candidate_id": candidate.id,
                "fec_candidate_id": candidate.fec_candidate_id,
                "name": candidate.name,
                "finance_id": finance.id,
                "outside_spending_id": spending.id,
            })

        return {
            "saved": saved,
            "skipped": skipped,
        }