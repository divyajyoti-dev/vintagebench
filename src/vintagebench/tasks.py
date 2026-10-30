"""Task schema, candidate generation and pilot selection (SPEC §3, §5).

Gold answers are computed by small pure functions over a *snapshot*: the
``pd.Series`` returned by :func:`vintagebench.data.get_as_of` (values indexed by
observation_date, as known on one date). Each SPEC §3 template has one gold
function. A gold function returns ``None`` when an observation it needs is missing
(or NaN); such candidates are skipped, never guessed.

Date rules (applied by :func:`build_candidates`, per target observation ``t``):

- ``as_of_date`` = the first vintage date on which ``t`` appears, i.e. the
  observation's first release. The question is therefore answerable from the
  as-of vintage alone (it is skipped if any other needed observation is missing).
- ``revision_date`` = the first vintage date at least one year after
  ``as_of_date``; if no such vintage exists, the latest vintage date after
  ``as_of_date``. Candidates with no later vintage are skipped.
- ``flips`` = ``gold_as_of != gold_revised``.
- Targets whose first vintage predates 2016-01-01 are skipped: the earliest stored
  vintage of each series is a baseline (data as of 2016-01-01), not a first release.

Every gold answer is computed within one snapshot (one vintage); levels are never
compared across vintages, so base-year rebasings (GDPC1/PCEPI 2018-07, 2023-09;
INDPRO 2021-05-28) cannot affect a gold answer. Only the resulting booleans are
compared across vintages (``flips``).

Regenerate the pilot with ``python -m vintagebench.tasks`` (writes
tasks/pilot.jsonl and tasks/README.md from data/vintages/).

Only target observations dated 2016-01-01 .. 2025-12-31 are used (SPEC §3).
All comparisons are strict; exact ties (within ``EPS``) count as "no".

Materiality margin: a candidate is kept only if, in BOTH vintages, the deciding
quantity is clear of its threshold by at least the margin below (half the 0.1
publication unit, or stricter), so no gold answer hinges on a difference below
published precision:

- GDPC1 shrink: |quarter-over-quarter % change, non-annualized| >= 0.05 (about 0.2pp
  annualized; stricter than half the 0.1 unit BEA uses for annualized growth)
- GDPC1 growth above 2%: |annualized QoQ growth - 2.0| >= 0.2 percentage points,
  the annualized equivalent of the 0.05 non-annualized GDP margin (see
  ``GDP_ANNUALIZED_MARGIN``)
- INDPRO: |month-over-month % change| >= 0.05
- PCEPI: |12-month % change - 2.5| >= 0.05 percentage points
- PAYEMS 3-month average: |average - threshold| >= 1 (thousand jobs)
- PAYEMS weakest-12m: |change(t) - min(change(t-11) .. change(t-1))| >= 1 (thousand)
- UNRATE: none (values are compared after rounding to the published 0.1).

COVID exclusion (controls only, applied in :func:`select_pilot`): a control is
never selected if any observation its answer reads falls in the COVID collapse,
i.e. a month from 2020-03 to 2020-06 for monthly series, or for GDPC1 any quarter
containing such a month (2020 Q1, Q2) plus the rebound quarter 2020 Q3. Such
controls are trivially decided by the collapse. The window is the
target period plus the template's ``lookback_months`` (e.g. 3 for the payroll
3-month average, 12 for weakest-of-12 and PCE YoY). Flips there stay eligible.

Non-trivial controls (applied in :func:`select_pilot`): each candidate's distance
from the threshold, in units of the template's materiality margin, is computed
numerically in both vintages (unrounded; kept as an internal attribute, not
serialized, and recomputed from the vintage data after :func:`load_tasks`; the
notes only display it). A non-UNRATE control is never selected if
that distance exceeds the template's ``control_cap`` in BOTH vintages (it is
obvious from the era alone). Caps: 10 margins for INDPRO (0.5% MoM), PCEPI
(0.5pp) and GDPC1 growth (2pp annualized); 5 margins for GDPC1 shrink (0.25% QoQ,
about 1pp annualized); 40 margins
(40k jobs) for both PAYEMS templates. UNRATE controls and all flips are exempt.
"""

from __future__ import annotations

import dataclasses
import json
import math
import random
import warnings
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd

from vintagebench import data

AnswerType = Literal["yes_no", "number"]
Answer = bool | float

EPS = 1e-9  # float tolerance: |a - b| <= EPS is a tie
FIRST_YEAR, LAST_YEAR = 2016, 2025
BASELINE_CUTOFF = date(2016, 1, 1)  # vintages before this are the pre-2016 baseline
CONTROL_SERIES = "UNRATE"
N_CONTROL_SERIES = 2


@dataclass(frozen=True)
class Task:
    """One benchmark task; one line of tasks/pilot.jsonl.

    Dates are ISO strings (YYYY-MM-DD). Gold answers are computed
    programmatically from the as-of and revision vintages, never hand-labeled.
    """

    id: str
    series_id: str
    as_of_date: str
    question: str
    answer_type: AnswerType
    gold_as_of: Answer
    revision_date: str
    gold_revised: Answer
    flips: bool
    notes: str = ""


# ---------------------------------------------------------------------------
# Snapshot helpers (pure)
# ---------------------------------------------------------------------------


def _normalize(snapshot: pd.Series) -> pd.Series:
    """Index by Timestamp, drop NaN values, sort by observation date."""
    s = snapshot.dropna().astype(float)
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _shift(t: pd.Timestamp, months: int) -> pd.Timestamp:
    return pd.Timestamp(t) + pd.DateOffset(months=months)


def _value(s: pd.Series, t: pd.Timestamp) -> float | None:
    v = s.get(pd.Timestamp(t))
    return None if v is None or pd.isna(v) else float(v)


def change(snapshot: pd.Series, t: pd.Timestamp, months: int = 1) -> float | None:
    """Level at ``t`` minus level ``months`` earlier; None if either is missing."""
    s = _normalize(snapshot)
    now, before = _value(s, t), _value(s, _shift(t, -months))
    return None if now is None or before is None else now - before


def monthly_changes(snapshot: pd.Series, t: pd.Timestamp, n: int) -> list[float] | None:
    """One-month changes for the ``n`` months ending at ``t`` (oldest first)."""
    out = [change(snapshot, _shift(t, -k)) for k in range(n - 1, -1, -1)]
    return None if any(c is None for c in out) else [float(c) for c in out]  # type: ignore[arg-type]


def avg_change_3m(snapshot: pd.Series, t: pd.Timestamp) -> float | None:
    """Average one-month change over the 3 months ending at ``t``: (L_t - L_{t-3}) / 3."""
    d = change(snapshot, t, months=3)
    return None if d is None else d / 3


def yoy_pct(snapshot: pd.Series, t: pd.Timestamp) -> float | None:
    """Unrounded 12-month percent change: 100 * (L_t / L_{t-12} - 1)."""
    s = _normalize(snapshot)
    now, before = _value(s, t), _value(s, _shift(t, -12))
    if now is None or before is None or before == 0:
        return None
    return 100.0 * (now / before - 1.0)


def pct_change(snapshot: pd.Series, t: pd.Timestamp, months: int = 1) -> float | None:
    """Unrounded percent change over ``months``: 100 * (L_t / L_{t-months} - 1)."""
    s = _normalize(snapshot)
    now, before = _value(s, t), _value(s, _shift(t, -months))
    if now is None or before is None or before == 0:
        return None
    return 100.0 * (now / before - 1.0)


# ---------------------------------------------------------------------------
# Materiality margins (pure): distance of the deciding quantity from its threshold
# ---------------------------------------------------------------------------

# Half the 0.1 publication unit for INDPRO % changes and the PCE YoY rate. For GDPC1
# the same 0.05 applies to the non-annualized QoQ % change, i.e. about 0.2pp
# annualized: stricter than half of BEA's 0.1 unit for annualized growth.
PCT_MARGIN = 0.05
PAYROLL_MARGIN_K = 1.0  # PAYEMS is published in whole thousands


def gdp_margin(snapshot: pd.Series, quarter: pd.Timestamp) -> float | None:
    """GDPC1: |quarter-over-quarter % change, non-annualized| (threshold 0)."""
    p = pct_change(snapshot, quarter, months=3)
    return None if p is None else abs(p)


# Annualized margin for the GDP growth template. The shrink margin is 0.05%
# non-annualized; annualizing maps a non-annualized change g to 100*((1+g/100)^4-1),
# whose slope is 4*(1+g/100)^3: about 4.0 near 0% and about 4.06 near 2% annualized
# (g ~ 0.5%), so 0.05 maps to about 0.20pp. We use 0.2pp.
GDP_ANNUALIZED_MARGIN = 0.2
GDP_GROWTH_THRESHOLD = 2.0


def annualized_qoq_pct(snapshot: pd.Series, quarter: pd.Timestamp) -> float | None:
    """Unrounded annualized QoQ growth: 100 * ((L_q / L_{q-1 quarter})^4 - 1)."""
    s = _normalize(snapshot)
    now, before = _value(s, quarter), _value(s, _shift(quarter, -3))
    if now is None or before is None or before <= 0:
        return None
    return 100.0 * ((now / before) ** 4 - 1.0)


def gdp_growth_margin(
    snapshot: pd.Series, quarter: pd.Timestamp, threshold_pct: float = GDP_GROWTH_THRESHOLD
) -> float | None:
    """GDPC1: |annualized QoQ growth - threshold| in percentage points."""
    a = annualized_qoq_pct(snapshot, quarter)
    return None if a is None else abs(a - threshold_pct)


def mom_pct_margin(snapshot: pd.Series, month: pd.Timestamp) -> float | None:
    """INDPRO: |month-over-month % change| (threshold 0)."""
    p = pct_change(snapshot, month)
    return None if p is None else abs(p)


def pce_margin(
    snapshot: pd.Series, month: pd.Timestamp, threshold_pct: float = 2.5
) -> float | None:
    """PCEPI: |12-month % change - threshold| in percentage points."""
    y = yoy_pct(snapshot, month)
    return None if y is None else abs(y - threshold_pct)


def payrolls_3m_margin(
    snapshot: pd.Series, month: pd.Timestamp, threshold_k: float
) -> float | None:
    """PAYEMS: |3-month average change - threshold| in thousands."""
    a = avg_change_3m(snapshot, month)
    return None if a is None else abs(a - threshold_k)


def payrolls_weakest_margin(snapshot: pd.Series, month: pd.Timestamp) -> float | None:
    """PAYEMS: |change(t) - min of the 11 preceding changes| in thousands.

    For a "yes" this is how much the month wins by; for a "no" how far it is above
    the weakest earlier month.
    """
    changes = monthly_changes(snapshot, month, 12)
    return None if changes is None else abs(changes[-1] - min(changes[:-1]))


def prior_11_min_change(snapshot: pd.Series, month: pd.Timestamp) -> float | None:
    """PAYEMS: the minimum one-month change over the 11 months before ``month``."""
    changes = monthly_changes(snapshot, month, 12)
    return None if changes is None else min(changes[:-1])


def is_material(margin: float | None, minimum: float) -> bool:
    """True iff ``margin`` is known and >= ``minimum`` (within EPS)."""
    return margin is not None and margin >= minimum - EPS


# ---------------------------------------------------------------------------
# Gold functions, one per SPEC §3 template (pure)
# ---------------------------------------------------------------------------


def real_gdp_shrank(snapshot: pd.Series, quarter: pd.Timestamp) -> bool | None:
    """GDPC1: yes iff real GDP in ``quarter`` < real GDP in the previous quarter.

    ``quarter`` is the quarter's first day (ALFRED convention). Tie -> no.
    """
    d = change(snapshot, quarter, months=3)
    return None if d is None else d < -EPS


def real_gdp_grew_faster_than(
    snapshot: pd.Series, quarter: pd.Timestamp, threshold_pct: float = GDP_GROWTH_THRESHOLD
) -> bool | None:
    """GDPC1: yes iff annualized QoQ growth 100*((L_q/L_{q-1})^4 - 1) > threshold.

    Unrounded; a tie (within EPS) -> no.
    """
    a = annualized_qoq_pct(snapshot, quarter)
    return None if a is None else a > threshold_pct + EPS


def payrolls_weakest_in_12m(snapshot: pd.Series, month: pd.Timestamp) -> bool | None:
    """PAYEMS: yes iff ``month``'s one-month change is strictly lower than each of
    the 11 preceding months' one-month changes.

    "The prior 12 months" is read as the 12-month window ending in (and including)
    ``month``. Needs 13 levels (t-12 .. t). A tie with any earlier month -> no.
    """
    changes = monthly_changes(snapshot, month, 12)
    if changes is None:
        return None
    this, earlier = changes[-1], changes[:-1]
    return all(this < c - EPS for c in earlier)


def payrolls_3m_avg_above(
    snapshot: pd.Series, month: pd.Timestamp, threshold_k: float
) -> bool | None:
    """PAYEMS (thousands): yes iff (L_t - L_{t-3}) / 3 > ``threshold_k``. Tie -> no."""
    d = change(snapshot, month, months=3)
    return None if d is None else d > 3 * threshold_k + EPS


def fell_vs_prior_month(snapshot: pd.Series, month: pd.Timestamp) -> bool | None:
    """Yes iff the level in ``month`` < the level in the prior month. Tie -> no.

    Used for INDPRO ("Did industrial production fall in <month>?").
    """
    d = change(snapshot, month)
    return None if d is None else d < -EPS


def industrial_production_fell(snapshot: pd.Series, month: pd.Timestamp) -> bool | None:
    """INDPRO: alias of :func:`fell_vs_prior_month`."""
    return fell_vs_prior_month(snapshot, month)


def pce_yoy_above(
    snapshot: pd.Series, month: pd.Timestamp, threshold_pct: float = 2.5
) -> bool | None:
    """PCEPI: yes iff the unrounded 12-month % change in the index > ``threshold_pct``.

    Tie (within EPS) -> no. Note BEA reports this rate rounded to 0.1; we use the
    unrounded value and say so in the question.
    """
    y = yoy_pct(snapshot, month)
    return None if y is None else y > threshold_pct + EPS


def unrate_rose(snapshot: pd.Series, month: pd.Timestamp) -> bool | None:
    """UNRATE control: yes iff the rate in ``month`` > the rate in the prior month.

    Design choice: SPEC §3 has no UNRATE template, so UNRATE (the low-revision
    control series) gets the analogue of the INDPRO question: "Did the
    unemployment rate rise in <month> versus the prior month?". Both values are
    rounded to 0.1 (the published precision) before comparing, so float noise or
    stray extra digits never create a change; equal rounded rates -> no.
    """
    s = _normalize(snapshot)
    now, before = _value(s, month), _value(s, _shift(month, -1))
    if now is None or before is None:
        return None
    return round(now, 1) > round(before, 1)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def _month(t: pd.Timestamp) -> str:
    return pd.Timestamp(t).strftime("%B %Y")


def _quarter(t: pd.Timestamp) -> str:
    t = pd.Timestamp(t)
    return f"Q{t.quarter} {t.year}"


@dataclass(frozen=True)
class Template:
    """A question template bound to one series.

    ``gold`` and ``metric`` are pure functions of (snapshot, target period);
    ``metric`` is the underlying number, reported in ``notes``.
    """

    key: str
    months_per_period: int  # 1 = monthly, 3 = quarterly
    question: Callable[[pd.Timestamp], str]
    gold: Callable[[pd.Series, pd.Timestamp], bool | None]
    metric: Callable[[pd.Series, pd.Timestamp], float | None]
    metric_name: str
    definition: str
    margin: Callable[[pd.Series, pd.Timestamp], float | None] | None = None
    min_margin: float = 0.0
    materiality: str = "none"
    lookback_months: int = 1  # how far before the target the answer reads data
    # Optional second quantity reported in notes (e.g. the weakest-12m comparison).
    metric2: Callable[[pd.Series, pd.Timestamp], float | None] | None = None
    metric2_name: str = ""
    # Non-trivial control cap, in margin units (None: no cap).
    control_cap: float | None = None


def fell_vs_prior_month_template(label: str, key: str = "mom-fall") -> Template:
    """'Did <label> fall in <month> versus the prior month?' (INDPRO; reusable in tests)."""
    return Template(
        key=key,
        months_per_period=1,
        question=lambda t: (
            f"Did {label} fall in {_month(t)} versus the prior month, i.e. was its "
            f"level in {_month(t)} lower than in {_month(_shift(t, -1))}?"
        ),
        gold=fell_vs_prior_month,
        metric=lambda s, t: pct_change(s, t),
        metric_name="one-month % change",
        definition="yes iff level(t) < level(t-1 month); a tie is no.",
        margin=mom_pct_margin,
        min_margin=PCT_MARGIN,
        materiality="|100 * (level(t) / level(t-1 month) - 1)| >= 0.05",
        control_cap=10.0,
    )


def _payrolls_3m_template(threshold_k: int) -> Template:
    return Template(
        key=f"avg3m-above-{threshold_k}k",
        months_per_period=1,
        question=lambda t: (
            "Was average monthly payroll growth over the 3 months ending "
            f"{_month(t)} above {threshold_k}k, i.e. is (level({_month(t)}) - "
            f"level({_month(_shift(t, -3))})) / 3 above {threshold_k}, with total nonfarm "
            "payrolls (PAYEMS) in thousands of jobs?"
        ),
        gold=lambda s, t: payrolls_3m_avg_above(s, t, threshold_k),
        metric=avg_change_3m,
        metric_name="3-month average change (thousands)",
        definition=(
            f"PAYEMS in thousands; yes iff (level(t) - level(t-3 months)) / 3 > "
            f"{threshold_k}; a tie is no."
        ),
        margin=lambda s, t: payrolls_3m_margin(s, t, threshold_k),
        min_margin=PAYROLL_MARGIN_K,
        materiality=f"|3-month average - {threshold_k}| >= 1 (thousand)",
        lookback_months=3,
        control_cap=40.0,
    )


TEMPLATES: dict[str, tuple[Template, ...]] = {
    "GDPC1": (
        Template(
            key="qoq-shrink",
            months_per_period=3,
            question=lambda t: (
                f"Did real GDP shrink in {_quarter(t)}, i.e. was real GDP (GDPC1) in "
                f"{_quarter(t)} lower than in {_quarter(_shift(t, -3))}?"
            ),
            gold=real_gdp_shrank,
            metric=lambda s, t: pct_change(s, t, months=3),
            metric_name="quarter-over-quarter % change (non-annualized)",
            definition="yes iff level(q) < level(q-1 quarter); a tie is no.",
            margin=gdp_margin,
            min_margin=PCT_MARGIN,
            materiality=(
                "|QoQ % change, non-annualized| >= 0.05 (about 0.2pp annualized; stricter "
                "than half the 0.1 publication unit)"
            ),
            lookback_months=3,
            control_cap=5.0,
        ),
        Template(
            key="growth-above-2",
            months_per_period=3,
            question=lambda t: (
                f"Did real GDP grow faster than 2% (annualized) in {_quarter(t)}, i.e. was "
                f"the annualized growth rate of real GDP (GDPC1) from {_quarter(_shift(t, -3))} "
                f"to {_quarter(t)}, 100 * ((level({_quarter(t)}) / "
                f"level({_quarter(_shift(t, -3))}))^4 - 1), above 2.0%?"
            ),
            gold=real_gdp_grew_faster_than,
            metric=annualized_qoq_pct,
            metric_name="annualized QoQ growth (%)",
            definition=(
                "yes iff 100 * ((level(q) / level(q-1 quarter))^4 - 1) > 2.0, unrounded; "
                "a tie is no."
            ),
            margin=gdp_growth_margin,
            min_margin=GDP_ANNUALIZED_MARGIN,
            materiality=(
                "|annualized QoQ growth - 2.0| >= 0.2 (percentage points; the annualized "
                "equivalent of the 0.05 non-annualized GDP margin)"
            ),
            lookback_months=3,
            control_cap=10.0,
        ),
    ),
    "PAYEMS": (
        Template(
            key="weakest-12m",
            months_per_period=1,
            question=lambda t: (
                f"Was {_month(t)} the weakest of the 12 months ending in {_month(t)} "
                f"for payroll growth, i.e. is change({_month(t)}) lower than each of "
                f"change({_month(_shift(t, -11))}) through change({_month(_shift(t, -1))}), "
                "where change(month) = level(month) - level(previous month), with total "
                "nonfarm payrolls (PAYEMS) in thousands of jobs?"
            ),
            gold=payrolls_weakest_in_12m,
            metric=lambda s, t: change(s, t),
            metric_name="one-month change (thousands)",
            metric2=prior_11_min_change,
            metric2_name="minimum one-month change of the prior 11 months (thousands)",
            definition=(
                "yes iff change(t) is strictly lower than each of change(t-1) .. "
                "change(t-11), where change(m) = level(m) - level(m-1); any tie is no."
            ),
            margin=payrolls_weakest_margin,
            min_margin=PAYROLL_MARGIN_K,
            materiality="|change(t) - min(change(t-11) .. change(t-1))| >= 1 (thousand)",
            lookback_months=12,
            control_cap=40.0,
        ),
        _payrolls_3m_template(100),
        _payrolls_3m_template(150),
    ),
    "INDPRO": (fell_vs_prior_month_template("industrial production (INDPRO)"),),
    "PCEPI": (
        Template(
            key="yoy-above-2.5",
            months_per_period=1,
            question=lambda t: (
                f"Is PCE inflation (year over year) above 2.5% for {_month(t)}, i.e. "
                f"is the 12-month percent change in the PCE price index (PCEPI) from "
                f"{_month(_shift(t, -12))} to {_month(t)}, 100 * (level({_month(t)}) / "
                f"level({_month(_shift(t, -12))}) - 1), above 2.5?"
            ),
            gold=lambda s, t: pce_yoy_above(s, t, 2.5),
            metric=yoy_pct,
            metric_name="12-month % change",
            definition="yes iff 100 * (level(t) / level(t-12 months) - 1) > 2.5, unrounded.",
            margin=lambda s, t: pce_margin(s, t, 2.5),
            min_margin=PCT_MARGIN,
            materiality="|12-month % change - 2.5| >= 0.05 (percentage points)",
            lookback_months=12,
            control_cap=10.0,
        ),
    ),
    "UNRATE": (
        Template(
            key="mom-rise",
            months_per_period=1,
            question=lambda t: (
                f"Did the unemployment rate (UNRATE) rise in {_month(t)} versus the "
                f"prior month, i.e. was it higher than in {_month(_shift(t, -1))} "
                "(as published, to one decimal place)?"
            ),
            gold=unrate_rose,
            metric=lambda s, t: change(s, t),
            metric_name="one-month change (percentage points)",
            definition="yes iff round(rate(t), 1) > round(rate(t-1 month), 1); equal is no.",
            materiality="none (compared at the published 0.1 precision)",
        ),
    ),
}


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------


def revision_date_for(as_of: date, vintages: list[date]) -> date | None:
    """First vintage >= as_of + 1 year; else the latest vintage after as_of; else None."""
    later = sorted(v for v in vintages if v > as_of)
    if not later:
        return None
    target = (pd.Timestamp(as_of) + pd.DateOffset(years=1)).date()
    return next((v for v in later if v >= target), later[-1])


def _materiality_note(template: Template) -> str:
    if template.margin is None:
        return f"Materiality filter: {template.materiality}."
    return f"Kept only if, in both vintages, {template.materiality}."


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.4g}"


def _task_id(series_id: str, template: Template, t: pd.Timestamp) -> str:
    return f"{series_id.lower()}-{template.key}-{pd.Timestamp(t):%Y-%m}"


def build_candidates(series_ids: Iterable[str], root: Path) -> list[Task]:
    """Generate all candidate tasks from the SPEC §3 templates for ``series_ids``.

    ``root`` is the vintage data directory. Gold answers are computed from vintages
    via :func:`vintagebench.data.get_as_of` (date rules in the module docstring).
    """
    out: list[Task] = []
    for series_id in series_ids:
        if series_id not in TEMPLATES:
            raise ValueError(f"no task template for series {series_id!r}")
        out.extend(_series_candidates(series_id, root))
    return out


def _series_candidates(series_id: str, root: Path) -> list[Task]:
    raw = data.load_vintages(series_id, root)
    first_release = raw.groupby("observation_date")["vintage_date"].min()
    vintages = sorted(pd.Timestamp(v).date() for v in data.vintage_dates(series_id, root))
    snapshots: dict[date, pd.Series] = {}

    def snap(d: date) -> pd.Series:
        if d not in snapshots:
            snapshots[d] = data.get_as_of(series_id, d, root)
        return snapshots[d]

    tasks: list[Task] = []
    for obs, first in sorted(first_release.items()):
        t = pd.Timestamp(obs)
        if not FIRST_YEAR <= t.year <= LAST_YEAR:
            continue
        as_of = pd.Timestamp(first).date()
        if as_of < BASELINE_CUTOFF:
            continue  # pre-2016 baseline vintage: not a genuine first release
        revised = revision_date_for(as_of, vintages)
        if revised is None:
            continue
        for template in TEMPLATES[series_id]:
            if (t.month - 1) % template.months_per_period:
                continue
            task = _make_task(series_id, template, t, as_of, revised, snap)
            if task is not None:
                tasks.append(task)
    return tasks


def _make_task(
    series_id: str,
    template: Template,
    t: pd.Timestamp,
    as_of: date,
    revised: date,
    snap: Callable[[date], pd.Series],
) -> Task | None:
    s_as_of, s_rev = snap(as_of), snap(revised)
    gold_as_of, gold_rev = template.gold(s_as_of, t), template.gold(s_rev, t)
    if gold_as_of is None or gold_rev is None:
        return None  # missing data in either vintage: skip, never guess
    if template.margin is not None and not all(
        is_material(template.margin(s, t), template.min_margin) for s in (s_as_of, s_rev)
    ):
        return None  # answer hinges on a difference below published precision
    notes = (
        f"Definition: {template.definition} {_materiality_note(template)} "
        "as_of_date = first release of the target observation; "
        "revision_date = first vintage >= 1 year later (else latest). "
        f"{template.metric_name}: as-of {_fmt(template.metric(s_as_of, t))}, "
        f"revised {_fmt(template.metric(s_rev, t))}."
    )
    if template.metric2 is not None:
        notes += (
            f" {template.metric2_name}: as-of {_fmt(template.metric2(s_as_of, t))}, "
            f"revised {_fmt(template.metric2(s_rev, t))}."
        )
    dist = _distances(template, s_as_of, s_rev, t)
    if dist is not None:
        notes += f" {DISTANCE_LABEL}: as-of {dist[0]:.4f}, revised {dist[1]:.4f}."
    task = Task(
        id=_task_id(series_id, template, t),
        series_id=series_id,
        as_of_date=as_of.isoformat(),
        question=template.question(t),
        answer_type="yes_no",
        gold_as_of=bool(gold_as_of),
        revision_date=revised.isoformat(),
        gold_revised=bool(gold_rev),
        flips=bool(gold_as_of) != bool(gold_rev),
        notes=notes,
    )
    if dist is not None:
        _attach_distances(task, dist)
    return task


DISTANCE_LABEL = "Distance from threshold in margin units"
_DIST_ATTR = "_threshold_distances"  # internal, not a dataclass field: never serialized


def _distances(
    template: Template, s_as_of: pd.Series, s_rev: pd.Series, t: pd.Timestamp
) -> tuple[float, float] | None:
    """Unrounded (as-of, revised) |quantity - threshold| / margin; None if no margin."""
    if template.margin is None or template.min_margin <= 0:
        return None
    a, r = template.margin(s_as_of, t), template.margin(s_rev, t)
    if a is None or r is None:
        return None
    return a / template.min_margin, r / template.min_margin


def _attach_distances(task: Task, dist: tuple[float, float]) -> None:
    object.__setattr__(task, _DIST_ATTR, dist)  # frozen dataclass: internal cache only


# ---------------------------------------------------------------------------
# Pilot selection
# ---------------------------------------------------------------------------


def _period_key(task: Task) -> str:
    """Target period 'YYYY-MM' (from the id suffix; falls back to as_of_date)."""
    suffix = task.id[-7:]
    if len(suffix) == 7 and suffix[4] == "-" and suffix.replace("-", "").isdigit():
        return suffix
    return task.as_of_date[:7]


def _template_key(task: Task) -> str:
    return task.id[: -len(_period_key(task)) - 1] if task.id.endswith(_period_key(task)) else ""


# COVID collapse periods (observation dates) that make a control trivially decided.
COVID_MONTHS = (date(2020, 3, 1), date(2020, 6, 1))  # monthly series, inclusive
# Quarters containing a COVID month (2020 Q1 holds March, Q2 holds Apr-Jun) plus the
# rebound quarter 2020 Q3. 2020 Q4 is excluded via its one-quarter lookback to Q3.
COVID_QUARTERS = frozenset({date(2020, 1, 1), date(2020, 4, 1), date(2020, 7, 1)})


def template_for(task: Task) -> Template | None:
    """The template that generated ``task`` (from its id), or None if unknown."""
    key = _template_key(task)
    for tp in TEMPLATES.get(task.series_id, ()):
        if f"{task.series_id.lower()}-{tp.key}" == key:
            return tp
    return None


def covid_window_overlap(task: Task) -> bool:
    """True iff any observation the task's answer reads is in the COVID collapse.

    The window is the target period and every period up to ``lookback_months``
    before it (step = the template's period length). Monthly: any month 2020-03 ..
    2020-06; quarterly: 2020 Q1 or Q2 (they contain such a month) or the rebound
    quarter 2020 Q3. Unknown templates use the target alone.
    """
    tp = template_for(task)
    lookback = tp.lookback_months if tp else 0
    step = tp.months_per_period if tp else 1
    t = pd.Timestamp(_period_key(task) + "-01")
    window = [_shift(t, -k).date() for k in range(0, lookback + 1, step)]
    if step == 3:
        return any(d in COVID_QUARTERS for d in window)
    return any(COVID_MONTHS[0] <= d <= COVID_MONTHS[1] for d in window)


def threshold_distances(task: Task, root: Path | None = None) -> tuple[float, float]:
    """Unrounded (as-of, revised) distance from the threshold in margin units.

    Uses the value computed by :func:`build_candidates` when present; otherwise
    (e.g. after :func:`load_tasks`) recomputes it from the vintage data under
    ``root`` (default ``data.DATA_DIR``) and caches it on the task. Raises
    ``ValueError`` if the template has no margin or the data cannot provide it.
    """
    cached = getattr(task, _DIST_ATTR, None)
    if cached is not None:
        return cached
    tp = template_for(task)
    if tp is None or tp.margin is None:
        raise ValueError(f"{task.id}: no template margin to compute a distance")
    t = pd.Timestamp(_period_key(task) + "-01")
    src = data.DATA_DIR if root is None else root
    try:
        snaps = [
            data.get_as_of(task.series_id, date.fromisoformat(d), src)
            for d in (task.as_of_date, task.revision_date)
        ]
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError(f"{task.id}: cannot load vintages to compute distance") from exc
    dist = _distances(tp, snaps[0], snaps[1], t)
    if dist is None or not all(math.isfinite(x) for x in dist):
        raise ValueError(f"{task.id}: distance from threshold is missing in the data")
    _attach_distances(task, dist)
    return dist


def trivial_control(task: Task, root: Path | None = None) -> bool:
    """True iff ``task`` is a non-UNRATE control that is far from the line in BOTH
    vintages: unrounded distance > the template's ``control_cap`` (margin units).

    Flips, UNRATE controls and templates without a cap are never trivial. For a
    capped template the distance is required: if it is neither attached nor
    computable from the data, :func:`threshold_distances` raises ``ValueError``.
    """
    if task.flips or task.series_id == CONTROL_SERIES:
        return False
    tp = template_for(task)
    if tp is None or tp.control_cap is None:
        return False
    return min(threshold_distances(task, root)) > tp.control_cap


def _eligible_control(task: Task) -> bool:
    return not covid_window_overlap(task) and not trivial_control(task)


def select_pilot(candidates: list[Task], n: int = 20, seed: int = 0) -> list[Task]:
    """Select a seeded, balanced pilot set (~half flips, spread across series/years).

    Algorithm: drop duplicate ids and targets outside 2016–2025; shuffle with
    ``random.Random(seed)``. Stratify on (flips, gold_as_of) so that the as-of
    answer is ~half Yes / ~half No within flips and within controls:

    - flips (non-UNRATE): ``n // 2``, split Yes/No as evenly as possible;
    - UNRATE controls: exactly 2 (one Yes, one No when available);
    - other controls: the rest, split so controls overall are ~half Yes.

    Controls whose window overlaps the COVID collapse (:func:`covid_window_overlap`)
    and non-UNRATE controls far from the line in both vintages
    (:func:`trivial_control`) are never selected; flips are unaffected.

    Strata are filled round-robin, one task at a time; each pick is greedy: the
    candidate whose series is least used among already chosen tasks with the same
    flips value, then whose series, template and year are least used overall (in
    that order), ties broken by the shuffled order. At most one task per (series,
    target period). A short stratum is filled first from its sibling (same group,
    other answer), then from any non-UNRATE candidate; every shortfall is reported
    in a warning. Output is sorted by id.
    """
    rng = random.Random(seed)
    unique = {t.id: t for t in sorted(candidates, key=lambda t: t.id)}
    pool = [t for t in unique.values() if FIRST_YEAR <= int(_period_key(t)[:4]) <= LAST_YEAR]
    rng.shuffle(pool)

    def stratum(flips: bool, yes: bool, unrate: bool) -> list[Task]:
        return [
            t
            for t in pool
            if t.flips == flips
            and (flips or _eligible_control(t))
            and bool(t.gold_as_of) == yes
            and (t.series_id == CONTROL_SERIES) == unrate
            and not (flips and unrate)
        ]

    n_flip = n // 2
    n_ctrl = n - n_flip
    n_unr = min(N_CONTROL_SERIES, n_ctrl)
    n_other = n_ctrl - n_unr  # >= 0
    ctrl_yes = min(max(n_ctrl - n_ctrl // 2 - n_unr // 2, 0), n_other)
    ctrl_no = max(n_other - ctrl_yes, 0)
    groups = [  # (name, [(stratum name, pool, quota), ...])
        (
            "flips",
            [
                ("flip/as-of Yes", stratum(True, True, False), n_flip - n_flip // 2),
                ("flip/as-of No", stratum(True, False, False), n_flip // 2),
            ],
        ),
        (
            f"{CONTROL_SERIES} controls",
            [
                (f"{CONTROL_SERIES} control/as-of Yes", stratum(False, True, True), n_unr // 2),
                (
                    f"{CONTROL_SERIES} control/as-of No",
                    stratum(False, False, True),
                    n_unr - n_unr // 2,
                ),
            ],
        ),
        (
            "controls",
            [
                ("control/as-of Yes", stratum(False, True, False), ctrl_yes),
                ("control/as-of No", stratum(False, False, False), ctrl_no),
            ],
        ),
    ]
    strata = [st for _, sts in groups for st in sts]

    picker = _Picker()
    got = {name: 0 for name, _, _ in strata}
    active = True
    while active:  # round-robin over strata
        active = False
        for name, spool, quota in strata:
            if got[name] < quota and picker.take(spool, 1):
                got[name] += 1
                active = True
    for _, sts in groups:  # sibling fallback, keeps the group's size
        deficit = sum(q for _, _, q in sts) - sum(got[name] for name, _, _ in sts)
        picker.take([t for _, sp, _ in sts for t in sp], deficit)
    others = [
        t for t in pool if t.series_id != CONTROL_SERIES and (t.flips or _eligible_control(t))
    ]
    picker.take(others, n - len(picker.chosen))

    chosen = picker.chosen[:n]  # quotas sum to n; the slice is only a guard
    short = [f"{name} {got[name]}/{quota}" for name, _, quota in strata if got[name] < quota]
    if short or len(chosen) < n:
        n_flips = sum(t.flips for t in chosen)
        n_yes = sum(bool(t.gold_as_of) for t in chosen)
        warnings.warn(
            f"select_pilot: strata short (got/wanted): {', '.join(short) or 'none'}; "
            f"got {len(chosen)}/{n} tasks: {n_flips} flips, {n_yes} as-of Yes.",
            stacklevel=2,
        )
    return sorted(chosen, key=lambda t: t.id)


class _Picker:
    """Greedy spread-maximizing picker with shared usage counters."""

    def __init__(self) -> None:
        self.chosen: list[Task] = []
        self.ids: set[str] = set()
        self.series: Counter[str] = Counter()
        self.series_group: Counter[tuple[str, bool]] = Counter()
        self.templates: Counter[str] = Counter()
        self.years: Counter[str] = Counter()
        self.targets: set[tuple[str, str]] = set()

    def take(self, pool: list[Task], k: int) -> int:
        """Pick up to ``k`` tasks from ``pool``; return how many were picked."""
        taken = 0
        for _ in range(max(k, 0)):
            avail = [
                (i, t)
                for i, t in enumerate(pool)
                if t.id not in self.ids and (t.series_id, _period_key(t)) not in self.targets
            ]
            if not avail:
                break
            _, best = min(avail, key=lambda it: (*self._score(it[1]), it[0]))
            self.chosen.append(best)
            self.ids.add(best.id)
            self.series[best.series_id] += 1
            self.series_group[(best.series_id, best.flips)] += 1
            self.templates[_template_key(best)] += 1
            self.years[_period_key(best)[:4]] += 1
            self.targets.add((best.series_id, _period_key(best)))
            taken += 1
        return taken

    def _score(self, t: Task) -> tuple[int, int, int, int]:
        return (
            self.series_group[(t.series_id, t.flips)],
            self.series[t.series_id],
            self.templates[_template_key(t)],
            self.years[_period_key(t)[:4]],
        )


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def save_tasks(path: Path, tasks: Iterable[Task]) -> None:
    """Write tasks to ``path`` as JSON Lines, one Task per line (field order kept)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(dataclasses.asdict(t)) for t in tasks]
    path.write_text("".join(line + "\n" for line in lines))


def load_tasks(path: Path) -> list[Task]:
    """Read tasks from a JSON Lines file written by :func:`save_tasks`."""
    text = Path(path).read_text()
    return [Task(**json.loads(line)) for line in text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Pilot generation entry point
# ---------------------------------------------------------------------------

SERIES = ("GDPC1", "PAYEMS", "INDPRO", "PCEPI", "UNRATE")
TASKS_DIR: Path = Path(__file__).resolve().parents[2] / "tasks"
PILOT_SEED = 0
PILOT_N = 20


def _yes_no(answer: Answer) -> str:
    if isinstance(answer, bool):
        return "Yes" if answer else "No"
    return f"{answer:g}"


def render_readme(candidates: list[Task], pilot: list[Task], seed: int) -> str:
    """Markdown for tasks/README.md, generated from the candidates and the pilot."""
    counts: dict[tuple[str, str], list[int]] = {}
    for t in candidates:
        c = counts.setdefault((t.series_id, _template_key(t)), [0, 0])
        c[0] += 1
        c[1] += t.flips
    tpl = {f"{s.lower()}-{tp.key}": tp for s, tps in TEMPLATES.items() for tp in tps}
    n_covid = sum(not t.flips and covid_window_overlap(t) for t in candidates)
    trivial = Counter(_template_key(t) for t in candidates if trivial_control(t))
    n_flips = sum(t.flips for t in pilot)
    n_unrate = sum(t.series_id == CONTROL_SERIES for t in pilot)
    lines = [
        "# VintageBench tasks",
        "",
        "Generated by `python -m vintagebench.tasks` from data/vintages/; do not edit by",
        "hand. Gold answers are computed programmatically from two vintages (SPEC §3).",
        "",
        "## Pilot",
        "",
        f"`tasks/pilot.jsonl`: {len(pilot)} tasks selected with `select_pilot(n={len(pilot)}, "
        f"seed={seed})`: {n_flips} flips, {len(pilot) - n_flips} controls "
        f"({n_unrate} {CONTROL_SERIES}).",
        "",
        "## Date rule",
        "",
        "- as_of_date: the first vintage containing the target observation (its first",
        "  release). Targets are observations dated 2016-01 to 2025-12; targets whose",
        "  first vintage is the pre-2016 baseline are skipped.",
        "- revision_date: the first vintage at least one year after as_of_date, else the",
        "  latest vintage after it.",
        "- flips: gold_as_of != gold_revised. Each answer uses one vintage only; levels",
        "  are never compared across vintages (base-year rebasings do not matter).",
        "",
        "## COVID exclusion (controls only)",
        "",
        "No control is selected if any observation its answer reads falls in the COVID",
        "collapse: a month from 2020-03 to 2020-06 (monthly series); for GDPC1, any",
        "quarter containing such a month (2020 Q1, Q2) plus the rebound quarter 2020 Q3",
        "(so 2020 Q4, which compares with Q3, is excluded too). The window is the",
        "target plus the template's lookback (1 month for month-over-month questions,",
        "1 quarter for GDP, 3 months for the payroll 3-month average, 12 months for",
        "weakest-of-12 and PCE YoY). Such controls are trivially decided by the",
        "collapse. Flips in these windows stay eligible.",
        f"Candidate controls excluded by this rule: {n_covid}.",
        "",
        "## Non-trivial controls",
        "",
        "Each candidate's notes record its distance from the threshold in units of the",
        "template's materiality margin, in both vintages. A non-UNRATE control is not",
        "selected if that distance exceeds the template's cap (column below) in BOTH",
        "vintages: it is obvious from the era alone. UNRATE controls (the low-revision",
        "series) and flips are exempt. Caps: 10 margins for INDPRO (0.5% MoM), PCEPI",
        "(0.5pp) and GDPC1 growth (2pp annualized); 5 margins for GDPC1 shrink (0.25%",
        "QoQ, about 1pp annualized); 40 margins",
        "(40k jobs) for the PAYEMS templates.",
        f"Candidate controls excluded by this rule: {sum(trivial.values())} "
        "(some are also COVID-excluded).",
        "",
        "## Templates",
        "",
        "Comparisons are strict; exact ties count as No. Candidates with any needed",
        "observation missing in either vintage are skipped. Materiality margin: a",
        "candidate is kept only if, in BOTH vintages, the deciding quantity is clear of",
        "its threshold by at least the margin in the column below (half the 0.1",
        "publication unit, or stricter for GDPC1), so no gold answer hinges on a",
        "difference below published precision. Counts are after this filter.",
        "",
        "| template | definition | materiality margin (both vintages) | control cap "
        "(margins) | candidates | flips | trivial controls excluded |",
        "|---|---|---|---|---|---|---|",
    ]
    for (series, key), (total, flips) in sorted(counts.items()):
        tp = tpl.get(key)
        definition, margin = (_cell(tp.definition), _cell(tp.materiality)) if tp else ("", "")
        cap = "none" if tp is None or tp.control_cap is None else f"{tp.control_cap:g}"
        lines.append(
            f"| {key} ({series}) | {definition} | {margin} | {cap} | {total} | {flips} "
            f"| {trivial[key]} |"
        )
    lines += _balance_lines(pilot)
    lines += [
        "",
        "## Pilot tasks",
        "",
        "| id | question | as-of answer | revised answer | flips |",
        "|---|---|---|---|---|",
    ]
    for t in pilot:
        lines.append(
            f"| {t.id} | {_cell(t.question)} | {_yes_no(t.gold_as_of)} | "
            f"{_yes_no(t.gold_revised)} | {'yes' if t.flips else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def _cell(text: str) -> str:
    """Escape pipes (e.g. absolute-value bars) so they do not split a table cell."""
    return text.replace("|", "\\|")


def _share(k: int, n: int) -> str:
    return f"{k}/{n} ({100 * k / n:.0f}%)" if n else "0/0"


def _balance_lines(pilot: list[Task]) -> list[str]:
    n = len(pilot)
    yes_as_of = sum(bool(t.gold_as_of) for t in pilot)
    yes_rev = sum(bool(t.gold_revised) for t in pilot)

    def cell(flips: bool, yes: bool) -> int:
        return sum(t.flips == flips and bool(t.gold_as_of) == yes for t in pilot)

    return [
        "",
        "## Answer balance (pilot)",
        "",
        "| | as-of Yes | as-of No |",
        "|---|---|---|",
        f"| flips | {cell(True, True)} | {cell(True, False)} |",
        f"| controls | {cell(False, True)} | {cell(False, False)} |",
        "",
        f"- Share of Yes: as-of {_share(yes_as_of, n)}; revised {_share(yes_rev, n)}.",
        f"- Majority-class baseline (always answer the more common gold): as-of "
        f"{_share(max(yes_as_of, n - yes_as_of), n)}, revised "
        f"{_share(max(yes_rev, n - yes_rev), n)}.",
    ]


def main(root: Path = data.DATA_DIR, out_dir: Path = TASKS_DIR, seed: int = PILOT_SEED) -> None:
    """Regenerate tasks/pilot.jsonl and tasks/README.md from the vintage data."""
    candidates = build_candidates(SERIES, root)
    pilot = select_pilot(candidates, n=PILOT_N, seed=seed)
    save_tasks(out_dir / "pilot.jsonl", pilot)
    (out_dir / "README.md").write_text(render_readme(candidates, pilot, seed))
    print(f"{len(candidates)} candidates; wrote {len(pilot)} tasks to {out_dir}")


if __name__ == "__main__":
    main()
