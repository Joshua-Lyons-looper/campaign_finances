# PAC amendment resolution investigation

Recommendation: use the official **processed Schedule B PostgreSQL dump**,
`fec_fitem_sched_b.dump`, as the normalized transaction source. Keep PAS2 as an
audit/reconciliation input. Do not reconstruct amendment chains from PAS2 flags
or transaction IDs. Do not interpret absence from the dump as supersession.

This is an investigation and proposed implementation contract, not an implemented
automatic resolver. The existing endpoint still requires resolution evidence.
No application behavior, taxonomy, frontend, or production database was changed.

## Existing behavior

- `PACBulkImporter.read_contributions()` retains only 24K/24Z and stores PAS2
  SUB_ID, TRAN_ID, FILE_NUM, recipient and candidate IDs, amount and memo code.
- `PACIngestionService.ingest_cycle()` atomically replaces a cycle, fingerprints
  PAS2, and leaves every transaction unresolved. Reimport resets supplied evidence.
- `resolve()` accepts caller-supplied statuses; it checks snapshot identity and
  duplicate current committee/file/transaction identities, not FEC authority.
- `PACAnalyticsService.aggregate()` counts only current records. Any unresolved
  transaction, unknown eligible committee type, unreconciled memo, or missing
  included amount blocks `complete=true`. Category, party and state gaps alone
  do not. Automatic amendments will not remove those other completeness blockers.

## Exactly which additional FEC data

The FEC [bulk catalog](https://www.fec.gov/data/browse-data/?tab=bulk-data)
publishes PostgreSQL schedule dumps. The
[official restore guide](https://www.fec.gov/files/bulk-downloads/data-dump/schedules/README.txt)
documents a weekly dataset, historical coverage, partitioning and restore steps.
Use **Schedule B**, the spending committee's disbursements, to preserve the
existing donor-side definition. Recipient Schedule A receipts would change the
measurement basis and require separate linkage/reconciliation.

The [OpenFEC Schedule B resource](https://github.com/fecgov/openFEC/blob/develop/webservices/resources/sched_b.py)
queries `disclosure.fec_fitem_sched_b` through the
[Schedule B model](https://github.com/fecgov/openFEC/blob/develop/webservices/common/models/itemized.py).
It exposes normalized `sub_id`, `orig_sub_id`, file and transaction identity,
amount, candidate, recipient, type, memo and processing action. The model maps
the API's `amendment_indicator` to **action_cd**, not PAS2's AMNDT_IND. These
fields must not be interpreted interchangeably.

The published schema does **not** provide an explicit per-PAS2-row
current/superseded flag, a complete historical replacement mapping, or a source
processing watermark proving that every PAS2 filing has been incorporated.
`orig_sub_id` is useful identity evidence, but its name alone does not establish
that it identifies every prior amendment version. Validate the actual crosswalk
against the downloaded data before relying on it.

Consequently, a current-only export can establish positive matches; it cannot
by itself explain every missing raw record. A missing row could be deleted,
superseded, recoded, assigned another cycle, unmatched, or awaiting processing.

## Proposed backend contract

1. Stage an immutable normalized snapshot and manifest recording download URL,
   retrieval time, dump and CSV SHA256, cycle scope, export SQL, row count and
   successful restoration/export. Bind reconciliation to the PAS2 SHA256 too.
2. Import all normalized rows needed for reconciliation, including non-24K/24Z
   rows. An amendment can change transaction type or remove candidate attribution;
   prefiltering would hide that evidence. Apply the existing 24K/24Z scope only
   when building the current contribution set.
3. Validate the PAS2/normalized identity relationship using `orig_sub_id` and
   `sub_id`, with committee, file, transaction, candidate, recipient, amount,
   memo, and type checks. Preserve both IDs. Ambiguous or conflicting matches
   remain unresolved; do not fall back to fuzzy date/name/amount matching.
4. Mark a raw record current only when the official normalized current-record
   identity and substantive fields agree. Never use action A/N as a shortcut.
5. Mark a raw record superseded only with affirmative replacement/deletion
   evidence. Missing normalized rows remain unresolved by default.
6. Keep raw PAS2 versions and their evidence separately from normalized current
   contributions. Include normalized current records absent from PAS2 in
   reconciliation; merely resolving the raw subset could miss new contributions.
7. Commit the cycle and evidence atomically. Reimport must also remove previous
   normalized current contributions that disappeared in the next snapshot.
   Return current/superseded/unresolved counts and provenance from ingestion.
8. Retain existing completeness blockers. Do not declare complete while raw
   conflicts or unexplained omissions remain. A normalized-source completeness
   mode requires an explicit definition and proven source coverage; it must not
   silently bypass PAS2 unresolved coverage.

For additional **superseded/deleted** evidence, use official processed filing
metadata (`amendment_chain`, `amended_by`, `most_recent`, processing completion)
plus the underlying reports where needed. Fetch metadata in paginated bulk queries
for the implicated committees/reports, rather than querying each SUB_ID.
The [FEC source documentation](https://github.com/fecgov/openFEC/blob/develop/webservices/docs.py)
defines those fields. Its public schedule dump does not include the filing view.

For a proven complete electronic replacement chain, older report rows can be
superseded even when the replacement deletes an item. A report-level latest flag
alone is insufficient for partial paper amendments: unchanged original items can
survive. The [FEC amendment instructions](https://www.fec.gov/help-candidates-and-committees/filing-amendments/)
explain this distinction. Keep paper/unknown cases unresolved unless official
record-level evidence resolves them. If a fully automated historical status
crosswalk is essential, an official FEC export containing raw-record identity,
replacement/deletion status and processing scope is needed in addition to the
current schedule dump; no such public crosswalk was established in this review.

## Exact download and export commands

Run from the repository root. These commands prepare evidence; they do not yet
enable automatic resolution in the application. PostgreSQL client tools and a
separate scratch PostgreSQL server are required. The dump contains all historical
cycles and can be very large even when restoring only the desired partition.
No FEC API key is needed for this download.

```sh
mkdir -p data/fec-normalized
curl -fL https://www.fec.gov/files/bulk-downloads/2024/cm24.zip -o data/cm24.zip
curl -fL https://www.fec.gov/files/bulk-downloads/2024/cn24.zip -o data/cn24.zip
curl -fL https://www.fec.gov/files/bulk-downloads/2024/pas224.zip -o data/pas224.zip
curl -fL https://www.fec.gov/files/bulk-downloads/data-dump/schedules/README.txt -o data/fec-normalized/README.txt
curl -fL -D data/fec-normalized/schedule-b.headers https://www.fec.gov/files/bulk-downloads/data-dump/schedules/fec_fitem_sched_b.dump -o data/fec-normalized/fec_fitem_sched_b.dump
sha256sum data/cm24.zip data/cn24.zip data/pas224.zip data/fec-normalized/fec_fitem_sched_b.dump > data/fec-normalized/downloads.sha256
date -u +%FT%TZ > data/fec-normalized/retrieved-at.txt
pg_restore --list data/fec-normalized/fec_fitem_sched_b.dump > data/fec-normalized/restore.list
```

The FEC's
[2024 partition migration](https://github.com/fecgov/openFEC/blob/develop/data/migrations/V0270__add_fec_fitem_sched_ab_2023_2024.sql)
confirms the partition name below. Inspect `restore.list` before restoration;
the downloaded archive, rather than an old README, determines its schema.

```sh
createdb fec_pac_scratch
psql -X -v ON_ERROR_STOP=1 -d fec_pac_scratch -c 'CREATE SCHEMA disclosure; CREATE EXTENSION pg_trgm; CREATE EXTENSION btree_gin;'
pg_restore --exit-on-error --no-acl --no-owner --section=pre-data --table=fec_fitem_sched_b --table=fec_fitem_sched_b_2023_2024 --dbname=fec_pac_scratch data/fec-normalized/fec_fitem_sched_b.dump
pg_restore --exit-on-error --no-acl --no-owner --data-only --table=fec_fitem_sched_b_2023_2024 --dbname=fec_pac_scratch data/fec-normalized/fec_fitem_sched_b.dump
psql -X -v ON_ERROR_STOP=1 -d fec_pac_scratch -f docs/pac-normalized-export.sql
sha256sum data/schedule-b-2024.csv > data/fec-normalized/export.sha256
psql -X -v ON_ERROR_STOP=1 -d fec_pac_scratch -c 'SELECT two_year_transaction_period, disb_tp, action_cd, action_cd_desc, count(*) FROM disclosure.fec_fitem_sched_b_2023_2024 GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;' > data/fec-normalized/export-counts.txt
```

The export retains the whole partition, including period values 2023 and 2024.
Normalize these to the application's 2024 cycle after validating period semantics;
do not select only `two_year_transaction_period=2024` without inspecting the data.
The commands intentionally omit post-data indexes/triggers, which can depend on
FEC functions absent from the dump. Stop on restore errors rather than treating
an incomplete restored table as a complete snapshot. Use a PostgreSQL version
compatible with the actual archive schema.

The CSV is generated evidence, not a manually adjudicated `resolution.json`.
Before implementing the adapter, measure unique positive identity matches,
conflicts, unmatched raw rows and normalized current rows absent from PAS2.
That audit determines whether this snapshot supports full automatic resolution
or needs the supplemental filing/record evidence described above.

## Validation needed for implementation

Test corrections across multiple amendments, deletion by full electronic
replacement, partial paper amendments retaining unchanged originals, transaction
IDs reused across reports, amendments changing type/candidate/cycle, mismatched
snapshots, normalized IDs differing from raw IDs, duplicate/ambiguous matches,
missing evidence, malformed/truncated exports, and rollback/reimport behavior.
Real-source verification must demonstrate identity semantics and source coverage;
synthetic fixtures alone cannot establish those facts.
