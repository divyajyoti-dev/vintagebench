"""VintageBench v1 tasks: templates, gold functions, candidates, selection, base rates.

SPEC §3 and §5. Data come from the local RTDSM vintages (vintagebench.data); the task
file (tasks/v1.jsonl) stores only task *definitions* (SPEC §2.3). Golds, flips and
threshold distances are recomputed from the vintages by :func:`load_tasks`.

Gold answers
------------
Each template has one pure gold function over a *snapshot* (a mapping or Series of
observation_date -> value as published in one vintage). Every gold answer is computed
within one snapshot, so base-year changes between vintages (ROUTPUT, IPT) cannot affect
it; only the resulting Yes/No answers are compared across vintages. A gold function
returns None when an observation it needs is missing. Ties count as "no" (and are
excluded from tasks by the materiality rule anyway).

Each template also has a *deciding quantity* (e.g. annualized GDP growth) and a signed
*distance* from its threshold, positive iff the answer is Yes. Materiality: |distance|
>= the template margin (half a publication unit) in both vintages, so the answer is the
same whether published (rounded) or unrounded figures are used. Controls additionally
need |distance| <= the template cap in both vintages.

Dates (per instance = series, template, period, threshold)
---------------------------------------------------------
- as_of_date: the first vintage that contains the period (its first release); the
  deciding quantity must be computable there. Periods before 2016 or already in the
  baseline (first) vintage are skipped (no genuine first release in range).
- flip / control: revision_date = the pinned latest vintage, at least 365 days later.
- no_change: revision_date = the last vintage of the unbroken run of vintages after the
  as-of vintage in which every observation of the computation window is identical.
- Periods: 2016-01 .. 2025-12 (2016 Q1 .. 2025 Q4).
- COVID exclusion (all kinds): no computation window touching 2020-02..2021-03
  (2020 Q1..2021 Q1 for GDP).

CLI: ``python -m vintagebench.tasks --build`` writes tasks/v1.jsonl, tasks/README.md and
tasks/BASE_RATES.md; ``--base-rates`` writes only tasks/BASE_RATES.md.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from vintagebench import data

EPS = 1e-9
PERIOD_START = date(2016, 1, 1)
PERIOD_END = date(2025, 12, 1)  # last period considered (periods 2016-2025)
MIN_REVISION_GAP_DAYS = 365
NO_CHANGE_PREFERRED_GAP_DAYS = 90
COVID_MONTHS = (date(2020, 2, 1), date(2021, 3, 1))  # inclusive; quarterly: 2020Q1..2021Q1
KINDS: tuple[str, ...] = ("flip", "control", "no_change")
Kind = Literal["flip", "control", "no_change"]
# (yes, no) as-of answer quotas per kind; no_change falls back to (2, 3) if needed.
QUOTAS: dict[str, tuple[int, int]] = {"flip": (10, 10), "control": (10, 10), "no_change": (3, 2)}
SEED = 0
TASKS_DIR: Path = data.REPO_ROOT / "tasks"
V1_PATH: Path = TASKS_DIR / "v1.jsonl"

Snapshot = Mapping[date, float]

# --- dates and snapshots ----------------------------------------------------------------


def _d(x: object) -> date:
    """Normalise a date-like (date, datetime, Timestamp, ISO string) to datetime.date."""
    if type(x) is date:
        return x
    return pd.Timestamp(x).date()


def shift(d: date, months: int) -> date:
    """First day of the month ``months`` after (before, if negative) ``d``'s month."""
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    return date(y, m + 1, 1)


def as_snapshot(values: Mapping[Any, Any] | pd.Series) -> dict[date, float]:
    """Mapping/Series of date-like -> number as {date: float}; None/NaN/non-numeric
    values are dropped."""
    items = values.items()
    out: dict[date, float] = {}
    for k, v in items:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out[_d(k)] = f
    return out


def _val(s: Snapshot, d: date) -> float | None:
    v = s.get(d)
    return None if v is None or v != v else float(v)


# --- deciding quantities (pure) --------------------------------------------------------


def level_change(s: Snapshot, t: date, months: int = 1) -> float | None:
    """level(t) - level(t - months); None if either is missing."""
    now, before = _val(s, t), _val(s, shift(t, -months))
    return None if now is None or before is None else now - before


def pct_change(s: Snapshot, t: date, months: int = 1) -> float | None:
    """100 * (level(t) / level(t - months) - 1), unrounded."""
    now, before = _val(s, t), _val(s, shift(t, -months))
    if now is None or before is None or before <= 0:
        return None
    return 100.0 * (now / before - 1.0)


def annualized_qoq_pct(s: Snapshot, q: date) -> float | None:
    """GDP convention: 100 * ((level(q) / level(q-1))^4 - 1), q = quarter's first day."""
    now, before = _val(s, q), _val(s, shift(q, -3))
    if now is None or before is None or before <= 0:
        return None
    return 100.0 * ((now / before) ** 4 - 1.0)


def avg_change_3m(s: Snapshot, t: date) -> float | None:
    """Average monthly level change over the 3 months through t: (L_t - L_{t-3}) / 3."""
    d = level_change(s, t, 3)
    return None if d is None else d / 3.0


def yoy_pct(s: Snapshot, t: date) -> float | None:
    """12-month percent change of the index."""
    return pct_change(s, t, 12)


def monthly_changes(s: Snapshot, t: date, n: int) -> list[float] | None:
    """One-month level changes for the ``n`` months ending at t (oldest first)."""
    out = [level_change(s, shift(t, -k)) for k in range(n - 1, -1, -1)]
    return None if any(c is None for c in out) else [float(c) for c in out]  # type: ignore[arg-type]


def weakest_gap(s: Snapshot, t: date) -> float | None:
    """change(t) - min(change(t-11) .. change(t-1)); negative iff t is the weakest of
    the 12 months through t."""
    ch = monthly_changes(s, t, 12)
    return None if ch is None else ch[-1] - min(ch[:-1])


def rounded_change(s: Snapshot, t: date, decimals: int = 1) -> float | None:
    """Change between the values rounded to the publication precision."""
    now, before = _val(s, t), _val(s, shift(t, -1))
    if now is None or before is None:
        return None
    return round(round(now, decimals) - round(before, decimals), 6)


# --- gold functions, one per template (pure) --------------------------------------------


def real_gdp_shrank(s: Snapshot, q: date) -> bool | None:
    """Yes iff real GDP in quarter q is below the previous quarter's level."""
    d = level_change(s, q, 3)
    return None if d is None else d < -EPS


def real_gdp_grew_faster_than(s: Snapshot, q: date, threshold: float) -> bool | None:
    """Yes iff annualized quarter-over-quarter growth > threshold (percent)."""
    a = annualized_qoq_pct(s, q)
    return None if a is None else a > threshold + EPS


def payrolls_weakest_in_12m(s: Snapshot, t: date) -> bool | None:
    """Yes iff month t's payroll change is strictly below each of the 11 preceding
    months' changes (the 12 months through t). Needs levels t-12 .. t."""
    g = weakest_gap(s, t)
    return None if g is None else g < -EPS


def payrolls_3m_avg_above(s: Snapshot, t: date, threshold: float) -> bool | None:
    """Yes iff the average monthly payroll change over the 3 months through t
    (thousands) > threshold (thousands)."""
    a = avg_change_3m(s, t)
    return None if a is None else a > threshold + EPS


def industrial_production_fell(s: Snapshot, t: date) -> bool | None:
    """Yes iff the IP index in month t is below the previous month's."""
    d = level_change(s, t)
    return None if d is None else d < -EPS


def cpi_12m_above(s: Snapshot, t: date, threshold: float) -> bool | None:
    """Yes iff the 12-month percent change of the CPI index in month t > threshold."""
    y = yoy_pct(s, t)
    return None if y is None else y > threshold + EPS


def cpi_1m_above(s: Snapshot, t: date, threshold: float) -> bool | None:
    """Yes iff the one-month percent change of the CPI index in month t > threshold."""
    p = pct_change(s, t)
    return None if p is None else p > threshold + EPS


def unemployment_rose(s: Snapshot, t: date) -> bool | None:
    """Yes iff the unemployment rate (rounded to its published 0.1) is higher in month
    t than in the previous month. Unchanged -> no."""
    c = rounded_change(s, t)
    return None if c is None else c > EPS


# --- templates --------------------------------------------------------------------------


def period_label(period: date, quarterly: bool) -> str:
    """'May 2019' or '2018 Q4'."""
    if quarterly:
        return f"{period.year} Q{(period.month - 1) // 3 + 1}"
    return period.strftime("%B %Y")


def _pct(x: float) -> str:
    return f"{x:g}%"


def _jobs(x: float) -> str:
    return f"{int(round(x * 1000)):,}"


@dataclass(frozen=True)
class Template:
    """A question template bound to one series.

    ``offsets``: months relative to the period of the observations the gold reads (key
    observations). ``direction`` +1: Yes iff quantity > cutoff; -1: Yes iff quantity <
    cutoff; cutoff = threshold + ``cutoff_offset``. ``margin`` and ``cap`` are in the
    deciding quantity's units.
    """

    key: str
    series_id: str
    thresholds: tuple[float, ...]
    offsets: tuple[int, ...]
    quantity: Callable[[Snapshot, date], float | None]
    gold_fn: Callable[[Snapshot, date, float], bool | None]
    direction: int
    margin: float
    cap: float
    question_fn: Callable[[str, float], str]
    quantity_doc: str
    margin_doc: str
    cutoff_offset: float = 0.0
    quarterly: bool = False

    def gold(self, s: Snapshot, period: date, threshold: float) -> bool | None:
        return self.gold_fn(s, period, threshold)

    def distance(self, s: Snapshot, period: date, threshold: float) -> float | None:
        """Signed distance of the deciding quantity from the cutoff; > 0 iff Yes."""
        q = self.quantity(s, period)
        if q is None:
            return None
        return self.direction * (q - (threshold + self.cutoff_offset))

    def question(self, period: date, threshold: float) -> str:
        return self.question_fn(period_label(period, self.quarterly), threshold)

    def key_observations(self, period: date) -> list[date]:
        return [shift(period, k) for k in self.offsets]

    def window(self, period: date) -> tuple[date, ...]:
        """All observation dates from the earliest key observation through the period."""
        step = 3 if self.quarterly else 1
        lo = min(self.offsets)
        return tuple(shift(period, k) for k in range(lo, 1, step))


TEMPLATE_LIST: tuple[Template, ...] = (
    Template(
        key="gdp_shrink", series_id="ROUTPUT", thresholds=(0.0,), offsets=(-3, 0),
        quantity=annualized_qoq_pct, gold_fn=lambda s, q, thr: real_gdp_shrank(s, q),
        direction=-1, margin=0.05, cap=1.0, quarterly=True,
        question_fn=lambda p, thr: f"Did US real GDP shrink in {p}?",
        quantity_doc="annualized quarter-over-quarter % change of the real GDP level; "
        "Yes iff below 0 (the level fell)",
        margin_doc="0.05 pp (half the 0.1 pp unit of published annualized growth)",
    ),
    Template(
        key="gdp_growth_above", series_id="ROUTPUT", thresholds=(2.0,), offsets=(-3, 0),
        quantity=annualized_qoq_pct, gold_fn=real_gdp_grew_faster_than,
        direction=1, margin=0.05, cap=1.0, quarterly=True,
        question_fn=lambda p, thr: (
            f"Did US real GDP grow faster than a {_pct(thr)} annual rate in {p}?"
        ),
        quantity_doc="annualized quarter-over-quarter % change of the real GDP level; "
        "Yes iff above the threshold",
        margin_doc="0.05 pp",
    ),
    Template(
        key="payroll_weakest_12m", series_id="EMPLOY", thresholds=(0.0,),
        offsets=tuple(range(-12, 1)), quantity=weakest_gap,
        gold_fn=lambda s, t, thr: payrolls_weakest_in_12m(s, t),
        direction=-1, margin=0.5, cap=35.0,
        question_fn=lambda p, thr: (
            f"Was {p} the weakest month for US job growth (nonfarm payrolls) in the "
            f"12 months through {p}?"
        ),
        quantity_doc="payroll change in the month (level difference, thousands) minus "
        "the smallest change of the 11 preceding months; Yes iff below 0",
        margin_doc="0.5 thousand (half the published 1 thousand unit)",
    ),
    Template(
        key="payroll_avg3m_above", series_id="EMPLOY", thresholds=(100.0, 150.0),
        offsets=(-3, 0), quantity=avg_change_3m, gold_fn=payrolls_3m_avg_above,
        direction=1, margin=0.5, cap=35.0,
        question_fn=lambda p, thr: (
            f"Did US employers add more than {_jobs(thr)} jobs a month on average "
            f"(nonfarm payrolls) in the three months through {p}?"
        ),
        quantity_doc="(level(t) - level(t-3)) / 3 in thousands; Yes iff above the "
        "threshold",
        margin_doc="0.5 thousand",
    ),
    Template(
        key="ip_fell", series_id="IPT", thresholds=(0.0,), offsets=(-1, 0),
        quantity=lambda s, t: pct_change(s, t),
        gold_fn=lambda s, t, thr: industrial_production_fell(s, t),
        direction=-1, margin=0.05, cap=0.3,
        question_fn=lambda p, thr: f"Did US industrial production fall in {p}?",
        quantity_doc="month-over-month % change of the IP index; Yes iff below 0 (the "
        "level fell)",
        margin_doc="0.05 pp (half the published 0.1% unit)",
    ),
    Template(
        key="cpi_12m_above", series_id="PCPI", thresholds=(2.0, 2.5, 3.0),
        offsets=(-12, 0), quantity=yoy_pct, gold_fn=cpi_12m_above,
        direction=1, margin=0.05, cap=0.25,
        question_fn=lambda p, thr: (
            f"Was US consumer price inflation (CPI) above {_pct(thr)} over the 12 "
            f"months through {p}?"
        ),
        quantity_doc="12-month % change of the seasonally adjusted CPI index; Yes iff "
        "above the threshold",
        margin_doc="0.05 pp (half the published 0.1 pp unit)",
    ),
    Template(
        key="cpi_1m_above", series_id="PCPI", thresholds=(0.2, 0.3),
        offsets=(-1, 0), quantity=lambda s, t: pct_change(s, t), gold_fn=cpi_1m_above,
        direction=1, margin=0.05, cap=0.1,
        question_fn=lambda p, thr: (
            f"Did US consumer prices (CPI) rise by more than {_pct(thr)} in {p}?"
        ),
        quantity_doc="month-over-month % change of the seasonally adjusted CPI index; "
        "Yes iff above the threshold",
        margin_doc="0.05 pp",
    ),
    Template(
        key="unemployment_rose", series_id="RUC", thresholds=(0.0,), offsets=(-1, 0),
        quantity=rounded_change, gold_fn=lambda s, t, thr: unemployment_rose(s, t),
        direction=1, margin=0.05, cap=0.15, cutoff_offset=0.05,
        question_fn=lambda p, thr: f"Did the US unemployment rate rise in {p}?",
        quantity_doc="month-over-month change of the rate rounded to its published "
        "0.1 pp; Yes iff it rose (by at least 0.1); unchanged is No. The distance is "
        "measured from 0.05, midway between unchanged and +0.1",
        margin_doc="0.05 pp (always met: changes are multiples of 0.1)",
    ),
)  # fmt: skip
TEMPLATES: dict[str, Template] = {t.key: t for t in TEMPLATE_LIST}


def templates_for(series_id: str) -> list[Template]:
    return [t for t in TEMPLATE_LIST if t.series_id == series_id]


def _threshold_tag(tp: Template, thr: float) -> str:
    if len(tp.thresholds) == 1:
        return ""
    if tp.series_id == "EMPLOY":
        return f"-{thr:g}k"
    return f"-{thr:g}pct"


def task_id(tp: Template, period: date, thr: float) -> str:
    p = f"{period.year}q{(period.month - 1) // 3 + 1}" if tp.quarterly else f"{period:%Y-%m}"
    return f"{tp.series_id.lower()}-{tp.key}{_threshold_tag(tp, thr)}-{p}"


# --- Task -------------------------------------------------------------------------------

DEFINITION_FIELDS: tuple[str, ...] = (
    "id", "series_id", "template", "period", "threshold", "as_of_date", "revision_date",
    "question", "answer_type", "kind", "notes",
)  # fmt: skip


@dataclass(frozen=True)
class Task:
    """One task. Definition fields are stored in tasks/v1.jsonl; the computed fields
    (gold_as_of, gold_revised, flips, margin_as_of, margin_revised = signed distances)
    are filled by :func:`load_tasks` / :func:`evaluate` from the local vintages and never
    written to disk. Dates are ISO strings; ``period`` is the first day of the observed
    month or quarter."""

    id: str
    series_id: str
    template: str
    period: str
    threshold: float
    as_of_date: str
    revision_date: str
    question: str
    answer_type: str
    kind: str
    notes: str = ""
    gold_as_of: bool | None = None
    gold_revised: bool | None = None
    flips: bool | None = None
    margin_as_of: float | None = None
    margin_revised: float | None = None

    def definition(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: d[k] for k in DEFINITION_FIELDS}


def template_of(task: Any) -> Template:
    return TEMPLATES[task.template]


def _period(task: Any) -> date:
    return _d(task.period)


def key_observations(task: Any) -> list[date]:
    """Observation dates the task's gold depends on (memorization probe)."""
    return template_of(task).key_observations(_period(task))


def computation_window(task: Any) -> tuple[date, ...]:
    """All observation dates spanned by the task's computation (overlap, COVID)."""
    return template_of(task).window(_period(task))


def implied_answer(task: Any, values: Mapping[Any, Any]) -> bool | None:
    """The task's gold function applied to arbitrary values {date: value} (e.g. a
    model's values_used). None if a needed observation is missing."""
    tp = template_of(task)
    return tp.gold(as_snapshot(values), _period(task), float(task.threshold))


def touches_covid(tp: Template, period: date) -> bool:
    lo, hi = COVID_MONTHS
    if tp.quarterly:  # 2020 Q1 .. 2021 Q1 (quarters are dated by their first month)
        lo, hi = date(2020, 1, 1), date(2021, 1, 1)
    return any(lo <= d <= hi for d in tp.window(period))


def covid_window_overlap(task: Any) -> bool:
    return touches_covid(template_of(task), _period(task))


def windows_overlap(a: Any, b: Any) -> bool:
    """Same series and at least one shared observation in the computation windows."""
    return a.series_id == b.series_id and bool(
        set(computation_window(a)) & set(computation_window(b))
    )


def task_clusters(rows: Iterable[Any]) -> dict[str, str]:
    """id -> cluster label: connected components of same-series window overlap,
    labelled '<SERIES>-<n>' in order of earliest window date (order-independent)."""
    rows = sorted(rows, key=lambda r: (r.series_id, min(computation_window(r)), r.id))
    parent = {r.id: r.id for r in rows}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            if windows_overlap(a, b):
                parent[find(b.id)] = find(a.id)
    labels: dict[str, str] = {}
    counters: Counter[str] = Counter()
    out: dict[str, str] = {}
    for r in rows:
        root = find(r.id)
        if root not in labels:
            counters[r.series_id] += 1
            labels[root] = f"{r.series_id}-{counters[r.series_id]}"
        out[r.id] = labels[root]
    return out


def overlap_pairs(rows: list[Any]) -> int:
    return sum(windows_overlap(a, b) for i, a in enumerate(rows) for b in rows[i + 1 :])


# --- snapshots from the vintages --------------------------------------------------------


class Vintages:
    """All vintages of one series as {vintage_date: {observation_date: value}}."""

    def __init__(self, series_id: str, root: Path | str = data.RAW_DIR) -> None:
        df = data.load_vintages(series_id, root)
        self.series_id = series_id
        self.snaps: dict[date, dict[date, float]] = {}
        for vd, g in df.groupby("vintage_date", sort=True):
            self.snaps[_d(vd)] = as_snapshot(
                dict(zip(g["observation_date"], g["value"], strict=True))
            )
        self.dates: list[date] = sorted(self.snaps)

    def as_of(self, d: date) -> dict[date, float]:
        known = [v for v in self.dates if v <= d]
        return self.snaps[known[-1]] if known else {}

    def first_containing(self, obs: date) -> date | None:
        return next((v for v in self.dates if obs in self.snaps[v]), None)


# --- candidates -------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One (series, template, period, threshold) instance with its golds and signed
    distances at first release, one year later and in the latest vintage."""

    template: str
    series_id: str
    period: date
    threshold: float
    as_of: date
    latest: date
    year_later: date | None
    gold_first: bool
    gold_year: bool | None
    gold_latest: bool | None
    dist_first: float
    dist_year: float | None
    dist_latest: float | None
    no_change_until: date | None

    @property
    def tp(self) -> Template:
        return TEMPLATES[self.template]

    @property
    def id(self) -> str:
        return task_id(self.tp, self.period, self.threshold)

    @property
    def covid(self) -> bool:
        return touches_covid(self.tp, self.period)

    @property
    def gap_ok(self) -> bool:
        return (self.latest - self.as_of).days >= MIN_REVISION_GAP_DAYS

    def material(self, dist: float | None) -> bool:
        return dist is not None and abs(dist) >= self.tp.margin - EPS

    def within_cap(self, dist: float | None) -> bool:
        return dist is not None and abs(dist) <= self.tp.cap + EPS

    @property
    def flips_latest(self) -> bool | None:
        return None if self.gold_latest is None else self.gold_latest != self.gold_first


def _instance(
    v: Vintages, tp: Template, period: date, thr: float, baseline: date
) -> Candidate | None:
    first = v.first_containing(period)
    if first is None or first <= baseline:
        return None
    s0 = v.snaps[first]
    g0, d0 = tp.gold(s0, period, thr), tp.distance(s0, period, thr)
    if g0 is None or d0 is None:
        return None
    latest = v.dates[-1]
    later = [x for x in v.dates if x >= first + timedelta(days=MIN_REVISION_GAP_DAYS)]
    yl = later[0] if later else None
    sl, sy = v.snaps[latest], (v.snaps[yl] if yl else None)
    window = tp.window(period)
    run_end = None
    for x in v.dates[v.dates.index(first) + 1 :]:
        if any(v.snaps[x].get(o) != s0.get(o) for o in window):
            break
        run_end = x
    return Candidate(
        template=tp.key, series_id=tp.series_id, period=period, threshold=thr,
        as_of=first, latest=latest, year_later=yl,
        gold_first=g0, gold_year=None if sy is None else tp.gold(sy, period, thr),
        gold_latest=tp.gold(sl, period, thr), dist_first=d0,
        dist_year=None if sy is None else tp.distance(sy, period, thr),
        dist_latest=tp.distance(sl, period, thr), no_change_until=run_end,
    )  # fmt: skip


def build_candidates(
    series_ids: Iterable[str] = data.SERIES_IDS, root: Path | str = data.RAW_DIR
) -> list[Candidate]:
    """All instances (no filters) whose period is in 2016-2025 and first released after
    the baseline vintage, computable at first release. Sorted by id."""
    out: list[Candidate] = []
    for sid in series_ids:
        tps = templates_for(sid)
        if not tps:
            raise KeyError(f"no templates for series {sid!r}")
        v = Vintages(sid, root)
        baseline = v.dates[0]
        periods = sorted(
            {o for snap in v.snaps.values() for o in snap if PERIOD_START <= o <= PERIOD_END}
        )
        for tp in tps:
            for p in periods:
                if tp.quarterly and p.month % 3 != 1:
                    continue
                for thr in tp.thresholds:
                    c = _instance(v, tp, p, thr, baseline)
                    if c is not None:
                        out.append(c)
    return sorted(out, key=lambda c: c.id)


# --- eligibility per kind ---------------------------------------------------------------


def flip_eligible(c: Candidate) -> bool:
    return (
        c.gap_ok and not c.covid and c.material(c.dist_first) and c.material(c.dist_latest)
        and c.flips_latest is True
    )  # fmt: skip


def control_eligible(c: Candidate) -> bool:
    return (
        c.gap_ok and not c.covid and c.material(c.dist_first) and c.material(c.dist_latest)
        and c.flips_latest is False
        and c.within_cap(c.dist_first) and c.within_cap(c.dist_latest)
    )  # fmt: skip


def no_change_eligible(c: Candidate) -> bool:
    """Window identical in at least the next vintage; material; within the control cap
    (non-trivial, like controls)."""
    return (
        c.no_change_until is not None and not c.covid and c.material(c.dist_first)
        and c.within_cap(c.dist_first)
    )  # fmt: skip


ELIGIBLE: dict[str, Callable[[Candidate], bool]] = {
    "flip": flip_eligible,
    "control": control_eligible,
    "no_change": no_change_eligible,
}

KIND_NOTES = {
    "flip": "flip: the conclusion at first release differs from the pinned latest vintage.",
    "control": "control: same conclusion at first release and in the pinned latest "
    "vintage; deciding quantity within the control cap in both.",
    "no_change": "no_change: every observation in the computation window is identical in "
    "the as-of and revision vintages.",
}


def to_task(c: Candidate, kind: str) -> Task:
    """Definition-only Task for a candidate (computed fields filled for convenience)."""
    rev = c.no_change_until if kind == "no_change" else c.latest
    assert rev is not None
    gold_rev = c.gold_first if kind == "no_change" else c.gold_latest
    dist_rev = c.dist_first if kind == "no_change" else c.dist_latest
    return Task(
        id=c.id, series_id=c.series_id, template=c.template, period=c.period.isoformat(),
        threshold=float(c.threshold), as_of_date=c.as_of.isoformat(),
        revision_date=rev.isoformat(), question=c.tp.question(c.period, c.threshold),
        answer_type="yes_no", kind=kind, notes=KIND_NOTES[kind],
        gold_as_of=c.gold_first, gold_revised=gold_rev, flips=c.gold_first != gold_rev,
        margin_as_of=c.dist_first, margin_revised=dist_rev,
    )  # fmt: skip


def filter_counts(cands: list[Candidate]) -> dict[str, dict[str, int]]:
    """Per series: candidate counts at each filter stage (for tasks/README.md)."""
    out: dict[str, dict[str, int]] = defaultdict(Counter)  # type: ignore[arg-type]
    for c in cands:
        for key in (c.series_id, "all"):
            row = out[key]
            row["instances"] += 1
            base = c.gap_ok and c.flips_latest is not None
            row["gap_ok"] += base
            mat = base and c.material(c.dist_first) and c.material(c.dist_latest)
            row["material"] += mat
            row["material_no_covid"] += mat and not c.covid
            row["flip"] += flip_eligible(c)
            row["control_uncapped"] += mat and not c.covid and c.flips_latest is False
            row["control"] += control_eligible(c)
            row["no_change_identical"] += c.no_change_until is not None and not c.covid
            row["no_change"] += no_change_eligible(c)
    return {k: dict(v) for k, v in out.items()}


# --- selection --------------------------------------------------------------------------


@dataclass
class Selection:
    tasks: list[Task]
    shortfall: dict[str, int]
    overlaps: int


def _slots(kind: str, quotas: tuple[int, int]) -> list[bool]:
    yes, no = quotas
    out: list[bool] = []
    for i in range(max(yes, no)):
        if i < yes:
            out.append(True)
        if i < no:
            out.append(False)
    return out


def select_v1_detailed(
    candidates: list[Candidate],
    seed: int = SEED,
    quotas: Mapping[str, tuple[int, int]] = QUOTAS,
) -> Selection:
    """Greedy, seeded selection (see :func:`select_v1`); also returns the per-kind
    shortfall (unfilled slots) and the number of overlapping same-series pairs."""
    uniq: dict[str, Candidate] = {}
    for c in sorted(candidates, key=lambda c: (c.id, repr(c))):
        uniq.setdefault(c.id, c)  # duplicates: keep one, independent of input order
    order = sorted(uniq)
    random.Random(seed).shuffle(order)
    rank = {cid: i for i, cid in enumerate(order)}
    chosen: list[Task] = []
    used: set[str] = set()
    shortfall: dict[str, int] = {}
    for kind in KINDS:
        q = quotas[kind]
        pool = [uniq[i] for i in order if ELIGIBLE[kind](uniq[i])]
        if kind == "no_change":
            n_yes = sum(c.gold_first for c in pool)
            if n_yes < q[0] and len(pool) - n_yes >= q[0]:
                q = (q[1], q[0])
        mine: list[Task] = []
        missing = 0
        for want in _slots(kind, q):
            best, best_key = None, None
            for c in pool:
                if c.id in used or c.gold_first != want:
                    continue
                t = to_task(c, kind)
                key = _score(t, c, kind, chosen, mine, rank[c.id])
                if best_key is None or key < best_key:
                    best, best_key = t, key
            if best is None:
                missing += 1
                continue
            used.add(best.id)
            mine.append(best)
            chosen.append(best)
        shortfall[kind] = missing
    ordered = sorted(chosen, key=lambda t: (KINDS.index(t.kind), t.series_id, t.period, t.id))
    return Selection(ordered, shortfall, overlap_pairs(ordered))


def _score(
    t: Task, c: Candidate, kind: str, chosen: list[Task], mine: list[Task], rank: int
) -> tuple:
    """Lower is better: avoid same-series window overlap first, then spread series,
    the series' Yes/No answers, years and templates (within the kind, then overall),
    then the seeded rank."""
    year = c.period.year
    return (
        sum(windows_overlap(t, o) for o in chosen),
        0
        if kind != "no_change"
        or (c.no_change_until - c.as_of).days  # type: ignore[operator]
        >= NO_CHANGE_PREFERRED_GAP_DAYS
        else 1,
        sum(o.series_id == t.series_id for o in mine),
        sum(o.series_id == t.series_id and o.gold_as_of == t.gold_as_of for o in mine),
        sum(_d(o.period).year == year for o in mine),
        sum(o.template == t.template for o in mine),
        sum(o.series_id == t.series_id for o in chosen),
        sum(_d(o.period).year == year for o in chosen),
        rank,
    )


def select_v1(candidates: list[Candidate], seed: int = SEED) -> list[Task]:
    """45 tasks = 20 flips, 20 controls, 5 no_change; as-of answers 10/10, 10/10, 3/2
    (or 2/3). Each slot takes the eligible candidate that (1) overlaps the fewest
    already-selected same-series computation windows, (for no_change: revision >= 90
    days later preferred), then (2) has the fewest already-selected tasks of the same
    series / series and as-of answer / year / template in its kind, then the same
    series / year overall, then (3) the seeded rank.
    Deterministic for a seed; independent of input order and duplicates."""
    return select_v1_detailed(candidates, seed).tasks


# --- persistence and load-time recomputation --------------------------------------------


def save_tasks(path: Path | str, tasks: Iterable[Task]) -> None:
    """Write definitions only (no golds, margins or data values; SPEC §2.3)."""
    lines = [json.dumps(t.definition()) for t in tasks]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + ("\n" if lines else ""))


class TaskKindError(ValueError):
    """A task's recomputed golds disagree with its stored kind."""


def evaluate(task: Task, as_of: Snapshot, revised: Snapshot) -> Task:
    """Fill the computed fields from the two snapshots and check them against kind.

    Raises TaskKindError if a gold is not computable, the materiality rule fails, or the
    computed kind disagrees with the stored one (flip: answers differ; control: answers
    equal; no_change: answers equal and every window observation identical).
    """
    tp, p, thr = template_of(task), _period(task), float(task.threshold)
    g1, g2 = tp.gold(as_of, p, thr), tp.gold(revised, p, thr)
    d1, d2 = tp.distance(as_of, p, thr), tp.distance(revised, p, thr)
    if g1 is None or g2 is None or d1 is None or d2 is None:
        raise TaskKindError(f"{task.id}: gold not computable from the vintages")
    if min(abs(d1), abs(d2)) < tp.margin - EPS:
        raise TaskKindError(f"{task.id}: materiality rule violated")
    flips = g1 != g2
    same = all(as_of.get(o) == revised.get(o) for o in tp.window(p))
    if task.kind == "flip":
        ok = flips
    elif task.kind == "control":
        ok = not flips
    elif task.kind == "no_change":
        ok = same and not flips
    else:
        raise TaskKindError(f"{task.id}: unknown kind {task.kind!r}")
    if not ok:
        computed = "flip" if flips else ("no_change" if same else "control")
        raise TaskKindError(f"{task.id}: stored kind {task.kind!r}, computed {computed!r}")
    return replace(
        task, gold_as_of=g1, gold_revised=g2, flips=flips, margin_as_of=d1, margin_revised=d2
    )


def load_tasks(path: Path | str, root: Path | str = data.RAW_DIR) -> list[Task]:
    """Read task definitions and recompute golds, flips and margins from the vintages
    in ``root`` (as of as_of_date and revision_date). Raises TaskKindError on mismatch."""
    rows = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    vint: dict[str, Vintages] = {}
    out = []
    for row in rows:
        defn = {k: row[k] for k in DEFINITION_FIELDS if k in row}
        task = Task(**defn)
        if task.series_id not in vint:
            vint[task.series_id] = Vintages(task.series_id, root)
        v = vint[task.series_id]
        out.append(evaluate(task, v.as_of(_d(task.as_of_date)), v.as_of(_d(task.revision_date))))
    return out


# --- base rates -------------------------------------------------------------------------

VARIANTS = ("all", "all_no_covid", "material", "material_no_covid")
COMPARISONS = ("latest", "one_year")


@dataclass(frozen=True)
class RateRow:
    group: str  # "overall" | "series" | "template"
    name: str
    comparison: str  # "latest" | "one_year"
    variant: str
    k: int
    n: int


def _differs(c: Candidate, comparison: str, variant: str) -> bool | None:
    """None if the instance is not in the population of this cell, else whether the
    first-release conclusion differs from the comparison vintage's."""
    if c.year_later is None or not c.gap_ok:
        return None
    gold, dist = (
        (c.gold_latest, c.dist_latest) if comparison == "latest" else (c.gold_year, c.dist_year)
    )
    if gold is None or dist is None:
        return None
    if variant.endswith("no_covid") and c.covid:
        return None
    if variant.startswith("material") and not (c.material(c.dist_first) and c.material(dist)):
        return None
    return gold != c.gold_first


def _template_name(c: Candidate) -> str:
    tp = c.tp
    return tp.key if len(tp.thresholds) == 1 else f"{tp.key} > {c.threshold:g}"


def base_rates(
    candidates: list[Candidate] | None = None, root: Path | str = data.RAW_DIR
) -> list[RateRow]:
    """How often the first-release conclusion differs from (i) the pinned latest
    vintage and (ii) the first vintage >= 365 days after first release.

    Population: every candidate instance (from :func:`build_candidates`; built from
    ``root`` if None) with a vintage >= 365 days after its first release, so (i) and
    (ii) share a population. Variants: all; COVID windows excluded; material (|distance|
    >= margin in both compared vintages); material and COVID excluded.
    """
    cands = build_candidates(data.SERIES_IDS, root) if candidates is None else candidates
    groups: list[tuple[str, Callable[[Candidate], str]]] = [
        ("overall", lambda c: "all"),
        ("series", lambda c: c.series_id),
        ("template", _template_name),
    ]
    rows: list[RateRow] = []
    for group, key in groups:
        names = sorted({key(c) for c in cands}, key=lambda n: (n != "all", n))
        for name in names:
            members = [c for c in cands if key(c) == name]
            for comp in COMPARISONS:
                for var in VARIANTS:
                    vals = [d for c in members if (d := _differs(c, comp, var)) is not None]
                    rows.append(RateRow(group, name, comp, var, sum(vals), len(vals)))
    return rows


def _cell(k: int, n: int) -> str:
    return f"{k}/{n} ({100 * k / n:.1f}%)" if n else "0/0 (n/a)"


VARIANT_LABELS = {
    "all": "all instances",
    "all_no_covid": "all, COVID windows excluded",
    "material": "material in both vintages",
    "material_no_covid": "material, COVID excluded",
}


def render_base_rates(rows: list[RateRow]) -> str:
    head = [
        "# Base rates: how often a first-release conclusion changes",
        "",
        "Generated by `python -m vintagebench.tasks --base-rates` (or `--build`) from the",
        "local RTDSM vintages. Counts only; no data values (SPEC §2.3).",
        "",
        "Population: every (series, template, period, threshold) instance of the task",
        "templates (tasks/README.md) whose period is in 2016-2025, first released after",
        "the baseline vintage, computable at first release, and with a vintage at least",
        "365 days after its first release (so both comparisons use the same instances).",
        "No selection filters apply. Each cell is k/n (share): k instances whose Yes/No",
        "conclusion at first release differs from the comparison vintage, out of n.",
        "",
        "- vs latest: the pinned latest vintage (data/manifest.json).",
        "- vs one year later: the first vintage at least 365 days after first release.",
        "- material: the deciding quantity clears its threshold by at least the template",
        "  margin (half a publication unit) in both compared vintages.",
        "- COVID excluded: no observation of the computation window in 2020-02..2021-03",
        "  (2020 Q1..2021 Q1 for GDP).",
        "",
    ]
    out = head
    for comp, title in (("latest", "vs latest vintage"), ("one_year", "vs one year later")):
        out += [f"## First release {title}", ""]
        out.append("| group | " + " | ".join(VARIANT_LABELS[v] for v in VARIANTS) + " |")
        out.append("|---|" + "---|" * len(VARIANTS))
        keys = sorted(
            {(r.group, r.name) for r in rows if r.comparison == comp},
            key=lambda g: (("overall", "series", "template").index(g[0]), g[1]),
        )
        for group, name in keys:
            cells = {
                r.variant: r
                for r in rows
                if r.comparison == comp and r.group == group and r.name == name
            }
            label = "overall" if group == "overall" else f"{group}: {name}"
            out.append(
                f"| {label} | " + " | ".join(_cell(cells[v].k, cells[v].n) for v in VARIANTS) + " |"
            )
        out.append("")
    return "\n".join(out)


# --- README -----------------------------------------------------------------------------


def _yn(x: bool | None) -> str:
    return "n/a" if x is None else ("Yes" if x else "No")


def _example(tp: Template) -> str:
    p = date(2019, 4, 1) if tp.quarterly else date(2019, 5, 1)
    return tp.question(p, tp.thresholds[-1])


def render_readme(sel: Selection, counts: dict[str, dict[str, int]], seed: int) -> str:
    tasks = sel.tasks
    clusters = task_clusters(tasks)
    lines = [
        "# VintageBench v1 tasks",
        "",
        "`v1.jsonl` stores task definitions only (id, series_id, template, period,",
        "threshold, as_of_date, revision_date, question, answer_type, kind, notes). Gold",
        "answers, flips and threshold distances are recomputed from the local RTDSM",
        "vintages by `vintagebench.tasks.load_tasks`, which fails if a task's computed",
        "kind disagrees with its stored kind. No data values are stored or quoted here",
        "(SPEC §2.3). Regenerate with `python -m vintagebench.tasks --build`",
        f"(seed {seed}).",
        "",
        "## Conventions used to compute gold answers",
        "",
        "Questions state the question in plain words and intentionally do not spell out",
        "the formula; the gold answer uses these conventions (SPEC §3). All quantities are",
        "computed within one vintage, unrounded unless stated; ties count as No.",
        "",
        "| template | series | example question | thresholds | gold (deciding quantity) "
        "| materiality margin | control cap | key observations |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for tp in TEMPLATE_LIST:
        thr = ", ".join(f"{x:g}" for x in tp.thresholds)
        unit = "pp" if tp.series_id != "EMPLOY" else "thousand"
        offs = ", ".join(("t" if k == 0 else f"t{k:+d}") for k in (min(tp.offsets), 0))
        offs = f"{offs} ({len(tp.offsets)} obs)" if len(tp.offsets) > 2 else offs
        if tp.quarterly:
            offs = "q-1, q"
        lines.append(
            f"| {tp.key} | {tp.series_id} | {_example(tp)} | {thr} | {tp.quantity_doc} "
            f"| {tp.margin_doc} | {tp.cap:g} {unit} | {offs} |"
        )
    lines += [
        "",
        "Notes: GDP growth is the annualized quarter-over-quarter change of the real GDP",
        "level; payroll changes are level differences in thousands; IP 'fell' is a",
        "month-over-month level decline; CPI inflation uses the seasonally adjusted CPI",
        "index in RTDSM (BLS's headline 12-month figure uses the unadjusted index);",
        "'unemployment rose' compares the published rates (0.1 pp precision).",
        "",
        "## Date rules and filters",
        "",
        "- as_of_date: the first RTDSM vintage containing the period (first release);",
        "  periods 2016-2025, first released after the baseline vintage.",
        "- flip / control: revision_date = pinned latest vintage, >= 365 days after",
        "  as_of_date. flip: Yes/No differs; control: same answer, and |distance| <= the",
        "  control cap in both vintages (tighter than v0's 10 margins / 40k).",
        "- no_change: revision_date = last vintage of the unbroken run after the as-of",
        "  vintage in which every computation-window observation is identical (>= 1",
        "  vintage later; >= 90 days preferred); within the control cap.",
        "- Materiality (all kinds): |distance| >= margin in both vintages.",
        "- COVID exclusion (all kinds): computation window touching 2020-02..2021-03",
        "  (2020 Q1..2021 Q1 for GDP).",
        "",
        "Candidate counts per filter stage (instances = every series/template/period/",
        "threshold computable at first release):",
        "",
        "| series | instances | gap >= 365d | material | material, no COVID | flip "
        "| control (uncapped) | control (capped) | no-change identical | no_change |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for sid in [*sorted(k for k in counts if k != "all"), "all"]:
        r = counts[sid]
        lines.append(
            f"| {sid} | {r['instances']} | {r['gap_ok']} | {r['material']} "
            f"| {r['material_no_covid']} | {r['flip']} | {r['control_uncapped']} "
            f"| {r['control']} | {r['no_change_identical']} | {r['no_change']} |"
        )
    lines += [
        "",
        "## Selection",
        "",
        "`select_v1(candidates, seed=0)`: 20 flips, 20 controls, 5 no_change; as-of",
        "answers balanced Yes/No within each kind (10/10, 10/10, 3/2). Greedy and seeded:",
        "each slot takes the eligible candidate that overlaps the fewest already-selected",
        "same-series computation windows, then spreads series, each series' Yes/No",
        "answers, years and templates, then the seeded rank. Overlap is allowed only",
        "when a slot cannot otherwise be filled.",
        "",
        f"Unfilled slots: {sum(sel.shortfall.values())} "
        f"({', '.join(f'{k} {v}' for k, v in sel.shortfall.items())}). "
        f"Overlapping same-series pairs: {sel.overlaps}; clusters: "
        f"{len(set(clusters.values()))} for {len(tasks)} tasks.",
        "",
        "| kind | series | as-of Yes | as-of No |",
        "|---|---|---|---|",
    ]
    tally = Counter((t.kind, t.series_id, bool(t.gold_as_of)) for t in tasks)
    for kind in KINDS:
        for sid in sorted({t.series_id for t in tasks}):
            y, n = tally[(kind, sid, True)], tally[(kind, sid, False)]
            if y or n:
                lines.append(f"| {kind} | {sid} | {y} | {n} |")
    years = Counter(_d(t.period).year for t in tasks)
    lines += [
        "",
        "Tasks per period year: " + ", ".join(f"{y}: {years[y]}" for y in sorted(years)) + ".",
        "",
    ]
    lines += [
        "## Tasks",
        "",
        "| id | question | kind | as-of answer | revised answer | cluster |",
        "|---|---|---|---|---|---|",
    ]
    for t in tasks:
        lines.append(
            f"| {t.id} | {t.question} | {t.kind} | {_yn(t.gold_as_of)} "
            f"| {_yn(t.gold_revised)} | {clusters[t.id]} |"
        )
    return "\n".join(lines) + "\n"


# --- CLI --------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m vintagebench.tasks", description=__doc__.split("\n")[0]
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--build",
        action="store_true",
        help="write tasks/v1.jsonl, tasks/README.md and tasks/BASE_RATES.md",
    )
    g.add_argument("--base-rates", action="store_true", help="write tasks/BASE_RATES.md")
    p.add_argument("--root", type=Path, default=data.RAW_DIR, help="RTDSM data directory")
    p.add_argument("--out-dir", type=Path, default=TASKS_DIR)
    p.add_argument("--seed", type=int, default=SEED)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cands = build_candidates(data.SERIES_IDS, args.root)
    out: Path = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "BASE_RATES.md").write_text(render_base_rates(base_rates(cands, args.root)))
    if args.build:
        sel = select_v1_detailed(cands, args.seed)
        save_tasks(out / "v1.jsonl", sel.tasks)
        loaded = load_tasks(out / "v1.jsonl", args.root)  # round-trip check
        sel = Selection(loaded, sel.shortfall, sel.overlaps)
        (out / "README.md").write_text(render_readme(sel, filter_counts(cands), args.seed))
        print(f"wrote {len(loaded)} tasks; shortfall {sel.shortfall}; overlaps {sel.overlaps}")
    print(f"wrote {out / 'BASE_RATES.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
