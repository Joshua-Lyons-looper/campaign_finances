"""FastAPI application entry point."""

import sqlite3
from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
from app.services.fec_bulk_importer import FECBulkImporter
from app.services.election_results_importer import ElectionResultsImporter
from app.models.election_result import ElectionResult
from app.services.analytics_service import AnalyticsService

from app.routers.pac import router as pac_router

Base.metadata.create_all(bind=engine)


app = FastAPI(title="Campaign Spending API",
              version="0.1.0",)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/bulk/datasets")
def get_bulk_datasets():

    importer = FECBulkImporter()

    return {
        "datasets": importer.list_datasets()
    }

@app.get("/bulk/candidates")
def get_bulk_candidates(cycle: int,state: str | None = None,office: str | None = None,):
    importer = FECBulkImporter()
    candidates = importer.read_candidates(cycle=cycle,)
    candidates = [
        candidate
        for candidate in candidates
        if candidate["election_year"] == str(cycle)
    ]
    if state:
        candidates = [
            candidate
            for candidate in candidates
            if candidate["state"] == state.upper()
        ]
    if office:
        candidates = [
            candidate
            for candidate in candidates
            if candidate["office"] == office.upper()
        ]
    return {
        "cycle": cycle,
        "count": len(candidates),
        "candidates": candidates,
    }

@app.get("/bulk/candidates/finances")
def get_bulk_candidate_finances(
    cycle: int,
    state: str,
    office: str,
):

    importer = FECBulkImporter()

    candidates = importer.read_candidates(
        cycle=cycle,
    )

    finances = importer.read_candidate_finances(
        cycle=cycle,
    )

    results = []

    for candidate in candidates:

        if candidate["election_year"] != str(cycle):
            continue

        if candidate["state"] != state.upper():
            continue

        if candidate["office"] != office.upper():
            continue

        finance = finances.get(
            candidate["candidate_id"]
        )

        results.append({
            **candidate,
            "finances": finance,
        })

    return {
        "cycle": cycle,
        "state": state.upper(),
        "office": office.upper(),
        "count": len(results),
        "candidates": results,
    }

@app.post("/ingest/bulk/candidates/{cycle}")
def ingest_bulk_cycle(cycle: int,db: Session = Depends(get_db),):
    importer = FECBulkImporter()
    ingestion_service = IngestionService(db)
    return ingestion_service.ingest_bulk_cycle(
        cycle=cycle,
        bulk_importer=importer,
    )

@app.get("/states/{state}/financial-activity")
def get_state_summary(
    state: str,
    cycle: int,
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(
            Candidate,
            CandidateFinance,
        )
        .join(
            CandidateFinance,
            Candidate.id == CandidateFinance.candidate_id,
        )
        .where(
            Candidate.state == state.upper(),
            CandidateFinance.cycle == cycle,
        )
        .order_by(
            Candidate.office,
            Candidate.district,
            CandidateFinance.disbursements.desc(),
        )
    ).all()

    senate = []
    house = {}

    for candidate, finance in rows:

        candidate_data = {
            "candidate_id": candidate.fec_candidate_id,
            "name": candidate.name,
            "party": candidate.party,
            "receipts": finance.receipts,
            "spent": finance.disbursements,
            "cash_on_hand": finance.cash_on_hand,
            "individual_contributions": finance.individual_contributions,
            "other_committee_contributions":
                finance.contributions_from_other_committees,
        }

        if candidate.office == "S":
            senate.append(candidate_data)

        elif candidate.office == "H":
            district = candidate.district or "00"

            if district not in house:
                house[district] = []

            house[district].append(candidate_data)

    return {
        "state": state.upper(),
        "cycle": cycle,
        "senate": senate,
        "house": house,
    }

@app.get("/bulk/election-results/sheets")
def get_election_result_sheets(
    cycle: int,
):
    importer = ElectionResultsImporter()

    return {
        "cycle": cycle,
        "sheets": importer.list_sheets(
            cycle=cycle,
        ),
    }

@app.get("/bulk/election-results/preview")
def preview_election_results(cycle: int,office: str,):
    importer = ElectionResultsImporter()

    office = office.upper()

    if office == "S":
        sheet_suffix = "US Senate Results by State"
    elif office == "H":
        sheet_suffix = "US House Results by State"
    elif office == "P":
        sheet_suffix = "Pres General Results"
    else:
        raise HTTPException(
            status_code=400,
            detail="office must be P, S, or H",
        )

    print("Getting sheet list...")

    sheets = importer.list_sheets(
        cycle=cycle,
    )

    print("Got sheet list")

    sheet_name = next(
        (
            name
            for name in sheets
            if name.endswith(sheet_suffix)
        ),
        None,
    )

    print(f"Found sheet: {sheet_name}")
    print("Starting preview...")

    rows = importer.preview_sheet(
        cycle=cycle,
        sheet_name=sheet_name,
        rows=20,
    )

    print("Finished preview")

    return {
        "cycle": cycle,
        "office": office,
        "sheet": sheet_name,
        "rows": rows,
    }

@app.get("/bulk/election-results")
def get_bulk_election_results(cycle: int,office: str,state: str | None = None,):
    importer = ElectionResultsImporter()
    try:
        results = importer.read_election_results(
            cycle=cycle,
            office=office,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )
    if state:
        results = [
            result
            for result in results
            if result["state"] == state.upper()
        ]
    return {
        "cycle": cycle,
        "state": state.upper() if state else None,
        "office": office.upper(),
        "count": len(results),
        "results": results,
    }

@app.post("/ingest/election-results/{cycle}")
def ingest_election_results(cycle: int,office: str,db: Session = Depends(get_db),):
    importer = ElectionResultsImporter()
    ingestion_service = IngestionService(db)

    try:
        return ingestion_service.ingest_election_results(
            cycle=cycle,
            office=office,
            election_importer=importer,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


@app.get("/races/{cycle}/{state}/{office}")
def get_race(cycle: int,state: str,office: str,district: str | None = None,db: Session = Depends(get_db),):
    state = state.upper()
    office = office.upper()

    query = (
        select(
            ElectionResult,
            Candidate,
            CandidateFinance,
            OutsideSpending,
        )
        .outerjoin(
            Candidate,
            Candidate.fec_candidate_id
            == ElectionResult.fec_candidate_id,
        )
        .outerjoin(
            CandidateFinance,
            (CandidateFinance.candidate_id == Candidate.id)
            & (CandidateFinance.cycle == cycle),
        )
        .outerjoin(
            OutsideSpending,
            (OutsideSpending.candidate_id == Candidate.id)
            & (OutsideSpending.cycle == cycle),
        )
        .where(
            ElectionResult.cycle == cycle,
            ElectionResult.state == state,
            ElectionResult.office == office,
        )
    )

    if office == "H":
        if district is None:
            raise HTTPException(
                status_code=400,
                detail="district is required for House races",
            )

        district = district.zfill(2)

        query = query.where(
            ElectionResult.district == district
        )

    elif office not in ("S", "P"):
        raise HTTPException(
            status_code=400,
            detail="office must be H, S, or P",
        )

    rows = db.execute(query).all()

    candidates = []

    for result, candidate, finance, outside_spending in rows:

        candidates.append({
            "fec_candidate_id": result.fec_candidate_id,
            "name": result.candidate_name,
            "party": result.party,

            "election": {
                "votes": result.general_votes,
                "vote_share": result.general_percentage,
                "winner": result.general_winner == "W",
            },

            "finance": {
                "receipts": finance.receipts,
                "spent": finance.disbursements,
                "cash_on_hand": finance.cash_on_hand,
                "individual_contributions":
                    finance.individual_contributions,
                "other_committee_contributions":
                    finance.contributions_from_other_committees,
            } if finance else None,
            "outside_spending": {
                "support": outside_spending.support,
                "oppose": outside_spending.oppose,
                "total": (
                    outside_spending.support
                    + outside_spending.oppose
                ),
            } if outside_spending else None,
        })

    return {
        "cycle": cycle,
        "state": state,
        "office": office,
        "district": district if office == "H" else None,

        "finance_scope": (
            "national"
            if office == "P"
            else "candidate_race"
        ),

        "candidates": candidates,
    }

@app.get("/states/{state}/summary")
def get_state_summary(state: str,cycle: int,db: Session = Depends(get_db),):
    state = state.upper()

    rows = db.execute(
        select(
            ElectionResult,
            Candidate,
            CandidateFinance,
            OutsideSpending,
        )
        .outerjoin(
            Candidate,
            Candidate.fec_candidate_id
            == ElectionResult.fec_candidate_id,
        )
        .outerjoin(
            CandidateFinance,
            (CandidateFinance.candidate_id == Candidate.id)
            & (CandidateFinance.cycle == cycle),
        )
        .outerjoin(
            OutsideSpending,
            (OutsideSpending.candidate_id == Candidate.id)
            & (OutsideSpending.cycle == cycle),
        )
        .where(
            ElectionResult.cycle == cycle,
            ElectionResult.state == state,
        )
        .order_by(
            ElectionResult.office,
            ElectionResult.district,
            ElectionResult.general_votes.desc(),
        )
    ).all()

    senate = []
    house = {}

    for result, candidate, finance, outside_spending in rows:

        candidate_data = {
            "fec_candidate_id": result.fec_candidate_id,
            "name": result.candidate_name,
            "party": result.party,

            "election": {
                "votes": result.general_votes,
                "vote_share": result.general_percentage,
                "winner": result.general_winner == "W",
            },

            "finance": {
                "receipts": finance.receipts,
                "spent": finance.disbursements,
                "cash_on_hand": finance.cash_on_hand,
                "individual_contributions":
                    finance.individual_contributions,
                "other_committee_contributions":
                    finance.contributions_from_other_committees,
            } if finance else None,
            "outside_spending": {
                "support": outside_spending.support,
                "oppose": outside_spending.oppose,
                "total": (
                    outside_spending.support
                    + outside_spending.oppose
                ),
            } if outside_spending else None,
        }

        if result.office == "S":
            senate.append(candidate_data)

        elif result.office == "H":
            district = result.district

            if district not in house:
                house[district] = []

            house[district].append(candidate_data)

    return {
        "state": state,
        "cycle": cycle,
        "senate": senate,
        "house": house,
    }

@app.get("/bulk/independent-expenditures")
def get_bulk_independent_expenditures(
    cycle: int,
):
    importer = FECBulkImporter()

    expenditures = (
        importer.read_independent_expenditures(
            cycle=cycle,
        )
    )

    return {
        "cycle": cycle,
        "count": len(expenditures),
        "sample": expenditures[:10],
    }

@app.get("/bulk/independent-expenditures/stats")
def get_independent_expenditure_stats(
    cycle: int,
):
    importer = FECBulkImporter()

    expenditures = (
        importer.read_independent_expenditures(
            cycle=cycle,
        )
    )

    amendment_counts = {}

    for expenditure in expenditures:
        indicator = expenditure[
            "amendment_indicator"
        ]

        amendment_counts[indicator] = (
            amendment_counts.get(indicator, 0) + 1
        )

    return {
        "cycle": cycle,
        "total_rows": len(expenditures),
        "amendment_counts": amendment_counts,
    }

@app.get("/bulk/independent-expenditures/amendments")
def get_independent_expenditure_amendments(
    cycle: int,
):
    importer = FECBulkImporter()

    expenditures = (
        importer.read_independent_expenditures(
            cycle=cycle,
        )
    )

    amendments = [
        expenditure
        for expenditure in expenditures
        if expenditure["amendment_indicator"] != "N"
    ]

    return {
        "cycle": cycle,
        "count": len(amendments),
        "sample": amendments[:20],
    }

@app.get("/bulk/independent-expenditures/filing-chain")
def get_independent_expenditure_filing_chain(cycle: int,file_number: str,):
    importer = FECBulkImporter()

    expenditures = (
        importer.read_independent_expenditures(
            cycle=cycle,
        )
    )

    related_file_numbers = {file_number}

    changed = True

    while changed:
        changed = False

        for expenditure in expenditures:
            current = expenditure["file_number"]
            previous = expenditure["previous_file_number"]

            if (
                current in related_file_numbers
                or previous in related_file_numbers
            ):
                before = len(related_file_numbers)

                if current:
                    related_file_numbers.add(current)

                if previous:
                    related_file_numbers.add(previous)

                if len(related_file_numbers) > before:
                    changed = True

    rows = [
        expenditure
        for expenditure in expenditures
        if expenditure["file_number"]
        in related_file_numbers
    ]

    return {
        "file_numbers": sorted(related_file_numbers),
        "count": len(rows),
        "rows": rows,
    }

@app.get("/bulk/independent-expenditures/current")
def get_current_independent_expenditures(
    cycle: int,
):
    importer = FECBulkImporter()

    all_rows = importer.read_independent_expenditures(
        cycle=cycle,
    )

    current_rows = (
        importer.read_current_independent_expenditures(
            cycle=cycle,
        )
    )

    return {
        "cycle": cycle,
        "original_count": len(all_rows),
        "current_count": len(current_rows),
        "removed_count": (
            len(all_rows) - len(current_rows)
        ),
        "sample": current_rows[:10],
    }

@app.get("/bulk/independent-expenditures/candidate")
def get_candidate_independent_expenditures(
    cycle: int,
    candidate_id: str,
):
    importer = FECBulkImporter()

    totals = (
        importer.read_independent_expenditure_totals(
            cycle=cycle,
        )
    )

    return totals.get(
        candidate_id.upper(),
        {
            "candidate_id": candidate_id.upper(),
            "support": 0,
            "oppose": 0,
        },
    )

@app.post("/ingest/bulk/outside-spending/{cycle}")
def ingest_bulk_outside_spending(
    cycle: int,
    db: Session = Depends(get_db),
):
    importer = FECBulkImporter()
    ingestion_service = IngestionService(db)

    return ingestion_service.ingest_bulk_outside_spending(
        cycle=cycle,
        bulk_importer=importer,
    )


@app.get("/bulk/{cycle}/summary")
def get_bulk_cycle_summary(cycle: int,):
    bulk_importer = FECBulkImporter()
    election_importer = ElectionResultsImporter()

    results = {
        "cycle": cycle,
        "candidates": None,
        "candidate_finances": None,
        "house_election_results": None,
        "senate_election_results": None,
        "independent_expenditures": None,
    }

    # Candidate master
    try:
        candidates = bulk_importer.read_candidates(
            cycle=cycle,
        )

        results["candidates"] = {
            "count": len(candidates),
            "status": "ok",
        }

    except FileNotFoundError:
        results["candidates"] = {
            "status": "missing",
        }

    # Candidate financial summaries
    try:
        finances = bulk_importer.read_candidate_finances(
            cycle=cycle,
        )

        results["candidate_finances"] = {
            "count": len(finances),
            "status": "ok",
        }

    except FileNotFoundError:
        results["candidate_finances"] = {
            "status": "missing",
        }

    # House election results
    try:
        house = election_importer.read_election_results(
            cycle=cycle,
            office="H",
        )

        results["house_election_results"] = {
            "count": len(house),
            "status": "ok",
        }

    except FileNotFoundError:
        results["house_election_results"] = {
            "status": "missing",
        }

    # Senate election results
    try:
        senate = election_importer.read_election_results(
            cycle=cycle,
            office="S",
        )

        results["senate_election_results"] = {
            "count": len(senate),
            "status": "ok",
        }

    except FileNotFoundError:
        results["senate_election_results"] = {
            "status": "missing",
        }

    # Independent expenditures
    try:
        outside = (
            bulk_importer
            .read_current_independent_expenditures(
                cycle=cycle,
            )
        )

        results["independent_expenditures"] = {
            "count": len(outside),
            "status": "ok",
        }

    except FileNotFoundError:
        results["independent_expenditures"] = {
            "status": "missing",
        }

    return results

@app.post("/ingest/bulk/{cycle}")
def ingest_complete_bulk_cycle(cycle: int,db: Session = Depends(get_db),):
    bulk_importer = FECBulkImporter()
    election_importer = ElectionResultsImporter()
    ingestion_service = IngestionService(db)

    # Candidates + candidate financial summaries
    candidate_result = ingestion_service.ingest_bulk_cycle(
        cycle=cycle,
        bulk_importer=bulk_importer,
    )

    # House election results
    house_result = ingestion_service.ingest_election_results(
        cycle=cycle,
        office="H",
        election_importer=election_importer,
    )

    # Senate election results
    senate_result = ingestion_service.ingest_election_results(
        cycle=cycle,
        office="S",
        election_importer=election_importer,
    )

    # Independent expenditures
    outside_spending_result = (
        ingestion_service.ingest_bulk_outside_spending(
            cycle=cycle,
            bulk_importer=bulk_importer,
        )
    )

    return {
        "cycle": cycle,
        "status": "complete",
        "candidates_and_finances": {
            "saved_count":
                candidate_result["saved_count"],
            "skipped_count":
                candidate_result["skipped_count"],
        },
        "house_election_results": {
            "saved_count":
                house_result["saved_count"],
        },
        "senate_election_results": {
            "saved_count":
                senate_result["saved_count"],
        },
        "outside_spending": {
            "saved_count":
                outside_spending_result["saved_count"],
            "skipped_count":
                outside_spending_result["skipped_count"],
        },
    }

@app.get("/analytics/states/{state}/house")
def get_state_house_analytics(
    state: str,
    cycle: int,
    db: Session = Depends(get_db),
):
    analytics_service = AnalyticsService(db)

    return analytics_service.get_state_house_party_totals(
        cycle=cycle,
        state=state,
    )

@app.get("/analytics/states/{state}/house/finances")
def get_state_house_finances(state: str,cycle: int,db: Session = Depends(get_db),):
    analytics_service = AnalyticsService(db)
    return analytics_service.get_state_house_party_finances(
        cycle=cycle,
        state=state,
    )

@app.get("/analytics/states/{state}/{office}/compare")
def compare_state_finances(
    state: str,
    office: str,
    from_cycle: int,
    to_cycle: int,
    db: Session = Depends(get_db),
):
    office_code = {"house": "H", "h": "H", "senate": "S", "s": "S"}.get(office.lower())
    if office_code is None:
        raise HTTPException(status_code=400, detail="office must be house, senate, H, or S")

    analytics_service = AnalyticsService(db)

    return analytics_service.compare_state_finances(
        state=state,
        office=office_code,
        from_cycle=from_cycle,
        to_cycle=to_cycle,
    )

@app.get("/analytics/states/{state}/house/outside-spending")
def get_state_house_outside_spending(
    state: str,
    cycle: int,
    db: Session = Depends(get_db),
):
    analytics_service = AnalyticsService(db)

    return analytics_service.get_state_house_party_outside_spending(
        cycle=cycle,
        state=state,
    )

@app.get("/analytics/data-coverage")
def get_data_coverage(
    state: str = "US",
    office: str | None = None,
    db: Session = Depends(get_db),
):
    office_code = None
    if office is not None:
        office_code = {"house": "H", "h": "H", "senate": "S", "s": "S"}.get(office.lower())
        if office_code is None:
            raise HTTPException(status_code=400, detail="office must be house, senate, H, or S")
    return AnalyticsService(db).get_data_coverage(state=state, office=office_code)


app.include_router(pac_router)
