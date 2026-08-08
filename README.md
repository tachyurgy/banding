# Banding

Compensation benchmarks with disclosure control: no published cell can be read back to a
single contributing company, including by subtraction.

Live: **https://banding.levelbrook.com**

A compensation market-data product exists only because competitors are willing to
contribute their own payroll. That willingness is conditional on one promise — that no
customer can recover another customer's numbers from a published benchmark. Break it once
and there is no product, so the disclosure rules belong in one auditable module rather
than spread across the view layer.

## The two rules

**Primary suppression** is the obvious one: withhold any cell computed from fewer than `k`
distinct contributing companies. The threshold counts *companies*, not observations —
twenty rows from one employer is that employer's pay band, published back to the whole
market.

**Complementary suppression** is the one that gets missed, and it is why this repo exists.
Suppressing a cell achieves nothing if the value is recoverable by arithmetic. Publish a
row and withhold exactly one cell, and that cell is whatever makes the row add up. So
whenever a cell in a row is suppressed, a second cell in that row must be suppressed as
cover — and likewise down its column.

That second suppression is invisible in casual testing, because the naive implementation
produces output that *looks* correctly redacted. The withheld cell is marked withheld. It
is simply also derivable.

Two consequences fall out:

- The cover cell is chosen as the next most sensitive (fewest contributing companies),
  not arbitrarily.
- Suppressing a cover cell can leave *its* column with a lone suppression, so the pass
  iterates to a fixed point instead of running once.

On the live table you can watch cells well above the threshold disappear. That is the
complementary pass, not a bug.

## Verifying rather than assuming

`audit()` re-derives both properties from a finished table and returns the ways it still
leaks. It runs inside the API response, so `/api/benchmarks` reports the audit of the exact
payload it is returning, and the test suite asserts it is empty across every `k` from 1 to
12 and over 300 randomly shaped markets.

The auditor has its own test that deliberately breaks a table and confirms the audit *fails*
— a checker that cannot fail proves nothing.

## API

```
GET  /api/benchmarks?k=5    the table, plus its own audit
POST /graphql               the same table
GET  /up
```

GraphQL filtering narrows what is returned, never what is suppressed. Suppression is
decided across the whole table before any filter applies, so slicing down to a single thin
cell still returns it withheld — the obvious way to try to widen disclosure does not work.

```graphql
{ benchmarks(k: 5, level: "L6", location: "denver") {
    safe audit cells { level location companies p50 suppressed } } }
```

## Tests

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests -q     # 21 tests
```

The invariant is `test_lone_suppression_triggers_a_second_one`, backed by
`test_audit_is_clean_on_random_inputs`. Both were verified red before being kept: deleting
the `_complementary` call turns four tests failing, and the redacted-looking output that
remains is exactly the trap the rule exists to close.

## A note on percentiles

Percentiles are nearest-rank, not interpolated. An interpolated percentile over a small
sample is a weighted blend of two individual salaries, which is a softer form of publishing
them. Nearest-rank reports a genuinely observed value, and the company threshold is what
keeps that value from identifying anyone.

## Layout

```
bench/disclosure.py   aggregation, both suppression passes, the auditor
banding/app.py        Django views + GraphQL schema
tests/                unit tests and API-level tests
```

## Limits

The market is synthetic and regenerated per request from a fixed seed, so there is no
database, no contributor onboarding, and no ingestion or job-matching — mapping a
customer's titles onto a common levelling scheme is the genuinely hard part of this domain
and is not modelled here. Suppression is applied over one level-by-location table; a real
system publishes many overlapping cuts of the same data, and the interesting next problem
is that a cell suppressed in one cut can be recoverable from a different cut of the same
contributors.

MIT.
