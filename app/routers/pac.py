"""PAC endpoints are independent of House/Senate election analytics."""
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from zipfile import BadZipFile
from app.database import get_db
from app.services.pac_bulk_importer import PACBulkImporter
from app.services.pac_ingestion_service import PACIngestionService
from app.services.pac_analytics_service import PACAnalyticsService

router = APIRouter()
Cycle = Annotated[int, Query(ge=1980, le=2098)]


def validate_cycle(cycle):
    if cycle % 2:
        raise HTTPException(422, 'cycle must be an even two-year FEC cycle')


class CategoryMapping(BaseModel):
    committee_id: str = Field(pattern=r'^C\d{8}$')
    committee_name: str | None = None
    category: str = Field(min_length=1, max_length=200)
    subcategory: str | None = None

    @field_validator('category')
    @classmethod
    def clean_category(cls, value):
        value = value.strip()
        if not value or value.lower() == 'unclassified':
            raise ValueError('Provide an explicit category; unclassified is reserved')
        return value


class RecordResolution(BaseModel):
    sub_id: str = Field(pattern=r'^\d+$')
    status: Literal['current', 'superseded', 'unresolved']


class SnapshotResolution(BaseModel):
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source: str = Field(min_length=1)  # provenance of record-level adjudication
    records: list[RecordResolution]


@router.get('/analytics/pac-categories')
def pac_categories(cycle: Cycle, category: str | None = None,
                   party: str | None = None,
                   state: Annotated[str | None, Query(pattern=r'^[A-Za-z]{2}$')] = None,
                   db: Session = Depends(get_db)):
    validate_cycle(cycle)
    return PACAnalyticsService(db).aggregate(cycle, category, party, state)


@router.put('/pac/categories')
def map_categories(mappings: list[CategoryMapping], db: Session = Depends(get_db)):
    if len({row.committee_id for row in mappings}) != len(mappings):
        raise HTTPException(422, 'Duplicate committee ID')
    return PACIngestionService(db).map_categories(mappings)


@router.post('/ingest/bulk/pac-contributions/{cycle}')
def ingest_pac(cycle: int, db: Session = Depends(get_db)):
    validate_cycle(cycle)
    if not 1980 <= cycle <= 2098:
        raise HTTPException(422, 'cycle out of range')
    try:
        return PACIngestionService(db).ingest_cycle(cycle, PACBulkImporter())
    except (ValueError, ArithmeticError, IntegrityError, BadZipFile) as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, 'Required cm, cn, or pas2 ZIP missing from data directory') from exc


@router.put('/pac/contributions/{cycle}/resolution')
def resolve_pac(cycle: int, resolution: SnapshotResolution, db: Session = Depends(get_db)):
    validate_cycle(cycle)
    try:
        return PACIngestionService(db).resolve(cycle, resolution)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
