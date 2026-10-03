from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Candidate, CandidateFinance, ElectionResult, OutsideSpending
from app.services.analytics_service import AnalyticsService


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_result(db, cycle=2020, office='H', state='NC', party='DEM', votes=100, candidate_id=None):
    db.add(ElectionResult(cycle=cycle, state=state, office=office,
                          party=party, general_votes=votes, candidate_name='Test',
                          fec_candidate_id=candidate_id))
    db.flush()


@pytest.mark.parametrize('office', ['H', 'S'])
@pytest.mark.parametrize('state', ['NC', 'US'])
def test_missing_cycle_does_not_become_zero(db, office, state):
    add_result(db, cycle=2012, office=office)
    response = AnalyticsService(db).compare_state_finances(state, 2000, 2012, office)
    assert response['available'] is False
    assert response['missing'] == {'from_cycle': True, 'to_cycle': False}
    assert response['parties'] == {}
    assert response['data_coverage']['2000'] == dict.fromkeys(
        ['election_results', 'candidate_finances', 'independent_expenditures'], False)


def test_absent_party_in_available_election_is_zero(db):
    add_result(db)
    add_result(db, cycle=2022, party='REP')
    response = AnalyticsService(db).compare_state_finances('NC', 2020, 2022, 'H')
    assert response['available'] is True
    assert response['parties']['DEM']['to_vote_share'] == 0
    assert response['parties']['DEM']['candidate_spending']['to'] is None
    assert response['parties']['DEM']['outside_spending']['change'] is None


@pytest.mark.parametrize('votes,available', [(None, False), ('Unopposed', False), ('#', False), ('1,000', True), (-1, False), (0, True)])
def test_usable_votes_and_undefined_zero_total_shares(db, votes, available):
    add_result(db, votes=votes)
    service = AnalyticsService(db)
    totals = service.get_state_party_totals(2020, 'NC', 'H')
    assert totals['available'] is available
    if votes == 0:
        assert totals['parties']['DEM']['vote_share'] is None
        assert service.compare_state_cycles('NC', 2020, 2020, 'H')['parties'] == {}


@pytest.mark.parametrize('office', ['H', 'S'])
def test_complete_comparison_and_explicit_zero_finances(db, office):
    candidate = Candidate(fec_candidate_id='TEST', name='Test', state='NC', office=office, party='DEM')
    db.add(candidate)
    db.flush()
    for cycle, amount in [(2020, 0), (2022, 100)]:
        add_result(db, cycle=cycle, office=office, candidate_id='TEST')
        db.add(CandidateFinance(candidate_id=candidate.id, cycle=cycle,
                               receipts=amount, disbursements=amount, cash_on_hand=0,
                               individual_contributions=0, contributions_from_other_committees=0))
        db.add(OutsideSpending(candidate_id=candidate.id, cycle=cycle, support=amount, oppose=0))
    db.flush()
    service = AnalyticsService(db)
    response = service.compare_state_finances('US', 2020, 2022, office)
    assert response['available'] is True
    assert all(all(flags.values()) for flags in response['data_coverage'].values())
    spending = response['parties']['DEM']['candidate_spending']
    assert spending['from'] == Decimal(0)
    assert spending['change'] == Decimal(100)
    assert spending['percent_change'] is None
    assert service.get_data_coverage('NC', office)['data_coverage']['2020'][office] == response['data_coverage']['2020']
    assert not any(service.get_data_coverage('VA', office)['data_coverage']['2020'][office].values())


def test_financial_only_cycle_discovered_but_not_usable_without_election_link(db):
    candidate = Candidate(fec_candidate_id='TEST', name='Test', state='NC', office='H')
    db.add(candidate)
    db.flush()
    db.add(OutsideSpending(candidate_id=candidate.id, cycle=1998, support=0, oppose=0))
    db.flush()
    assert AnalyticsService(db).get_data_coverage()['data_coverage']['1998']['H']['independent_expenditures'] is False
