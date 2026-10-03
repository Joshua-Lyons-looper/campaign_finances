# Direct PAC contributions by category

This feature is independent of election comparison and outside-spending analytics.
No new dependencies. No existing House/Senate service methods change.

## Inspected existing code

`Candidate` stores a unique FEC candidate ID and mutable party/state. `ElectionResult`
stores cycle-specific party/state. `CandidateFinance.contributions_from_other_committees`
is a candidate-level total: it cannot identify contributing PACs and is not reused as
transaction data. `OutsideSpending` and the independent expenditure importer are
outside-spending summaries, not direct contributions. There is no equivalent direct
committee-to-candidate transaction model in this backend.

## FEC files

Download ZIP snapshots for each two-year cycle to the backend's `data/` directory.
For 2024:

| File | Member | Purpose |
| --- | --- | --- |
| `cm24.zip` | `cm.txt` | Committee identity/type for this cycle |
| `pas224.zip` | `itpas2.txt` | Committee-to-candidate itemizations |
| `cn24.zip` | `cn.txt` | Cycle-specific candidate identity, party, state fallback |
| `ccl24.zip` | `ccl.txt` | Optional future recipient-committee linkage enrichment; not read in v1 |

2024 download examples:

```sh
curl -fL https://www.fec.gov/files/bulk-downloads/2024/cm24.zip -o data/cm24.zip
curl -fL https://www.fec.gov/files/bulk-downloads/2024/pas224.zip -o data/pas224.zip
curl -fL https://www.fec.gov/files/bulk-downloads/2024/cn24.zip -o data/cn24.zip
```

Sources: [bulk download catalog](https://www.fec.gov/data/browse-data/?tab=bulk-data),
[committee layout](https://www.fec.gov/campaign-finance-data/committee-master-file-description/),
[PAS2 layout](https://www.fec.gov/campaign-finance-data/contributions-committees-candidates-file-description/),
[transaction codes](https://www.fec.gov/campaign-finance-data/transaction-type-code-descriptions/),
[committee codes](https://www.fec.gov/campaign-finance-data/committee-type-code-descriptions/).

PAS2 includes independent expenditures and other spending. Only `24K` (direct cash
contributions to nonaffiliated committees) and `24Z` (in-kind contributions to
registered filers) are imported. Recipient candidates come from PAS2 `CAND_ID`;
missing candidate IDs remain unknown. Possible-candidate transactions `24P` are
outside this initial, registered-candidate scope. `24A`/`24E` independent expenditures,
`24C` coordinated party spending, communication costs, earmarked individual funds,
loans, honoraria and recount spending never enter these totals.

Only cycle-specific committee types `N`, `Q`, `V`, `W` count as contributing PACs.
Party/candidate committees and IE-only committees do not. Missing committee/type
mappings go into coverage, not into an inferred PAC class. Committee `ORG_TP` is an
organizational form, not an industry taxonomy; no categories are inferred from it.

## Models and schema

`app/models/pac.py` defines four additive tables:

- `PACCategory` / `pac_categories`: id, unique committee_id, nullable committee_name,
  category, nullable subcategory. Explicit global mapping, one category per committee.
- `PACCommittee` / `pac_committees`: id, committee_id, cycle, nullable name/type;
  unique committee/cycle. Classification checks use historical type.
- `PACContribution` / `pac_contributions`: id, contributing committee_id,
  nullable local Candidate foreign key, nullable FEC candidate ID, recipient committee
  ID, cycle, nullable decimal amount, candidate party/state snapshot, SUB_ID,
  transaction ID, report/file number, amendment indicator, transaction type,
  memo code, resolution status and provenance. Unique cycle/SUB_ID.
- `PACImport` / `pac_imports`: cycle primary key and PAS2 ZIP SHA256, tracking
  successful full-cycle ingestion even when no qualifying transactions exist.

The project uses `Base.metadata.create_all()` at app startup and has no migration
framework. Model registration creates these four tables on restart. No existing
columns or data are altered. Back up the database as usual before deployment.
For a managed migration environment, create just these four tables using their
SQLAlchemy metadata. The implementation does not run ingestion or mutate the
existing `campaign.db` during installation/testing.

Mapping names are optional labels; authoritative cycle-specific committee names
remain in PACCommittee. Global category updates apply retroactively to all cycles.
A future taxonomy can replace the mapping service; cycle-effective taxonomies would
need an effective-cycle/version column and adjusted uniqueness.

## Ingestion and amendment resolution

See [the normalized FEC source investigation](pac-amendment-resolution.md) for the
recommended bulk source, automatic-resolution design, source limitations, and exact
download/restore/export commands. This investigation does not change the endpoint's
current requirement for explicit resolution evidence.

1. Read candidate and committee ZIPs, retain historical candidate party/state.
2. Stream qualifying PAS2 rows. Join to existing Candidate IDs where available;
   unmatched FEC IDs and amounts remain nullable and recoverable.
3. Atomically replace this cycle's raw transactions and committee snapshot, storing
   the source SHA256. Failure rolls back to the previous snapshot. Existing manual
   categories survive. Reimport resets amendment statuses because evidence must
   match the newly imported snapshot. Duplicate SUB_IDs fail, rather than double-count.
4. Apply explicit current/superseded/unresolved record-level resolution evidence.
5. Aggregate only verified current records.

**Important operational limitation:** importing PAS2 alone does not produce verified
allocation totals. PAS2 supplies amendment flags and report IDs but no complete
report chain or current-record indicator. The implementation deliberately leaves all
rows unresolved until supplied with record-level evidence. An automatic adapter from
FEC's normalized bulk database is not implemented in this version. Resolution data
must come from verified FEC current-record data, normalized bulk database exports, or
careful record-level adjudication. This is separate from the manual industry taxonomy.

The [FEC amendment instructions](https://www.fec.gov/help-candidates-and-committees/filing-amendments/)
distinguish full electronic report replacements from partial paper amendments.
The [FEC filing view](https://github.com/fecgov/openFEC/blob/develop/data/migrations/V0315__ofec_filings_all_mv_add_f3l.sql)
uses amendment chains and normalized summary relationships to determine recency.

Do not choose `max(FILE_NUM)` or `max(SUB_ID)` across a committee, and do not deduplicate
only by committee/TRAN_ID: transaction IDs are report-local. Do not discard all `A`
rows, and do not retain originals when an amendment deletes a transaction. Resolve
at record level, especially for partial paper amendments. The resolution endpoint is
an internal ingestion interface: it validates source hash and row identity, but cannot
independently verify the adjudication supplied by the caller. Multiple current rows
with identical committee/file/transaction identity are rejected. Missing transaction
IDs are never deduplicated by coincidental date/amount/name.

Memo `X` rows are retained but excluded from additive allocation totals and reported
in coverage. FEC notes that memo records require analysis; excluding them here is a
conservative non-additive policy, not a claim that all memo activity is irrelevant.
Future memo attribution requires a purpose-specific reconciliation adapter.

## Endpoints and curl

Run the backend as usual from its root, with the data directory present.

```sh
curl -X POST http://localhost:8000/ingest/bulk/pac-contributions/2024

curl -X PUT http://localhost:8000/pac/categories \
  -H 'Content-Type: application/json' \
  -d '[{"committee_id":"C00000001","committee_name":"Example PAC","category":"Automotive","subcategory":null}]'

# resolution.json must contain verified evidence for this exact imported snapshot.
curl -X PUT http://localhost:8000/pac/contributions/2024/resolution \
  -H 'Content-Type: application/json' --data-binary @resolution.json

curl 'http://localhost:8000/analytics/pac-categories?cycle=2024'
curl 'http://localhost:8000/analytics/pac-categories?cycle=2024&category=Automotive'
curl 'http://localhost:8000/analytics/pac-categories?cycle=2024&party=R&state=NC'
curl 'http://localhost:8000/analytics/pac-categories?cycle=2022&category=Automotive'
```

Example resolution document (substitute the actual import hash, source provenance,
and adjudicated SUB_IDs; this is not real FEC evidence):

```json
{
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "source": "Verified FEC record-level export, snapshot date and provenance",
  "records": [
    {"sub_id":"1001","status":"superseded"},
    {"sub_id":"1002","status":"current"}
  ]
}
```

Large resolution files can be submitted in batches. Unmentioned rows keep their
status. The API currently follows the existing project's unauthenticated ingestion
conventions; deployment access control should cover its write endpoints.

## Analytics and example response

Amounts use decimal arithmetic in the database and service. JSON dollar amounts are
numbers, shares are fractions (multiply by 100 for percentages). Amounts include cash
and in-kind, and retain signed corrections rather than taking absolute values. These
are net reported contribution amounts, not spending or gross refund-adjusted receipts.
Separate recipient-side refund reconciliation is not implemented.

ElectionResult joins are resolved in memory by FEC ID/cycle so duplicate election
rows do not multiply transactions. Party and state resolve independently: conflicting
known values remain unknown, while entirely missing values fall back to the candidate
master snapshot. Mutable Candidate
party is never used to rewrite historical allocations. `DEM`/`REP` normalize to
`D`/`R` only in the new service. Other parties are retained; unknown is not OTHER.

Categories sort by known amount descending. Shares divide by the category's total
**after filters**, including unknown-party amounts. A party filter therefore generally
makes its share 1; omit that filter to compare D vs R. No party or category is invented
when it has no observations. Missing amounts make that category's total and shares
null; its known subtotal remains visible. Party amounts with missing transactions
also remain null, with `known_amount` and `missing_amount_records` beside them.
Unresolved amendments, unknown committee types, and unreconciled memo items make
all category totals and shares null because their effects on the denominators are
unknown. `verified_known_amount` retains the sum of included known dollars.
Nonpositive totals or negative party buckets
have null shares. State is the recipient candidate's state, not the contributing PAC's.

Illustrative complete response, not actual FEC results:

```json
{
  "cycle": 2024,
  "available": true,
  "complete": true,
  "filters": {"category": null, "party": null, "state": null},
  "total_contributions": 10000000,
  "verified_known_amount": 10000000,
  "categories": [{
    "cycle": 2024,
    "category": "Automotive",
    "total_contributions": 10000000,
    "known_amount": 10000000,
    "missing_amount_records": 0,
    "complete": true,
    "contributing_committees": 12,
    "parties": {
      "R": {"amount": 7000000, "known_amount": 7000000, "missing_amount_records": 0, "share": 0.7},
      "D": {"amount": 3000000, "known_amount": 3000000, "missing_amount_records": 0, "share": 0.3}
    }
  }],
  "coverage_scope": "entire_cycle",
  "coverage": {
    "unresolved_amendments": {"records": 0, "amount": 0, "missing_amount_records": 0},
    "superseded": {"records": 0, "amount": 0, "missing_amount_records": 0},
    "unknown_committee_type": {"records": 0, "amount": 0, "missing_amount_records": 0},
    "excluded_non_pac": {"records": 0, "amount": 0, "missing_amount_records": 0},
    "memo_items": {"records": 0, "amount": 0, "missing_amount_records": 0},
    "unclassified": {"records": 0, "amount": 0, "missing_amount_records": 0},
    "unknown_candidate_party": {"records": 0, "amount": 0, "missing_amount_records": 0},
    "unknown_candidate_state": {"records": 0, "amount": 0, "missing_amount_records": 0},
    "missing_amount": {"records": 0, "amount": 0, "missing_amount_records": 0},
    "excluded_non_contribution": {"records": 0, "amount": 0, "missing_amount_records": 0}
  },
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "share_denominator": "category total after filters, including unknown party",
  "amount_basis": "signed net reported cash and in-kind direct contributions (24K, 24Z)"
}
```

Unmapped eligible PACs appear in an `unclassified` category and the unclassified
coverage bucket. Coverage is cycle-wide, even with filters, and buckets overlap;
do not sum them as mutually exclusive amounts. Unresolved/superseded amounts describe
raw versions and are not estimates of excluded unique money. A missing amount makes
its coverage bucket amount null with a known_amount subtotal. No imported cycle:
`available=false`, `total_contributions=null`, `categories=[]`, `coverage=null`.
A partial verified subset has `available=true`, `complete=false`, null totals/shares,
and known subtotals: unresolved records never contribute an implied zero.
Analytics also checks transaction type, so even rows inserted outside ingestion
cannot mix independent expenditures or coordinated spending into contributions.

`complete` concerns additive amount and amendment coverage. It does not mean every
committee has an industry label or every candidate has a known party/state; those
gaps remain visible in coverage and the `unclassified`/`unknown` buckets.

## Changed files

- `app/models/pac.py`, `app/models/__init__.py`
- `app/services/pac_bulk_importer.py`
- `app/services/pac_ingestion_service.py`
- `app/services/pac_analytics_service.py`
- `app/routers/pac.py`, `app/main.py`
- `tests/test_pac_categories.py`
- `docs/pac-categories.md`

No frontend files or existing election analytics services were changed.
