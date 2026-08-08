"""Disclosure control for compensation benchmarks.

A market-data product only exists because competitors are willing to contribute
their own pay data. That willingness is conditional: no customer may be able to
read another customer's numbers back out of a published benchmark. Getting that
wrong once ends the product, so the rules live here rather than being scattered
through the view layer.

Two rules, and the second is the one people miss.

**Primary suppression.** A cell computed from fewer than `k` distinct
contributing companies is withheld. Obvious, and usually where implementations
stop.

**Complementary suppression.** Suppressing a cell is pointless if the value can
be recovered by subtraction. Publish a row total and every cell but one, and the
withheld cell is exactly `total - sum(published)`. So whenever a cell in a row is
suppressed, at least one further cell in that row must be suppressed too -- and
the same for its column. That second suppression is what actually protects the
first, and it is invisible in testing unless you go looking for it, because the
naive version produces output that *looks* correctly redacted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

DEFAULT_K = 5


class InsufficientSample(Exception):
    """Raised when a benchmark cannot be published safely at all."""


@dataclass(frozen=True)
class Observation:
    company: str
    level: str
    location: str
    base: int


@dataclass
class Cell:
    level: str
    location: str
    n: int = 0
    companies: int = 0
    p25: int | None = None
    p50: int | None = None
    p75: int | None = None
    suppressed: bool = False
    reason: str | None = None

    def redact(self, reason: str) -> None:
        self.suppressed = True
        self.reason = reason
        self.p25 = self.p50 = self.p75 = None


@dataclass
class Table:
    cells: list[Cell] = field(default_factory=list)
    k: int = DEFAULT_K

    def by_level(self, level: str) -> list[Cell]:
        return [c for c in self.cells if c.level == level]

    def by_location(self, location: str) -> list[Cell]:
        return [c for c in self.cells if c.location == location]

    def published(self) -> list[Cell]:
        return [c for c in self.cells if not c.suppressed]

    def suppressed(self) -> list[Cell]:
        return [c for c in self.cells if c.suppressed]


def percentile(values: list[int], p: float) -> int:
    """Nearest-rank percentile.

    Deliberately not interpolated. An interpolated percentile over a small sample
    is a weighted blend of two individual salaries, which is a softer version of
    publishing them; nearest-rank at least reports a real observed value, and the
    k-threshold is what keeps that from identifying anyone.
    """
    if not values:
        raise InsufficientSample("no values")
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, round(p * (len(ordered) - 1))))
    return ordered[idx]


def build(observations: list[Observation], k: int = DEFAULT_K) -> Table:
    """Aggregate observations into a level x location table, then apply both
    suppression passes."""
    groups: dict[tuple[str, str], list[Observation]] = {}
    for obs in observations:
        groups.setdefault((obs.level, obs.location), []).append(obs)

    table = Table(k=k)
    for (level, location), rows in sorted(groups.items()):
        companies = {r.company for r in rows}
        cell = Cell(level=level, location=location, n=len(rows), companies=len(companies))
        salaries = [r.base for r in rows]
        cell.p25 = percentile(salaries, 0.25)
        cell.p50 = percentile(salaries, 0.50)
        cell.p75 = percentile(salaries, 0.75)
        table.cells.append(cell)

    _primary(table)
    _complementary(table)
    return table


def _primary(table: Table) -> None:
    """Withhold any cell backed by too few distinct companies.

    The threshold counts *companies*, not observations. Ten data points from one
    employer is that employer's pay band, published back to them and to everyone
    else, which is precisely the disclosure the threshold exists to prevent.
    """
    for cell in table.cells:
        if cell.companies < table.k:
            cell.redact(f"only {cell.companies} contributing companies, need {table.k}")


def _complementary(table: Table) -> None:
    """Ensure no suppressed cell is recoverable by subtraction.

    A lone suppressed cell in an otherwise fully published row can be derived
    from the row's other cells. The fix is to suppress a second cell in that row,
    choosing the one with the fewest contributing companies, since it is the next
    most sensitive. Suppressing a second cell can itself leave *its* column with
    a lone suppression, so this iterates to a fixed point rather than making a
    single pass.
    """
    changed = True
    while changed:
        changed = False
        axes = (
            [table.by_level(lv) for lv in {c.level for c in table.cells}]
            + [table.by_location(lo) for lo in {c.location for c in table.cells}]
        )
        for group in axes:
            if len(group) < 2:
                # A one-cell row has nothing to hide behind. Its suppression is
                # already total, so there is nothing to complement.
                continue
            hidden = [c for c in group if c.suppressed]
            if len(hidden) != 1:
                continue
            candidates = [c for c in group if not c.suppressed]
            if not candidates:
                continue
            victim = min(candidates, key=lambda c: (c.companies, c.n, c.level, c.location))
            victim.redact("complementary suppression: would be recoverable by subtraction")
            changed = True


def audit(table: Table) -> list[str]:
    """Return the ways this table still leaks, if any. Empty means safe.

    Used as a self-check in the API response and asserted in the tests, so the
    property is verified on real output rather than only on the code path that
    produced it.
    """
    problems = []
    for cell in table.published():
        if cell.companies < table.k:
            problems.append(
                f"{cell.level}/{cell.location} published with {cell.companies} companies"
            )
    axes = (
        [(f"level={lv}", table.by_level(lv)) for lv in {c.level for c in table.cells}]
        + [(f"location={lo}", table.by_location(lo)) for lo in {c.location for c in table.cells}]
    )
    for name, group in axes:
        if len(group) < 2:
            continue
        if len([c for c in group if c.suppressed]) == 1:
            problems.append(f"{name} has a single suppressed cell, recoverable by subtraction")
    return problems
