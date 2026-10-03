import hashlib
from sqlalchemy import delete, select
from app.models.candidate import Candidate
from app.models.pac import PACCategory, PACCommittee, PACContribution, PACImport


class PACIngestionService:
    def __init__(self, db):
        self.db = db

    def ingest_cycle(self, cycle, importer):
        # A complete cycle snapshot replaces the prior snapshot atomically. Never append
        # snapshots, which would retain transactions deleted by subsequent amendments.
        candidates = {c['candidate_id']: c for c in importer.read_candidates(cycle)}
        local = {c.fec_candidate_id: c.id for c in self.db.scalars(select(Candidate))}
        source = importer.data_directory / f"pas2{str(cycle)[-2:]}.zip"
        digest = hashlib.sha256()
        with source.open('rb') as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b''):
                digest.update(chunk)
        try:
            for model in (PACContribution, PACCommittee, PACImport):
                self.db.execute(delete(model).where(model.cycle == cycle))
            count = 0
            for row in importer.read_committees(cycle):
                self.db.add(PACCommittee(cycle=cycle, **row))
            # Enforce duplicate identity in the database; duplicate SUB_IDs fail safely.
            for row in importer.read_contributions(cycle):
                candidate = candidates.get(row['fec_candidate_id'], {})
                self.db.add(PACContribution(
                    cycle=cycle, candidate_id=local.get(row['fec_candidate_id']),
                    candidate_party=candidate.get('party') or None,
                    candidate_state=candidate.get('state') or None, **row))
                count += 1
                if count % 2000 == 0:
                    self.db.flush()
            self.db.add(PACImport(cycle=cycle, source_sha256=digest.hexdigest()))
            self.db.commit()
            return dict(cycle=cycle, imported=count, source_sha256=digest.hexdigest(),
                        amendment_status='unresolved', available=False)
        except Exception:
            self.db.rollback()
            raise

    def map_categories(self, mappings):
        try:
            for mapping in mappings:
                values = mapping.model_dump()
                row = self.db.scalar(select(PACCategory).where(
                    PACCategory.committee_id == values['committee_id']))
                if row is None:
                    self.db.add(PACCategory(**values))
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
            self.db.commit()
            return {'saved': len(mappings)}
        except Exception:
            self.db.rollback()
            raise

    def resolve(self, cycle, resolution):
        imported = self.db.get(PACImport, cycle)
        if imported is None or imported.source_sha256 != resolution.source_sha256:
            raise ValueError('Resolution must match the imported PAS2 snapshot SHA256')
        if len({r.sub_id for r in resolution.records}) != len(resolution.records):
            raise ValueError('Duplicate resolution SUB_ID')
        try:
            for record in resolution.records:
                row = self.db.scalar(select(PACContribution).where(
                    PACContribution.cycle == cycle, PACContribution.sub_id == record.sub_id))
                if row is None:
                    raise ValueError(f'Unknown SUB_ID {record.sub_id}')
                row.status = record.status
                row.resolution_source = resolution.source
            self.db.flush()
            seen = set()
            for row in self.db.scalars(select(PACContribution).where(
                    PACContribution.cycle == cycle, PACContribution.status == 'current')):
                if row.transaction_id and row.file_number:
                    key = (row.committee_id, row.file_number, row.transaction_id)
                    if key in seen:
                        raise ValueError('Multiple current records share committee/report/transaction identity')
                    seen.add(key)
            self.db.commit()
            return {'resolved': len(resolution.records)}
        except Exception:
            self.db.rollback()
            raise
