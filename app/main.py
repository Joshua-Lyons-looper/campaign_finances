"""FastAPI application entry point."""

import sqlite3
from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.ingestion_service import IngestionService
from app.models import (Candidate,
                        CandidateFinance,
                        OutsideSpending,ElectionResult,)
from app.database import get_db, Base, engine
from app.models.candidate import Candidate
from app.schemas.candidate import CandidateResponse
from app.services.fec_client import FECClient
from app.schemas.finance import CandidateFinanceResponse
from app.schemas.independent_expenditure import (
    IndependentExpenditureSummary,
)

Base.metadata.create_all(bind=engine)


app = FastAPI(title="Campaign Spending API",
              version="0.1.0",)


@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/candidates",
         response_model=list[CandidateResponse],)
def get_candidates(
    state: str,
    office: str,
    cycle: int,):
        fec = FECClient()

        return fec.get_candidates(
            state=state,
            office=office,
            cycle=cycle,
        )

@app.get("/candidates/{candidate_id}/finances",
    response_model=CandidateFinanceResponse | None,)
def get_candidate_finances(
    candidate_id: str,
    cycle: int,):
        
        fec = FECClient()
        return fec.get_candidate_finances(
            candidate_id=candidate_id,
            cycle=cycle,
        )

@app.get("/candidates/{candidate_id}/independent_expenditures",
    response_model=IndependentExpenditureSummary | None,)
def get_independent_expenditures(
    candidate_id: str,
    cycle: int,):
        fec = FECClient()
        return fec.get_independent_expenditures(
            candidate_id=candidate_id,
            cycle=cycle,
        )


@app.post("/ingest/candidate")
def ingest_candidate(
    state: str,
    office: str,
    cycle: int,
    db: Session = Depends(get_db),):
        fec = FECClient()
        ingestion = IngestionService(db)

        candidates = fec.get_candidates(
            state=state,
            office=office,
            cycle=cycle,
        )

        saved_candidates = []

        for candidate_data in candidates:
            candidate = ingestion.upsert_candidate(candidate_data)
            saved_candidates.append({
            "id": candidate.id,
            "fec_candidate_id": candidate.fec_candidate_id,
            "name": candidate.name,
        })
        return saved_candidates


@app.post("/ingest/candidate/{fec_candidate_id}/finances")
def ingest_candidate_finances(
    fec_candidate_id: str,
    cycle: int,
    db: Session = Depends(get_db),):
        candidate = db.scalar(
            select(Candidate).where(
                Candidate.fec_candidate_id == fec_candidate_id
            )
        )

        if candidate is None:
            raise HTTPException(
                status_code=404,
                detail="Candidate has not been ingested",
            )

        fec = FECClient()

        finance_data = fec.get_candidate_finances(
            candidate_id=fec_candidate_id,
            cycle=cycle,
        )

        if finance_data is None:
            raise HTTPException(
                status_code=404,
                detail="No finance data found",
            )

        ingestion = IngestionService(db)

        finance = ingestion.upsert_candidate_finance(
            candidate=candidate,
            finance_data=finance_data,
        )

        return {
            "id": finance.id,
            "candidate_id": finance.candidate_id,
            "fec_candidate_id": candidate.fec_candidate_id,
            "cycle": finance.cycle,
            "receipts": finance.receipts,
            "disbursements": finance.disbursements,
        }

@app.post("/ingest/candidate/{fec_candidate_id}/outside-spending")
def ingest_outside_spending(fec_candidate_id: str,cycle: int,db: Session = Depends(get_db),):
        candidate = db.scalar(
            select(Candidate).where(
                Candidate.fec_candidate_id == fec_candidate_id
            )
        )

        if candidate is None:
            raise HTTPException(
                status_code=404,
                detail="Candidate has not been ingested",
            )

        fec = FECClient()

        spending_data = fec.get_independent_expenditures(
            candidate_id=fec_candidate_id,
            cycle=cycle,
        )

        ingestion = IngestionService(db)

        spending = ingestion.upsert_outside_spending(
            candidate=candidate,
            spending_data=spending_data,
        )

        return {
            "id": spending.id,
            "candidate_id": spending.candidate_id,
            "fec_candidate_id": candidate.fec_candidate_id,
            "cycle": spending.cycle,
            "support": spending.support,
            "oppose": spending.oppose,
            "total": spending.support + spending.oppose,
        }

@app.post("/ingest/candidate/{fec_candidate_id}")
def ingest_candidate_cycle(fec_candidate_id: str,cycle: int,db: Session = Depends(get_db),):
        fec = FECClient()
        ingestion = IngestionService(db)

        try:
            result = ingestion.ingest_candidate_cycle(
                fec_candidate_id=fec_candidate_id,
                cycle=cycle,
                fec=fec,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=404,
                detail=str(exc),
            )

        candidate = result["candidate"]
        finance = result["finance"]
        spending = result["outside_spending"]

        return {
            "candidate": {
                "id": candidate.id,
                "fec_candidate_id": candidate.fec_candidate_id,
                "name": candidate.name,
            },
            "finance": {
                "cycle": finance.cycle,
                "receipts": finance.receipts,
                "disbursements": finance.disbursements,
            },
            "outside_spending": {
                "cycle": spending.cycle,
                "support": spending.support,
                "oppose": spending.oppose,
                "total": spending.support + spending.oppose,
            },
        }

@app.post("/ingest/race")
def ingest_race(
    state: str,
    office: str,
    cycle: int,
    db: Session = Depends(get_db),
):
    fec = FECClient()
    ingestion = IngestionService(db)

    result = ingestion.ingest_race(
        state=state,
        office=office,
        cycle=cycle,
        fec=fec,
    )

    return {
        "state": state.upper(),
        "office": office.upper(),
        "cycle": cycle,
        "saved_count": len(result["saved"]),
        "skipped_count": len(result["skipped"]),
        "saved": result["saved"],
        "skipped": result["skipped"],
    }

@app.get("/candidates/finance-summary")
def get_finance_summary(state: str,office: str,cycle: int,db: Session = Depends(get_db),):
        rows = db.execute(
            select(
                Candidate,
                CandidateFinance,
                OutsideSpending,
            )
            .join(
                CandidateFinance,
                Candidate.id == CandidateFinance.candidate_id,
            )
            .outerjoin(
                OutsideSpending,
                (Candidate.id == OutsideSpending.candidate_id)
                & (OutsideSpending.cycle == cycle),
            )
            .where(
                Candidate.state == state.upper(),
                Candidate.office == office.upper(),
                CandidateFinance.cycle == cycle,
            )
            .order_by(
                CandidateFinance.disbursements.desc()
            )
        ).all()

        results = []

        for candidate, finance, outside_spending in rows:
            other_receipts = (
                finance.receipts
                - finance.individual_contributions
                - finance.contributions_from_other_committees
            )


            results.append({
                "candidate_id": candidate.id,
                "fec_candidate_id": candidate.fec_candidate_id,
                "name": candidate.name,
                "party": candidate.party,

                "candidate_finances": {
                "receipts": finance.receipts,
                "spent": finance.disbursements,

                "funding_sources": {
                    "individuals": finance.individual_contributions,
                    "other_committees": (
                        finance.contributions_from_other_committees
                    ),
                    "other": other_receipts,},
                },
                "outside_spending": {
                    "support": (
                        outside_spending.support
                        if outside_spending
                        else 0
                    ),
                    "oppose": (
                        outside_spending.oppose
                        if outside_spending
                        else 0
                    ),
                },
            })

        return {
            "state": state.upper(),
            "office": office.upper(),
            "cycle": cycle,
            "candidates": results,
        }