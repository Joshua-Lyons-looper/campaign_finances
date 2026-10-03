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
from app.models.election_result import ElectionResult

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

    def ingest_bulk_cycle(self,cycle: int,bulk_importer,) -> dict:
        candidates = bulk_importer.read_candidates(
            cycle=cycle,
        )
        finances = bulk_importer.read_candidate_finances(
            cycle=cycle,
        )
        saved = []
        skipped = []
        for candidate_data in candidates:
            if candidate_data["election_year"] != str(cycle):
                continue
            candidate_response = CandidateResponse(
                candidate_id=candidate_data["candidate_id"],
                name=candidate_data["name"],
                party=candidate_data["party"],
                office=candidate_data["office"],
                state=candidate_data["state"],
                district=candidate_data["district"],
            )

            candidate = self.upsert_candidate(
                candidate_response
            )

            finance_data = finances.get(
                candidate_data["candidate_id"]
            )

            if finance_data is None:
                skipped.append({
                    "candidate_id": candidate_data["candidate_id"],
                    "name": candidate_data["name"],
                    "reason": "No financial summary",
                })
                continue

            finance_response = CandidateFinanceResponse(
                candidate_id=candidate_data["candidate_id"],
                cycle=cycle,
                receipts=finance_data["receipts"],
                disbursements=finance_data["disbursements"],
                cash_on_hand=finance_data["cash_on_hand"],
                individual_contributions=finance_data[
                    "individual_contributions"
                ],
                contributions_from_other_committees=finance_data[
                    "other_committee_contributions"
                ],
            )

            self.upsert_candidate_finance(
                candidate=candidate,
                finance_data=finance_response,
            )

            saved.append({
                "candidate_id": candidate_data["candidate_id"],
                "name": candidate_data["name"],
            })

        return {
            "cycle": cycle,
            "saved_count": len(saved),
            "skipped_count": len(skipped),
            "saved": saved,
            "skipped": skipped,
        }

    def upsert_election_result(self,result_data: dict,) -> ElectionResult:

        existing = self.db.execute(
            select(ElectionResult).where(
                ElectionResult.fec_candidate_id
                == result_data["fec_candidate_id"],

                ElectionResult.cycle
                == result_data["cycle"],

                ElectionResult.state
                == result_data["state"],

                ElectionResult.office
                == result_data["office"],

                ElectionResult.district
                == result_data["district"],
            )
        ).scalar_one_or_none()

        if existing:
            existing.state = result_data["state"]
            existing.office = result_data["office"]
            existing.district = result_data["district"]
            existing.candidate_name = result_data["candidate_name"]
            existing.party = result_data["party"]
            existing.general_votes = result_data["general_votes"]
            existing.general_percentage = result_data[
                "general_percentage"
            ]
            existing.general_winner = result_data[
                "general_winner"
            ]

            self.db.commit()
            self.db.refresh(existing)

            return existing

        election_result = ElectionResult(
            fec_candidate_id=result_data["fec_candidate_id"],
            cycle=result_data["cycle"],
            state=result_data["state"],
            office=result_data["office"],
            district=result_data["district"],
            candidate_name=result_data["candidate_name"],
            party=result_data["party"],
            general_votes=result_data["general_votes"],
            general_percentage=result_data[
                "general_percentage"
            ],
            general_winner=result_data[
                "general_winner"
            ],
        )

        self.db.add(election_result)
        self.db.commit()
        self.db.refresh(election_result)

        return election_result


    def ingest_election_results(self,cycle: int,office: str,election_importer,) -> dict:

        results = election_importer.read_election_results(
            cycle=cycle,
            office=office,
        )

        saved = []

        for result_data in results:

            self.upsert_election_result(
                result_data=result_data,
            )

            saved.append({
                "fec_candidate_id":
                    result_data["fec_candidate_id"],
                "name":
                    result_data["candidate_name"],
                "state":
                    result_data["state"],
                "office":
                    result_data["office"],
            })

        return {
            "cycle": cycle,
            "office": office.upper(),
            "saved_count": len(saved),
            "saved": saved,
        }

    def ingest_bulk_outside_spending(self,cycle: int,bulk_importer,) -> dict:

        totals = (
            bulk_importer.read_independent_expenditure_totals(
                cycle=cycle,
            )
        )

        saved = []
        skipped = []

        for candidate_id, spending in totals.items():

            candidate = self.db.scalar(
                select(Candidate).where(
                    Candidate.fec_candidate_id == candidate_id
                )
            )

            if candidate is None:
                skipped.append({
                    "candidate_id": candidate_id,
                    "reason": "Candidate not found",
                })
                continue

            spending_data = IndependentExpenditureSummary(
                candidate_id=candidate_id,
                cycle=cycle,
                support=spending["support"],
                oppose=spending["oppose"],
                total=(
                    spending["support"]
                    + spending["oppose"]
                ),
            )

            self.upsert_outside_spending(
                candidate=candidate,
                spending_data=spending_data,
            )

            saved.append({
                "candidate_id": candidate_id,
                "support": spending["support"],
                "oppose": spending["oppose"],
            })

        return {
            "cycle": cycle,
            "saved_count": len(saved),
            "skipped_count": len(skipped),
            "saved": saved,
            "skipped": skipped,
        }