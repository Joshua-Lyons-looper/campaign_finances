# Analytics data coverage

`GET /analytics/data-coverage?state=NC&office=house` discovers cycle/office pairs from the database. Omit state for nationwide (`US`) coverage; omit office for House and Senate. Office accepts H, S, house, senate (case insensitive).

Availability uses the exact scope and joins used by analytics:

- Election results: at least one row with parseable nonnegative integer general votes. Comma-separated strings are accepted; null, placeholders and invalid values are ignored. Explicit zero votes count as available, but a zero total has undefined shares (`null`) and cannot produce a comparison.
- Candidate finances: at least one election-linked finance row for the cycle with finite numeric receipts and disbursements, including explicit zero-dollar rows.
- Independent expenditures: at least one election-linked outside-spending row for the cycle with finite numeric support and oppose amounts, including explicit zero-dollar rows.

Coverage flags describe usable data presence, not import completeness. Financial-only cycles are discovered but financial records without election links cannot be used for these party analytics. Nationwide availability means usable rows exist somewhere nationwide, not that all states are present.

Comparison `available` means election vote shares can be compared. `missing` describes election dataset availability. Financial availability is reported independently in `data_coverage`. Missing financial party records remain null; financial changes require both values. A missing party in an available election has zero vote share. If either election is unavailable (or total votes are zero), parties is empty and no derived analytics are calculated.

Actual examples from the local database:

- [Complete NC House 2020 to 2022](data-coverage-complete.json)
- [Missing NC House 2000 to 2012](data-coverage-missing.json)

Exact application diff against the working files before this task: [data-coverage.patch](data-coverage.patch). Existing user changes were preserved. Regression tests are in `tests/test_analytics_coverage.py`.

```bash
curl 'http://localhost:8000/analytics/data-coverage'
curl 'http://localhost:8000/analytics/data-coverage?state=NC&office=house'
curl 'http://localhost:8000/analytics/states/NC/house/compare?from_cycle=2020&to_cycle=2022'
curl 'http://localhost:8000/analytics/states/NC/house/compare?from_cycle=2000&to_cycle=2012'
curl 'http://localhost:8000/analytics/states/US/senate/compare?from_cycle=2020&to_cycle=2022'
```

Validation: `.venv/bin/python -m pytest -q` passed all 26 tests. Local database checks also confirmed that NC House 2020 to 2022 remains available with all three coverage flags true, and 2000 to 2012 returns unavailable with empty parties.
