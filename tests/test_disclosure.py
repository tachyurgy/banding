"""Tests for disclosure control.

The invariant is `audit(build(...)) == []`: whatever the shape of the input, the
published table must not contain a cell under the company threshold, nor a lone
suppressed cell that can be recovered by subtraction.
"""
from __future__ import annotations

import random

import pytest

from bench.disclosure import (
    DEFAULT_K,
    InsufficientSample,
    Observation,
    audit,
    build,
    percentile,
)

LEVELS = ["L3", "L4", "L5"]
LOCS = ["seattle", "denver", "remote"]


def obs(company, level, location, base):
    return Observation(company=company, level=level, location=location, base=base)


def dense(companies=8, salary=150_000):
    """A table where every cell clears the threshold comfortably."""
    out = []
    for c in range(companies):
        for lv in LEVELS:
            for lo in LOCS:
                out.append(obs(f"co{c}", lv, lo, salary + c * 1000 + LEVELS.index(lv) * 20_000))
    return out


# -- percentiles ----------------------------------------------------------


def test_percentile_is_nearest_rank_not_interpolated():
    values = [100, 200, 300, 400]
    assert percentile(values, 0.5) in values
    assert percentile(values, 0.25) in values
    assert percentile(values, 0.75) in values


def test_percentile_bounds():
    values = [10, 20, 30]
    assert percentile(values, 0.0) == 10
    assert percentile(values, 1.0) == 30


def test_percentile_of_empty_raises():
    with pytest.raises(InsufficientSample):
        percentile([], 0.5)


# -- primary suppression --------------------------------------------------


def test_cell_under_threshold_is_suppressed():
    data = dense()
    # knock one cell down to three companies
    data = [o for o in data if not (o.level == "L3" and o.location == "denver")]
    data += [obs(f"co{i}", "L3", "denver", 120_000) for i in range(3)]

    table = build(data)
    cell = next(c for c in table.cells if c.level == "L3" and c.location == "denver")
    assert cell.suppressed
    assert cell.p50 is None
    assert "3 contributing companies" in cell.reason


def test_threshold_counts_companies_not_observations():
    """Twenty rows from one employer is that employer's band, not a market."""
    data = dense()
    data = [o for o in data if not (o.level == "L5" and o.location == "remote")]
    data += [obs("solo", "L5", "remote", 200_000 + i) for i in range(20)]

    table = build(data)
    cell = next(c for c in table.cells if c.level == "L5" and c.location == "remote")
    assert cell.n == 20
    assert cell.companies == 1
    assert cell.suppressed


def test_dense_table_publishes_everything():
    table = build(dense())
    assert table.suppressed() == []
    assert len(table.published()) == len(LEVELS) * len(LOCS)


# -- complementary suppression (the invariant) ----------------------------


def test_lone_suppression_triggers_a_second_one():
    """THE invariant. One thin cell in an otherwise full row is recoverable from
    the row's other cells, so a second cell must be withheld as cover.

    This is what fails if `_complementary` is removed: the table still looks
    correctly redacted, and the thin cell is still derivable.
    """
    data = dense()
    data = [o for o in data if not (o.level == "L4" and o.location == "denver")]
    data += [obs(f"co{i}", "L4", "denver", 130_000) for i in range(2)]

    table = build(data)
    row = table.by_level("L4")
    col = table.by_location("denver")

    assert len([c for c in row if c.suppressed]) >= 2, "row leaks by subtraction"
    assert len([c for c in col if c.suppressed]) >= 2, "column leaks by subtraction"
    assert audit(table) == []


def test_complementary_pass_picks_the_next_most_sensitive_cell():
    data = dense(companies=9)
    data = [o for o in data if not (o.level == "L4" and o.location == "denver")]
    data += [obs(f"co{i}", "L4", "denver", 130_000) for i in range(2)]
    # make L4/remote the thinnest of the remaining cells in that row
    data = [o for o in data if not (o.level == "L4" and o.location == "remote")]
    data += [obs(f"co{i}", "L4", "remote", 140_000) for i in range(6)]

    table = build(data)
    remote = next(c for c in table.cells if c.level == "L4" and c.location == "remote")
    assert remote.suppressed
    assert "complementary" in remote.reason


def test_suppression_reaches_a_fixed_point():
    """Suppressing a cover cell can leave *its* column with a lone suppression,
    so the pass has to iterate rather than run once."""
    data = dense(companies=7)
    for lv, lo in [("L3", "seattle"), ("L4", "denver")]:
        data = [o for o in data if not (o.level == lv and o.location == lo)]
        data += [obs(f"co{i}", lv, lo, 125_000) for i in range(2)]

    table = build(data)
    assert audit(table) == []


def test_audit_is_clean_on_random_inputs():
    """Property check. Whatever the shape, the published table must not leak."""
    rng = random.Random(20260807)
    for _ in range(300):
        data = []
        for lv in LEVELS:
            for lo in LOCS:
                for c in range(rng.randint(0, 9)):
                    data.append(obs(f"co{c}", lv, lo, rng.randrange(90_000, 260_000)))
        if not data:
            continue
        table = build(data)
        assert audit(table) == [], f"leak with {len(table.cells)} cells"


def test_audit_flags_a_deliberately_broken_table():
    """The auditor has to be able to fail, or a clean audit proves nothing."""
    data = dense()
    data = [o for o in data if not (o.level == "L4" and o.location == "denver")]
    data += [obs(f"co{i}", "L4", "denver", 130_000) for i in range(2)]
    table = build(data)

    # un-suppress the cover cell, re-creating the recoverable situation
    for cell in table.by_level("L4"):
        if cell.suppressed and "complementary" in (cell.reason or ""):
            cell.suppressed = False
            cell.reason = None
            break
    assert audit(table) != []


def test_single_cell_table_stays_suppressed_without_cover():
    """A one-cell row has nothing to hide behind; it must not loop forever
    trying to find cover."""
    data = [obs("solo", "L3", "seattle", 100_000)]
    table = build(data)
    assert table.cells[0].suppressed
    assert audit(table) == []


def test_k_is_configurable():
    data = dense(companies=3)
    assert build(data, k=3).suppressed() == []
    assert len(build(data, k=DEFAULT_K).suppressed()) == len(LEVELS) * len(LOCS)
