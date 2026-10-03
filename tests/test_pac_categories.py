from decimal import Decimal
from pathlib import Path
import zipfile

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Candidate, ElectionResult
from app.models.pac import PACCommittee, PACCategory, PACContribution, PACImport
from app.services.pac_bulk_importer import PACBulkImporter
from app.services.pac_analytics_service import PACAnalyticsService
from app.services.pac_ingestion_service import PACIngestionService
from app.routers.pac import CategoryMapping, SnapshotResolution


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed(db):
    db.add(PACImport(cycle=2024, source_sha256='a' * 64))
    db.add(PACCommittee(committee_id='C00000001', cycle=2024, committee_type='Q'))
    db.add(PACCommittee(committee_id='C00000002', cycle=2024, committee_type='N'))
    db.add(PACCategory(committee_id='C00000001', category='Automotive'))
    db.flush()


def contribution(db, sub_id, amount, committee='C00000001', **kwargs):
    defaults = dict(cycle=2024, committee_id=committee, amount=amount, sub_id=str(sub_id),
                    fec_candidate_id='H00000001', candidate_party='REP',
                    candidate_state='NC', transaction_type='24K', status='current')
    db.add(PACContribution(**(defaults | kwargs)))
    db.flush()


def test_allocation_and_cycle_specific_party(db):
    seed(db)
    contribution(db, 1, 70)
    contribution(db, 2, 30, fec_candidate_id='H00000002', candidate_party='DEM')
    # Same-cycle election data outranks snapshot and never multiplies rows.
    for _ in range(2):
        db.add(ElectionResult(cycle=2024, fec_candidate_id='H00000002',
                              candidate_name='Test', party='D', office='H', state='NC'))
    db.flush()
    response = PACAnalyticsService(db).aggregate(2024)
    assert response['complete'] is True
    assert {party: {key: bucket[key] for key in ('amount', 'share')}
            for party, bucket in response['categories'][0]['parties'].items()} == {
        'D': {'amount': Decimal(30), 'share': .3}, 'R': {'amount': Decimal(70), 'share': .7}}
    assert response['categories'][0]['contributing_committees'] == 1
    assert PACAnalyticsService(db).aggregate(2022)['total_contributions'] is None


def test_unclassified_unknown_and_missing_are_retained(db):
    seed(db)
    contribution(db, 1, 40, committee='C00000002', candidate_party=None)
    response = PACAnalyticsService(db).aggregate(2024)
    assert response['categories'][0]['category'] == 'unclassified'
    assert response['categories'][0]['parties']['unknown']['amount'] == 40
    assert response['coverage']['unclassified']['amount'] == 40
    contribution(db, 2, None, committee='C00000002')
    response = PACAnalyticsService(db).aggregate(2024)
    assert response['categories'][0]['total_contributions'] is None
    assert response['categories'][0]['parties']['unknown']['share'] is None
    assert response['coverage']['missing_amount']['amount'] is None
    assert response['complete'] is False


def test_unresolved_superseded_memos_and_non_pacs_excluded(db):
    seed(db)
    contribution(db, 1, 500, status='superseded')
    contribution(db, 2, 999, status='unresolved')
    contribution(db, 3, 70)
    contribution(db, 4, 70, memo_code='X')
    contribution(db, 5, 800, committee='C99999999')
    db.add(PACCommittee(cycle=2024, committee_id='C00000003', committee_type='Y'))
    contribution(db, 6, 1000, committee='C00000003')
    response = PACAnalyticsService(db).aggregate(2024)
    assert response['total_contributions'] is None
    assert response['verified_known_amount'] == 70
    assert response['categories'][0]['parties']['R']['share'] is None
    assert response['complete'] is False
    assert response['coverage']['superseded']['amount'] == 500
    assert response['coverage']['unresolved_amendments']['amount'] == 999
    assert response['coverage']['memo_items']['amount'] == 70
    assert response['coverage']['unknown_committee_type']['amount'] == 800
    assert response['coverage']['excluded_non_pac']['amount'] == 1000


def test_filters_and_nonpositive_share(db):
    seed(db)
    contribution(db, 1, 100)
    contribution(db, 2, -100, candidate_party='D', candidate_state='VA')
    assert PACAnalyticsService(db).aggregate(2024)['categories'][0]['parties']['R']['share'] is None
    assert PACAnalyticsService(db).aggregate(2024, state='NC')['total_contributions'] == 100
    assert PACAnalyticsService(db).aggregate(2024, party='DEM')['total_contributions'] == -100
    assert PACAnalyticsService(db).aggregate(2024, category='Absent')['total_contributions'] is None


def write_zip(directory, name, member, rows):
    with zipfile.ZipFile(directory / name, 'w') as file:
        file.writestr(member, '\n'.join('|'.join(row) for row in rows))


def pas(sub_id, transaction_type='24K', amount='10'):
    row = [''] * 22
    for index, value in {0:'C00000001', 1:'A', 5:transaction_type, 14:amount,
                         16:'H00000001', 17:'TX1', 18:'2', 21:str(sub_id)}.items():
        row[index] = value
    return row


def files(tmp_path):
    cm = [''] * 15
    cm[0], cm[1], cm[9] = 'C00000001', 'Test PAC', 'Q'
    cn = [''] * 15
    cn[0], cn[1], cn[2], cn[3], cn[4], cn[5] = 'H00000001', 'Test', 'REP', '2024', 'NC', 'H'
    write_zip(tmp_path, 'cm24.zip', 'cm.txt', [cm])
    write_zip(tmp_path, 'cn24.zip', 'cn.txt', [cn])
    write_zip(tmp_path, 'pas224.zip', 'itpas2.txt', [pas(1), pas(2, '24A'), pas(3, '24E'), pas(4, '24C')])
    return PACBulkImporter(str(tmp_path))


def test_ingestion_resolution_reimport_and_atomic_failure(db, tmp_path):
    importer = files(tmp_path)
    local = Candidate(fec_candidate_id='H00000001', name='Test', office='H', party='DEM')
    db.add(local)
    db.commit()
    service = PACIngestionService(db)
    imported = service.ingest_cycle(2024, importer)
    assert imported['imported'] == 1  # Never includes independent/coordinated expenditures.
    assert PACAnalyticsService(db).aggregate(2024)['available'] is False
    row = db.scalar(select(PACContribution))
    assert row.candidate_id == local.id
    assert row.candidate_party == 'REP'  # Current mutable candidate party is not historical.
    resolution = SnapshotResolution(source_sha256=imported['source_sha256'], source='FEC adjudication fixture',
                                    records=[{'sub_id':'1', 'status':'current'}])
    service.resolve(2024, resolution)
    assert PACAnalyticsService(db).aggregate(2024)['total_contributions'] == 10
    service.map_categories([CategoryMapping(committee_id='C00000001', category='Automotive')])
    service.ingest_cycle(2024, importer)
    assert len(db.scalars(select(PACContribution)).all()) == 1
    assert db.scalar(select(PACCategory)).category == 'Automotive'
    assert db.scalar(select(PACContribution)).status == 'unresolved'
    write_zip(tmp_path, 'pas224.zip', 'itpas2.txt', [pas(9, amount='NaN')])
    with pytest.raises(ValueError):
        service.ingest_cycle(2024, importer)
    assert db.scalar(select(PACContribution)).sub_id == '1'
    with pytest.raises(ValueError):
        service.resolve(2024, SnapshotResolution(source_sha256='0' * 64, source='wrong', records=[]))


def test_resolution_rolls_back_unknown_record(db):
    seed(db)
    contribution(db, 1, 10, status='unresolved')
    db.commit()
    with pytest.raises(ValueError):
        PACIngestionService(db).resolve(2024, SnapshotResolution(source_sha256='a' * 64, source='Test',
            records=[{'sub_id':'1', 'status':'current'}, {'sub_id':'999', 'status':'current'}]))
    assert db.scalar(select(PACContribution)).status == 'unresolved'


def test_duplicate_current_transaction_identity_rejected(db):
    seed(db)
    for sub_id in (1, 2):
        contribution(db, sub_id, 10, status='unresolved', transaction_id='TX', file_number='123')
    db.commit()
    with pytest.raises(ValueError, match='Multiple current'):
        PACIngestionService(db).resolve(2024, SnapshotResolution(source_sha256='a' * 64, source='Test',
            records=[{'sub_id':str(i), 'status':'current'} for i in (1, 2)]))
    assert all(row.status == 'unresolved' for row in db.scalars(select(PACContribution)))


def test_endpoint_contract_and_validation(db):
    from fastapi import FastAPI, HTTPException
    from pydantic import ValidationError
    from app.routers.pac import router, validate_cycle, pac_categories, map_categories
    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    assert '/analytics/pac-categories' in schema['paths']
    with pytest.raises(HTTPException):
        validate_cycle(2023)
    result = pac_categories(cycle=2024, category=None, party=None, state=None, db=db)
    assert result['total_contributions'] is None
    assert map_categories([CategoryMapping(committee_id='C00000001', category=' Automotive ')], db) == {'saved':1}
    with pytest.raises(ValidationError):
        CategoryMapping(committee_id='C00000001', category='unclassified')


def test_missing_party_amount_is_null_with_known_subtotal(db):
    seed(db)
    contribution(db, 1, 20)
    contribution(db, 2, None)
    contribution(db, 3, None, candidate_party='D')
    response = PACAnalyticsService(db).aggregate(2024)
    parties = response['categories'][0]['parties']
    assert parties['R']['amount'] is None
    assert parties['R']['known_amount'] == 20
    assert parties['R']['missing_amount_records'] == 1
    assert parties['D']['amount'] is None
    assert parties['D']['known_amount'] == 0
    assert response['total_contributions'] is None
    assert response['verified_known_amount'] == 20


def test_analytics_cannot_count_independent_expenditure_rows(db):
    seed(db)
    contribution(db, 1, 70)
    contribution(db, 2, 1000, transaction_type='24E')
    contribution(db, 3, 2000, transaction_type='24A')
    response = PACAnalyticsService(db).aggregate(2024)
    assert response['total_contributions'] == 70
    assert response['coverage']['excluded_non_contribution']['amount'] == 3000


def test_election_mapping_resolves_party_and_state_independently(db):
    seed(db)
    contribution(db, 1, 70)
    for state in ('NC', 'VA'):
        db.add(ElectionResult(cycle=2024, fec_candidate_id='H00000001',
                              candidate_name='Test', party='D', office='H', state=state))
    db.flush()
    response = PACAnalyticsService(db).aggregate(2024)
    assert response['categories'][0]['parties']['D']['amount'] == 70
    assert response['coverage']['unknown_candidate_state']['amount'] == 70
    assert PACAnalyticsService(db).aggregate(2024, state='NC')['total_contributions'] is None


def test_response_serializes_dollars(db):
    from fastapi.encoders import jsonable_encoder
    seed(db)
    contribution(db, 1, Decimal('70.25'))
    result = PACAnalyticsService(db).aggregate(2024)
    assert jsonable_encoder(result)['total_contributions'] == 70.25
