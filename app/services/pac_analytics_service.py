"""Industry allocation of verified direct PAC contributions only."""
from collections import defaultdict
from decimal import Decimal
from sqlalchemy import select
from app.models.election_result import ElectionResult
from app.models.pac import PACCategory, PACCommittee, PACContribution, PACImport
from app.services.pac_bulk_importer import DIRECT_TYPES, PAC_TYPES


def normalize_party(value):
    value = (value or '').strip().upper()
    return {'DEM': 'D', 'DEMOCRAT': 'D', 'DEMOCRATIC': 'D',
            'REP': 'R', 'REPUBLICAN': 'R'}.get(value, value or None)


class PACAnalyticsService:
    def __init__(self, db):
        self.db = db

    def aggregate(self, cycle, category=None, party=None, state=None):
        # Read party from this cycle's election result where unambiguous. The
        # cycle-specific candidate master snapshot covers non-general candidates.
        results = defaultdict(set)
        for row in self.db.scalars(select(ElectionResult).where(ElectionResult.cycle == cycle)):
            if row.fec_candidate_id:
                results[row.fec_candidate_id].add((normalize_party(row.party), row.state))
        committees = {c.committee_id: c for c in self.db.scalars(
            select(PACCommittee).where(PACCommittee.cycle == cycle))}
        categories = {c.committee_id: c.category for c in self.db.scalars(select(PACCategory))}
        coverage = {key: {'records': 0, 'amount': Decimal(0), 'missing_amount_records': 0}
                    for key in ('unresolved_amendments', 'superseded', 'unknown_committee_type',
                                'excluded_non_pac', 'memo_items', 'unclassified',
                                'unknown_candidate_party', 'unknown_candidate_state', 'missing_amount',
                                'excluded_non_contribution')}
        groups = {}
        for row in self.db.scalars(select(PACContribution).where(
                PACContribution.cycle == cycle)).yield_per(2000):
            def record(key):
                bucket = coverage[key]
                bucket['records'] += 1
                if row.amount is None:
                    bucket['missing_amount_records'] += 1
                else:
                    bucket['amount'] += row.amount

            # Defense in depth: even externally inserted rows cannot mix IE with PAC gifts.
            if row.transaction_type not in DIRECT_TYPES:
                record('excluded_non_contribution')
                continue
            if row.status != 'current':
                record('superseded' if row.status == 'superseded' else 'unresolved_amendments')
                continue
            identity = committees.get(row.committee_id)
            if identity is None or not identity.committee_type:
                record('unknown_committee_type')
                continue
            if identity.committee_type not in PAC_TYPES:
                record('excluded_non_pac')
                continue
            # Do not infer dollar allocations from non-additive memo amounts.
            if row.memo_code == 'X':
                record('memo_items')
                continue
            mapped = results.get(row.fec_candidate_id, set())
            if mapped:
                parties = {party for party, _ in mapped if party is not None}
                states = {state for _, state in mapped if state is not None}
                candidate_party = next(iter(parties)) if len(parties) == 1 else None
                candidate_state = next(iter(states)) if len(states) == 1 else None
                if not parties:
                    candidate_party = normalize_party(row.candidate_party)
                if not states:
                    candidate_state = row.candidate_state
            else:
                candidate_party, candidate_state = normalize_party(row.candidate_party), row.candidate_state
            if not row.fec_candidate_id:
                candidate_party, candidate_state = None, None
            name = categories.get(row.committee_id, 'unclassified')
            if name == 'unclassified':
                record('unclassified')
            if candidate_party is None:
                record('unknown_candidate_party')
            if candidate_state is None:
                record('unknown_candidate_state')
            if row.amount is None:
                record('missing_amount')
            # Coverage above is cycle-wide, even when filters exclude unknown mappings.
            if category and name != category:
                continue
            if state and state.upper() != 'US' and candidate_state != state.upper():
                continue
            if party and candidate_party != normalize_party(party):
                continue
            group = groups.setdefault(name, {'amount': Decimal(0), 'committees': set(),
                                            'parties': {}, 'missing': 0})
            group['committees'].add(row.committee_id)
            key = candidate_party or 'unknown'
            bucket = group['parties'].setdefault(key, {'amount': Decimal(0), 'missing': 0})
            if row.amount is None:
                group['missing'] += 1
                bucket['missing'] += 1
                continue
            group['amount'] += row.amount
            bucket['amount'] += row.amount
        imported = self.db.get(PACImport, cycle)
        complete = imported is not None and all(coverage[key]['records'] == 0 for key in (
            'unresolved_amendments', 'unknown_committee_type', 'memo_items', 'missing_amount'))
        categories_response = []
        for name, group in groups.items():
            total = group['amount'] if not group['missing'] else None
            shares_available = complete and total is not None and total > 0 and all(
                bucket['amount'] >= 0 for bucket in group['parties'].values())
            categories_response.append({
                'cycle': cycle, 'category': name, 'total_contributions': total if complete else None,
                'known_amount': group['amount'], 'missing_amount_records': group['missing'],
                'complete': complete,
                'contributing_committees': len(group['committees']),
                'parties': {key: {
                    'amount': bucket['amount'] if not bucket['missing'] else None,
                    'known_amount': bucket['amount'],
                    'missing_amount_records': bucket['missing'],
                    'share': float(bucket['amount'] / total) if shares_available else None}
                    for key, bucket in sorted(group['parties'].items())}})
        categories_response.sort(key=lambda row: (-row['known_amount'], row['category']))
        available = imported is not None and bool(groups)
        for bucket in coverage.values():
            if bucket['missing_amount_records']:
                bucket['known_amount'] = bucket['amount']
                bucket['amount'] = None
        total = sum((row['known_amount'] for row in categories_response), Decimal(0))
        return {'cycle': cycle, 'available': available, 'complete': complete,
                'filters': {'category': category, 'party': normalize_party(party) if party else None,
                            'state': state.upper() if state else None},
                'total_contributions': total if available and complete and all(
                    row['total_contributions'] is not None for row in categories_response) else None,
                'verified_known_amount': total if imported else None,
                'categories': categories_response, 'coverage_scope': 'entire_cycle',
                'coverage': coverage if imported else None,
                'source_sha256': imported.source_sha256 if imported else None,
                'share_denominator': 'category total after filters, including unknown party',
                'amount_basis': 'signed net reported cash and in-kind direct contributions (24K, 24Z)'}
