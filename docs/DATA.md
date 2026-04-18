# Data pipeline

Where the data comes from, how it's transformed, how often it refreshes,
and what the scope rules are.

## Source

OpenPowerlifting publishes a bulk CSV of every meet their volunteers have
transcribed. They maintain a federation-specific "OpenIPF" subset that
includes only IPF-affiliated federations (CPU included). The export is
updated daily by the OpenPowerlifting project.

- URL: `https://openpowerlifting.gitlab.io/opl-csv/files/openipf-latest.zip`
- License: [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/)
- Attribution: [openpowerlifting.org](https://openpowerlifting.org/)

Please keep attribution and link the source if you build on this data.

## Refresh cadence

`.github/workflows/refresh-data.yml` runs every **Sunday at 06:13 UTC**.
The cron offset is intentional: avoid on-the-hour times where GitHub
runner contention peaks.

The workflow does:

1. `curl -o openipf-latest.zip <openipf-url>`
2. `unzip openipf-latest.zip`
3. `python data/preprocess.py` against the unzipped CSV
4. `gh release upload data-latest data/processed/*.parquet --clobber`

The production backend reads the parquet files from the `data-latest`
GitHub Release on cold start, so a successful workflow run is live for
new users the next time the Render instance cold-boots (either a
scheduled deploy, manual restart, or natural 15-minute idle spindown).

Manual refresh: Actions tab -> "Refresh OpenIPF data" -> Run workflow.

## Preprocess

`data/preprocess.py` takes the raw OpenIPF CSV (a few hundred MB) and
produces two parquet files:

### `openipf.parquet`

Filtered OpenIPF rows, about 5,400 unique lifters, about 28 MB
compressed. The filter applied:

```python
df = df[(df.Country == "Canada") & (df.ParentFederation == "IPF")]
```

This is the same scope the API enforces at query time. Applying it at
preprocess gives a 15-20x shrink versus shipping the full OpenIPF export,
which makes Render cold-boot downloads fast.

Columns kept (roughly): `Name`, `Sex`, `Event`, `Equipment`, `Age`,
`AgeClass`, `BirthYearClass`, `Division`, `BodyweightKg`, `WeightClassKg`,
`Best3SquatKg`, `Best3BenchKg`, `Best3DeadliftKg`, `TotalKg`, `Place`,
`Goodlift`, `Federation`, `ParentFederation`, `Date`, `MeetCountry`,
`MeetName`, `Country`.

Note: `Dots` was renamed to `Goodlift` through the SQL pipeline. The CSV
still has both; preprocess keeps `Goodlift` since that matches the current
OpenPowerlifting frontend terminology.

### `qt_standards.parquet`

Hand-curated CPU qualifying totals, sourced from the CPU's official
announcements. Vendored as a CSV (`data/qualifying_totals_canpl.csv`,
32 rows) and converted to parquet in the same preprocess step.

Columns: `Sex`, `WeightClass`, `Pre2025_Nationals`, `Pre2025_Regionals`,
`Y2025_Nationals`, `Y2025_Regionals`, `Y2027_Nationals`, `Y2027_Regionals`.

The CSV is in git because CI needs it to run the test suite without the
285 MB OpenIPF export.

### Canonical weight classes

`backend/app/weight_class.py` collapses historical variants into modern
IPF:

| Sex | Modern classes (kg) |
|---|---|
| M | 59, 66, 74, 83, 93, 105, 120, 120+ |
| F | 47, 52, 57, 63, 69, 76, 84, 84+ |

Historical rows with classes like `82.5` or `81` collapse into `83`.
Men below 58 kg return `NaN` because no CPU QT standard exists for that
range (extremely rare in CPU meets).

This is aggregate-correct and edge-case-imperfect. It's fine for cohort
statistics. Individual lifters in those edge cases may see small
misclassification.

## Schema at serve time

After `preprocess.py`, the backend registers two DuckDB views:

```sql
CREATE VIEW openipf       AS SELECT * FROM read_parquet('openipf.parquet');
CREATE VIEW qt_standards  AS SELECT * FROM read_parquet('qt_standards.parquet');
```

All API queries read from these views. DuckDB's parquet reader is
column-pruning and predicate-pushing, so a filter like
`WHERE Sex='M' AND WeightClass='83'` only scans the relevant columns for
the relevant row groups.

## QT standards and eras

The "QT Squeeze" tab slices coverage across three standards:

| Era | Effective | Context |
|---|---|---|
| Pre-2025 | Before 2025-01-01 | The standard under which most lifters in the dataset qualified |
| 2025 | 2025-01-01 onward | The first raised-standards cycle, already in effect |
| 2027 | Projected 2027-01-01 | The upcoming raise, forward-looking |

For each era, compute_coverage does:

1. For each lifter in scope, take their best SBD total in the 24-month
   window leading up to the era's effective date (or today for the 2027
   projection).
2. Compare against the QT threshold for their sex + weight class.
3. Aggregate the fraction who clear the threshold.

Aggregation happens in DuckDB SQL (`GROUP BY Sex, WeightClass, Name` with
`MAX(CASE WHEN Date < <cutoff> THEN TotalKg END)` columns per era), so
the full scope never materializes into pandas. pandas only sees the
small pre-aggregated frame for threshold comparison.

## Open-lifter definition

The QT views filter to `BirthYearClass == '24-39'` for "Open" lifters.
This is the IPF's age-bracket convention: 24 to 39 is the Open division.
Prior iterations used `Division == 'Open'` (which is free-text and
inconsistent across federations). `BirthYearClass` is derived from the
lifter's birth year and meet date, which is authoritative.

## Caching

The data pipeline caches at multiple levels:

1. **`data-latest` GitHub Release.** The parquet files live here between
   refreshes. Render downloads on cold start, caches on disk, uses local
   disk for the life of the container.
2. **DuckDB column-pruning.** Queries read only the columns they need.
3. **Python `lru_cache`** on `compute_blocks` and `get_filters`. Results
   only change on parquet refresh -> container restart, so the cache is
   safe without invalidation.

## Data quality notes

- **Age is ~70% NULL** in the OpenIPF export. Any query filtering by age
  category silently drops those rows. The Progression UI surfaces this
  with a hint.
- **Division is free-text** and varies across meets. The app maps CPU's
  canonical division labels to backend aliases.
- **TotalKg can be null** (DQ, bombed lift, bench-only events). All
  arithmetic guards against null.
- **Equipment is nominally Raw/Wraps/Single/Multi/Unlimited**, but since
  this is the IPF feed every row is effectively Raw or Single. The
  frontend collapses display to Raw / Equipped.
- **Event column has seven values**: SBD, BD, SD, SB, S, B, D. Only SBD
  (full power) gives a total that's comparable across meets. Progression
  and lifter-lookup charts filter to SBD; the per-lifter meet table
  shows all events but labels partial-meet rows clearly.

## Extending scope

If you fork and want to serve a different country or federation, the
changes are localized:

1. `backend/app/scope.py`: change `DEFAULT_COUNTRY` and
   `DEFAULT_PARENT_FEDERATION`.
2. `data/preprocess.py`: change the pandas filter.
3. `data/qualifying_totals_canpl.csv`: replace with your federation's
   standards (or remove the QT tab).

The frontend is scope-agnostic.
