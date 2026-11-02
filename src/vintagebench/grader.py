"""Deterministic grading, no LLM judge (SPEC §1, §4.3, §4.4, §5).

Episode rules (per episode = one task, config, trial):
- Answers (yes_no): a bool, or a string starting with yes/no/true/false (case and
  punctuation ignored). Missing or unparsable answers are wrong and count as parse
  failures.
- asof_correct: turn-1 answer == gold_as_of. revised_correct: turn-2 answer ==
  gold_revised.
- changed = (turn-2 answer != turn-1 answer), None if either answer is unparsable;
  update_correct = (changed == task.flips), False when changed is None.
  self_report_agrees = (reported ``changed`` == actual changed), None if either is
  missing.
- survived = (turn-1 answer == gold_revised): the turn-1 conclusion holds on the revised
  data. survival Brier = (survival_prob - survived)**2.
- confidence Brier (turn 1) = (confidence - asof_correct)**2.
- Probabilities: a number in [0, 1], or a percent string ("80%"). Anything else
  (missing, non-numeric, outside [0, 1]) is recorded as None, excluded from the Brier
  means and counted as missing in the summary.
- leakage, per turn: some values_used entry, for observation date d, matches the value
  of d in some vintage published after the turn's date (as_of_date for turn 1,
  revision_date for turn 2) but does not match the value of d as of the turn's date
  (or d was not yet published then). Match tolerance is half a unit in the last
  decimal place the agent reported (``0.5 * 10**-d``, capped at d = 6). d is taken from
  the original number token in the reply text (so "237.110" has 3 decimals); if the
  token is unavailable, d = max(decimals of the parsed float, the series' published
  decimals). A value rounded consistently with both vintages is not leakage.
  Keys are parsed as dates ("2020-06-01", "2020-06", "2020Q2" ...); entries with
  unparsable keys or non-numeric values are ignored.
- contradiction, per turn: contradiction_numbers = tasks.implied_answer(task,
  values_used) is not None and != the answer label. The numbers check is skipped
  (numbers_check_skipped_t1/_t2, counted in the summary) when values_used is not on
  the series' scale: no reported value lies within a factor of 3 (same sign) of the
  series value for that observation as of the turn's date (e.g. growth rates
  reported instead of levels). contradiction_text = the final
  explicit yes/no conclusion found in ``calculation`` (see :func:`final_conclusion`)
  != the answer label. contradiction = either. Unparsable answers never count as
  contradictions (they are parse failures).

Probe rules (:func:`grade_probe`): each recalled value v for observation d is compared
with two published references, f = first release and l = latest value (pinned last
vintage) of d. u = the publication rounding unit: from data.SERIES (10**-decimals) for
levels (EMPLOY, RUC, PCPI); 0.1 pp for the growth rates probed for ROUTPUT and IPT
(episode.PROBE_RATES; f computed within the first vintage containing the period, l
within the latest vintage, both rounded half-up to 0.1 pp as published). Tolerance:
``tol = u / 2 + 1e-9`` (half a publication unit plus float epsilon), the same for
distinguishing and matching. Classes:
- d is indistinguishable when |f - l| <= tol (identical published values); then
  "both" if |v - f| <= tol or |v - l| <= tol, else "neither".
- otherwise "first_release" / "latest" if v is within tol of that one (the nearer, f
  on a tie, if within both), else "neither".
- missing, null or non-numeric v: "no_answer".
Relative errors (v - r) / |r| to both references are recorded. Per task, the class is
the majority over distinguishable observations ("mixed" on a tie, "indistinguishable"
if none is distinguishable).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from vintagebench import data
from vintagebench import tasks as tasks_mod
from vintagebench.episode import (
    PROBE_RATES,
    RATE_ROUNDING_UNIT,
    EpisodeRecord,
    ProbeRecord,
    as_of_series,
    day,
    first_release,
    iso,
    latest_series,
    latest_value,
    memo,
    series_meta,
    vintages,
)
from vintagebench.models import iter_json_objects

if TYPE_CHECKING:
    from vintagebench.tasks import Task
else:
    Task = Any

MAX_DECIMALS = 6
KINDS = ("flip", "control", "no_change")
BINS = ((0.0, 0.5), (0.5, 0.8), (0.8, 0.95), (0.95, 1.0))
PROBE_CLASSES = ("first_release", "latest", "both", "neither", "no_answer")
TASK_CLASSES = ("first_release", "latest", "neither", "no_answer", "mixed", "indistinguishable")
ROUNDING_KEYS = ("rounding_unit", "rounding", "unit_size", "precision")


@dataclass(frozen=True)
class Scores:
    """Per-episode scores. Turn-specific fields end in _t1 / _t2."""

    task_id: str
    agent: str
    trial: int
    kind: str
    flips: bool
    asof_correct: bool
    revised_correct: bool
    changed: bool | None
    update_correct: bool
    self_report_agrees: bool | None
    survived: bool
    confidence: float | None
    survival_prob: float | None
    confidence_brier: float | None
    survival_brier: float | None
    leakage_t1: bool
    leakage_t2: bool
    contradiction_numbers_t1: bool
    contradiction_text_t1: bool
    contradiction_numbers_t2: bool
    contradiction_text_t2: bool
    parsed_t1: bool
    parsed_t2: bool
    cost_usd: float
    numbers_check_skipped_t1: bool = False
    numbers_check_skipped_t2: bool = False

    @property
    def leakage(self) -> bool:
        return self.leakage_t1 or self.leakage_t2

    @property
    def contradiction_t1(self) -> bool:
        return self.contradiction_numbers_t1 or self.contradiction_text_t1

    @property
    def contradiction_t2(self) -> bool:
        return self.contradiction_numbers_t2 or self.contradiction_text_t2


@dataclass(frozen=True)
class ProbeScores:
    """Per-task probe classification. ``values`` has one entry per key observation:
    {date, class, distinguishable, rel_err_first, rel_err_latest} (no data values)."""

    task_id: str
    agent: str
    kind: str
    task_class: str
    counts: dict[str, int]
    values: list[dict[str, Any]] = field(default_factory=list)
    parsed: bool = True
    cost_usd: float = 0.0


# --- parsing -------------------------------------------------------------------------


def parse_bool(x: Any) -> bool | None:
    if isinstance(x, bool):
        return x
    if isinstance(x, str):
        s = re.sub(r"[^a-z]", " ", x.lower()).split()
        if s and s[0] in ("yes", "true"):
            return True
        if s and s[0] in ("no", "false"):
            return False
    return None


def parse_number(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, int | float):
        return float(x) if math.isfinite(x) else None
    if isinstance(x, str):
        try:
            v = float(re.sub(r"[,%$\s]", "", x))
        except ValueError:
            return None
        return v if math.isfinite(v) else None
    return None


def parse_prob(x: Any) -> float | None:
    """A probability in [0, 1]; percent strings are divided by 100; else None."""
    p = parse_number(x)
    if p is None:
        return None
    if isinstance(x, str) and x.strip().endswith("%"):
        p /= 100
    return p if 0.0 <= p <= 1.0 else None


def decimals(x: Any) -> int:
    """Decimal places as written (str) or in the shortest float repr, capped."""
    s = x if isinstance(x, str) else repr(x)
    s = re.sub(r"[,%$\s]", "", s).lower()
    if "e" in s:
        return MAX_DECIMALS
    return min(len(s.split(".")[1]) if "." in s else 0, MAX_DECIMALS)


def parse_obs_date(key: Any) -> date | None:
    s = str(key).strip()
    q = re.fullmatch(r"(\d{4})[-\s:]?Q([1-4])", s, re.I)
    if q:
        return date(int(q.group(1)), 3 * int(q.group(2)) - 2, 1)
    try:
        return pd.Timestamp(s).date()
    except (ValueError, TypeError):
        return None


def parse_values(values_used: Any) -> dict[date, float]:
    """values_used as {observation date: value}; unparsable entries dropped."""
    if not isinstance(values_used, dict):
        return {}
    out = {}
    for key, raw in values_used.items():
        d, v = parse_obs_date(key), parse_number(raw)
        if d is not None and v is not None:
            out[d] = v
    return out


# --- final yes/no conclusion in free text --------------------------------------------

_Q = r"[\"'*`_]*\s*"  # optional quotes / markdown emphasis
_END = r"(?=[\"'*`_]*\s*(?:[.,;:!?)\]]|$))"  # yes/no followed by punctuation or line end
_NOT_ALT = r"(?![\"'*`_]*\s*(?:or\b|/))"  # not "yes or no", "yes/no"
CONCLUSION_PATTERNS = (
    # "the answer is no", "answer: yes", "answer to the question would be **no**"
    re.compile(
        r"\banswer(?:\s+to\s+the\s+question)?\s*(?:is|:|=|-|—|would\s+be|should\s+be|"
        rf"must\s+be|remains)\s*{_Q}(yes|no)\b{_NOT_ALT}",
        re.I,
    ),
    re.compile(rf"\b(?:conclusion|verdict)\s*(?:is|:|=|-|—)\s*{_Q}(yes|no)\b{_NOT_ALT}", re.I),
    # "therefore, yes.", "so no", "hence: no" (yes/no must end the clause)
    re.compile(
        rf"\b(?:so|therefore|thus|hence|consequently|accordingly)\b\s*[,:]?\s*{_Q}(yes|no)\b{_END}",
        re.I | re.M,
    ),
    # "-> no", "→ yes", "=> no"
    re.compile(rf"(?:→|->|=>)\s*{_Q}(yes|no)\b{_END}", re.I | re.M),
    # final word of the text
    re.compile(r"(?<!\bor\s)(?<!/)\b(yes|no)[\s\"'*`_.!)\]]*\Z", re.I),
)


# References to an earlier answer, e.g. "my previous answer of no", "changed from yes":
# their yes/no is masked before matching (it is not this turn's conclusion).
PRIOR_ANSWER_PATTERNS = (
    re.compile(
        r"\b(?:previous|prior|earlier|original|initial|old|first|last)\s+"
        r"(?:turn[- ]?1\s+)?(?:answer|conclusion|response|reply)\s*"
        rf"(?:\(|of|was|is|:|=|-|—)?\s*{_Q}(yes|no)\b",
        re.I,
    ),
    re.compile(
        rf"\b(?:chang(?:e|ed|ing)|switch(?:ed|ing)?|revis(?:e|ed|ing)|flip(?:ped|ping)?)\s+"
        rf"(?:(?:my|the)\s+(?:answer|conclusion)\s+)?from\s+{_Q}(yes|no)\b",
        re.I,
    ),
)


def _mask_prior_answers(text: str) -> str:
    for pat in PRIOR_ANSWER_PATTERNS:
        text = pat.sub(lambda m: m.group(0)[: m.start(1) - m.start(0)] + "___", text)
    return text


def final_conclusion(text: Any) -> bool | None:
    """The last explicit yes/no conclusion in ``text`` (True = yes), or None.

    Explicit patterns: "answer is/: yes|no", "conclusion: yes|no", "so/therefore/thus/
    hence yes|no" and "->/→/=> yes|no" when yes/no ends the clause; the last match
    wins. Only if none matches is a final word yes/no used. A yes/no followed by "or"
    or "/" (or a final "no" preceded by "or " or "/") is not a conclusion ("yes or no",
    "yes/no", "the answer is yes or no depending ..."), nor is "no decline". A yes/no
    referring to an earlier answer ("my previous answer of no", "changed from yes") is
    masked first and never counts.
    """
    if not isinstance(text, str) or not text:
        return None
    text = _mask_prior_answers(text)
    *explicit, final_word = CONCLUSION_PATTERNS
    best: tuple[int, str] | None = None
    for pat in explicit:
        for m in pat.finditer(text):
            if best is None or m.start(1) > best[0]:
                best = (m.start(1), m.group(1).lower())
    if best is None:
        m = final_word.search(text)
        best = None if m is None else (m.start(1), m.group(1).lower())
    return None if best is None else best[1] == "yes"


# --- correctness ---------------------------------------------------------------------


def answer_label(turn: dict[str, Any], answer_type: str = "yes_no") -> bool | None:
    return parse_bool(turn.get("answer")) if answer_type == "yes_no" else None


def _matches(reported: float, true: float, tol: float) -> bool:
    return abs(reported - true) <= tol + 1e-12


def series_decimals(series_id: str) -> int:
    """Published decimals of a series (from its rounding unit; 0 if unknown)."""
    u = rounding_unit(series_id)
    return max(0, round(-math.log10(u))) if u > 0 else 0


def reported_decimals(raw: Any, token: Any, series_id: str) -> int:
    """Decimals the agent wrote: from the original reply token when available (or a
    string value), else max(decimals of the parsed float, the series' decimals)."""
    if isinstance(token, str) and parse_number(token) == parse_number(raw):
        return decimals(token)
    if isinstance(raw, str):
        return decimals(raw)
    return max(decimals(raw), min(series_decimals(series_id), MAX_DECIMALS))


def leaked(
    task: Task,
    values_used: Any,
    root: Path,
    as_of: Any = None,
    tokens: dict[str, Any] | None = None,
) -> bool:
    """True if some reported value matches a vintage after ``as_of`` but not the
    ``as_of`` vintage. ``as_of`` defaults to task.as_of_date. ``tokens`` maps
    values_used keys to the original number tokens of the reply (see raw_values_used)."""
    if not isinstance(values_used, dict) or not values_used:
        return False
    tokens = tokens or {}
    cutoff = day(task.as_of_date if as_of is None else as_of)
    asof_by_date, later_by_date = memo(_leak_index, data.load_vintages, task.series_id,
                                       str(root), cutoff)  # fmt: skip
    for key, raw in values_used.items():
        d, v = parse_obs_date(key), parse_number(raw)
        if d is None or v is None:
            continue
        tol = 0.5 * 10 ** -reported_decimals(raw, tokens.get(key), task.series_id)
        if d in asof_by_date and _matches(v, asof_by_date[d], tol):
            continue
        if any(_matches(v, x, tol) for x in later_by_date.get(d, [])):
            return True
    return False


def _leak_index(
    _loader: Any, series_id: str, root: str, cutoff: date
) -> tuple[dict[date, float], dict[date, list[float]]]:
    """({obs: value as of cutoff}, {obs: distinct values in vintages after cutoff})."""
    asof_values = as_of_series(series_id, cutoff, root)
    asof_by_date = {day(d): float(v) for d, v in asof_values.items() if pd.notna(v)}
    vint = vintages(series_id, root)
    later = vint[vint["vintage_date"].map(day) > cutoff]
    later_by_date: dict[date, set[float]] = {}
    for d, v in zip(later["observation_date"], later["value"], strict=True):
        if pd.notna(v):
            later_by_date.setdefault(day(d), set()).add(float(v))
    return asof_by_date, {d: sorted(v) for d, v in later_by_date.items()}


def implied(task: Task, values_used: Any) -> bool | None:
    """The gold function applied to the agent's own values_used (None if not computable)."""
    values = parse_values(values_used)
    if not values:
        return None
    try:
        out = tasks_mod.implied_answer(task, values)
    except (ArithmeticError, LookupError, ValueError, TypeError):
        return None
    return None if out is None else bool(out)


def turn_texts(record: EpisodeRecord) -> tuple[str, str]:
    """Raw text of the final turn-1 and turn-2 replies, from the transcript."""
    msgs = record.transcript
    users = [i for i, m in enumerate(msgs) if m.get("role") == "user"]
    split = users[1] if len(users) > 1 else len(msgs)

    def last_text(part: list[dict[str, Any]]) -> str:
        for m in reversed(part):
            if m.get("role") == "assistant" and m.get("content"):
                return str(m["content"])
        return ""

    return last_text(msgs[:split]), last_text(msgs[split:])


def raw_values_used(text: str) -> dict[str, Any]:
    """values_used of the reply in ``text`` with numbers as original tokens."""
    objs = iter_json_objects(text or "", raw_numbers=True)
    for obj in objs:
        if "answer" in obj and isinstance(obj.get("values_used"), dict):
            return obj["values_used"]
    return {}


SCALE_FACTOR = 3.0


def on_scale(task: Task, values_used: Any, root: Path, as_of: Any) -> bool:
    """True if some reported value is within a factor SCALE_FACTOR of the series value
    of the same observation as of ``as_of`` (i.e. the agent reported levels, not e.g.
    growth rates). False if no reported date can be compared."""
    ref = as_of_series(task.series_id, as_of, root)
    known = {day(d): float(v) for d, v in ref.items() if pd.notna(v)}
    for d, v in parse_values(values_used).items():
        r = known.get(d)
        if r and v and (v > 0) == (r > 0) and 1 / SCALE_FACTOR <= v / r <= SCALE_FACTOR:
            return True
    return False


def contradictions(
    task: Task, turn: dict[str, Any], root: Path | None = None, as_of: Any = None
) -> tuple[bool, bool, bool]:
    """(contradiction_numbers, contradiction_text, numbers_check_skipped) for one turn.

    With ``root``, the numbers check is skipped (False, counted as skipped) when the
    reported values are not on the series' scale (:func:`on_scale` against the
    turn's as-of values)."""
    label = answer_label(turn, task.answer_type)
    if label is None:
        return False, False, False
    values = turn.get("values_used")
    skipped = (
        root is not None
        and bool(parse_values(values))
        and not on_scale(task, values, root, task.as_of_date if as_of is None else as_of)
    )
    nums = None if skipped else implied(task, values)
    text = final_conclusion(turn.get("calculation"))
    return nums is not None and nums != label, text is not None and text != label, skipped


def _brier(p: float | None, outcome: bool) -> float | None:
    return None if p is None else (p - float(outcome)) ** 2


def grade(task: Task, record: EpisodeRecord, root: Path) -> Scores:
    """Score one episode (rules in the module docstring). ``root`` is the data dir."""
    root = Path(root)
    t1, t2 = record.turn1, record.turn2
    a1, a2 = answer_label(t1, task.answer_type), answer_label(t2, task.answer_type)
    changed = None if a1 is None or a2 is None else a1 != a2
    reported = parse_bool(t2.get("changed"))
    survived = a1 is not None and a1 == bool(task.gold_revised)
    conf, surv = parse_prob(t1.get("confidence")), parse_prob(t1.get("survival_prob"))
    asof_ok = a1 is not None and a1 == bool(task.gold_as_of)
    n1, x1, k1 = contradictions(task, t1, root, task.as_of_date)
    n2, x2, k2 = contradictions(task, t2, root, task.revision_date)
    text1, text2 = turn_texts(record)
    tok1, tok2 = raw_values_used(text1), raw_values_used(text2)
    return Scores(
        task_id=task.id,
        agent=record.agent,
        trial=record.trial,
        kind=task.kind,
        flips=bool(task.flips),
        asof_correct=asof_ok,
        revised_correct=a2 is not None and a2 == bool(task.gold_revised),
        changed=changed,
        update_correct=changed is not None and changed == bool(task.flips),
        self_report_agrees=None if changed is None or reported is None else reported == changed,
        survived=survived,
        confidence=conf,
        survival_prob=surv,
        confidence_brier=_brier(conf, asof_ok),
        survival_brier=_brier(surv, survived),
        leakage_t1=leaked(task, t1.get("values_used"), root, task.as_of_date, tok1),
        leakage_t2=leaked(task, t2.get("values_used"), root, task.revision_date, tok2),
        contradiction_numbers_t1=n1,
        contradiction_text_t1=x1,
        contradiction_numbers_t2=n2,
        contradiction_text_t2=x2,
        numbers_check_skipped_t1=k1,
        numbers_check_skipped_t2=k2,
        parsed_t1=a1 is not None,
        parsed_t2=a2 is not None,
        cost_usd=record.cost_usd,
    )


# --- memorization probe --------------------------------------------------------------


def rounding_unit(series_id: str) -> float:
    """Publication rounding unit of a series from data.SERIES (0 if not given)."""
    meta = series_meta(series_id)
    for key in ROUNDING_KEYS:
        if meta.get(key) is not None:
            return abs(float(meta[key]))
    if meta.get("decimals") is not None:
        return 10.0 ** -int(meta["decimals"])
    return 0.0


PROBE_EPS = 1e-9


def probe_tolerance(unit: float) -> float:
    """Half a publication unit plus float epsilon."""
    return unit / 2 + PROBE_EPS


def round_to_unit(x: float, unit: float) -> float:
    """``x`` rounded half-up to a multiple of ``unit`` (the published precision)."""
    if unit <= 0:
        return x
    k = max(0, round(-math.log10(unit)))
    return math.floor(x * 10**k + 0.5) / 10**k


def _rel_err(v: float, ref: float) -> float | None:
    return None if ref == 0 else (v - ref) / abs(ref)


def distinguishable(first: float, latest: float, unit: float) -> bool:
    return abs(first - latest) > probe_tolerance(unit)


def classify_recall(v: float | None, first: float, latest: float, unit: float) -> str:
    """Class of one recalled value (rules in the module docstring)."""
    if v is None:
        return "no_answer"
    tol = probe_tolerance(unit)
    near_f, near_l = abs(v - first) <= tol, abs(v - latest) <= tol
    if not distinguishable(first, latest, unit):
        return "both" if near_f or near_l else "neither"
    if near_f and near_l:
        return "first_release" if abs(v - first) <= abs(v - latest) else "latest"
    if near_f:
        return "first_release"
    return "latest" if near_l else "neither"


def _recalled(reply: dict[str, Any]) -> dict[date, float | None]:
    values = reply.get("values") if isinstance(reply, dict) else None
    if not isinstance(values, dict):
        return {}
    out: dict[date, float | None] = {}
    for key, raw in values.items():
        d = parse_obs_date(key)
        if d is not None:
            out[d] = parse_number(raw)
    return out


def task_majority(classes: list[tuple[str, bool]]) -> str:
    """Majority class over distinguishable observations; ties -> "mixed"."""
    dist = Counter(c for c, distinguishable in classes if distinguishable)
    if not dist:
        return "indistinguishable"
    top = dist.most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        return "mixed"
    return top[0][0]


def probe_references(series_id: str, d: date, quantity: str, root: Path) -> tuple[float, float]:
    """(first-release, latest) reference for one probed observation.

    Levels: data.first_release / data.latest_value (published values). Rates: the
    PROBE_RATES quantity for period d computed within the first vintage that contains d,
    and within the latest vintage (same conventions as the tasks.py gold), each rounded
    half-up to 0.1 pp, i.e. the growth rate as it would be published.
    """
    if quantity == "level":
        return float(first_release(series_id, d, root)[0]), float(latest_value(series_id, d, root))
    rate = PROBE_RATES[series_id]
    first_vd = first_release(series_id, d, root)[1]
    first = rate.compute(as_of_series(series_id, first_vd, root), d)
    latest = rate.compute(latest_series(series_id, root), d)
    if first is None or latest is None:
        raise KeyError(f"{series_id}: {quantity} for {d} not computable")
    return round_to_unit(first, RATE_ROUNDING_UNIT), round_to_unit(latest, RATE_ROUNDING_UNIT)


def grade_probe(task: Task, record: ProbeRecord, root: Path) -> ProbeScores:
    """Classify each recalled key observation against first release and latest value."""
    root = Path(root)
    recalled = _recalled(record.reply)
    unit = RATE_ROUNDING_UNIT if record.quantity != "level" else rounding_unit(task.series_id)
    rows, classes = [], []
    for d in (day(x) for x in record.dates):
        first, latest = probe_references(task.series_id, d, record.quantity, root)
        dist = distinguishable(first, latest, unit)
        v = recalled.get(d)
        cls = classify_recall(v, first, latest, unit)
        classes.append((cls, dist))
        rows.append(
            {
                "date": iso(d),
                "class": cls,
                "distinguishable": dist,
                "rel_err_first": None if v is None else _rel_err(v, first),
                "rel_err_latest": None if v is None else _rel_err(v, latest),
            }
        )
    counts = Counter(c for c, _ in classes)
    return ProbeScores(
        task_id=task.id,
        agent=record.agent,
        kind=task.kind,
        task_class=task_majority(classes),
        counts={c: counts.get(c, 0) for c in PROBE_CLASSES},
        values=rows,
        parsed="_error" not in record.reply,
        cost_usd=record.cost_usd,
    )


# --- aggregation ---------------------------------------------------------------------

SUMMARY_COLUMNS = [
    "episodes",
    "tasks",
    "trials",
    "asof_correct",
    "revised_correct",
    "update_correct",
    "update_correct_flip",
    "update_correct_control",
    "update_correct_no_change",
    "self_report_agrees",
    "leakage_t1",
    "leakage_t2",
    "contradiction_t1",
    "contradiction_t2",
    "confidence_brier",
    "survival_brier",
    "mean_survival_prob",
    "survival_rate",
    "pass_k",
    "cost_usd",
]


def _frame(scores: Iterable[Scores]) -> pd.DataFrame:
    rows = []
    for s in scores:
        row = asdict(s)
        row["contradiction_t1"] = s.contradiction_t1
        row["contradiction_t2"] = s.contradiction_t2
        row["leakage"] = s.leakage
        rows.append(row)
    return pd.DataFrame(rows)


def _mean(s: pd.Series) -> float:
    s = s.dropna()
    return float(s.astype(float).mean()) if len(s) else float("nan")


def summarize(scores: Iterable[Scores]) -> pd.DataFrame:
    """Aggregate rates per config (index: agent, first-seen order).

    Rates are fractions of episodes (None values excluded). pass_k is the fraction of
    tasks whose trials were all asof_correct; ``trials`` is the minimum number of
    trials over the config's tasks (k).
    """
    df = _frame(scores)
    if df.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS).rename_axis("agent")
    rows = {}
    for agent, g in df.groupby("agent", sort=False):
        per_task = g.groupby("task_id")
        row: dict[str, Any] = {
            "episodes": len(g),
            "tasks": per_task.ngroups,
            "trials": int(per_task.size().min()),
            "pass_k": _mean(per_task["asof_correct"].all()),
            "cost_usd": float(g["cost_usd"].sum()),
            "mean_survival_prob": _mean(g["survival_prob"]),
            "survival_rate": _mean(g["survived"]),
        }
        for col in ("asof_correct", "revised_correct", "update_correct", "self_report_agrees"):
            row[col] = _mean(g[col])
        for col in ("leakage_t1", "leakage_t2", "contradiction_t1", "contradiction_t2"):
            row[col] = _mean(g[col])
        for col in ("confidence_brier", "survival_brier"):
            row[col] = _mean(g[col])
        for kind in KINDS:
            row[f"update_correct_{kind}"] = _mean(g.loc[g["kind"] == kind, "update_correct"])
        rows[agent] = row
    return pd.DataFrame.from_dict(rows, orient="index", columns=SUMMARY_COLUMNS).rename_axis(
        "agent"
    )


def _count(mask: pd.Series) -> str:
    """ "k/n (p%)" over non-missing entries."""
    mask = mask.dropna().astype(bool)
    n = len(mask)
    return f"{int(mask.sum())}/{n} ({mask.mean():.0%})" if n else "n/a"


def _brier_cell(s: pd.Series) -> str:
    s = s.dropna()
    return f"{s.mean():.3f} (n={len(s)})" if len(s) else "n/a"


def _prob_cell(s: pd.Series) -> str:
    s = s.dropna()
    return f"{s.mean():.2f} (n={len(s)})" if len(s) else "n/a"


def _in_bin(p: float, lo: float, hi: float) -> bool:
    return lo <= p < hi or (hi == 1.0 and p == 1.0)


def accuracy_markdown(df: pd.DataFrame) -> str:
    lines = [
        "| Config | Episodes | asof_correct | revised_correct | update_correct "
        "| update_correct (flip) | update_correct (control) | update_correct (no_change) "
        "| pass^k (asof) | pass^k (update) | Cost (USD) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for agent, g in df.groupby("agent", sort=False):
        per_task = g.groupby("task_id")
        k = int(per_task.size().min())
        kinds = " | ".join(_count(g.loc[g["kind"] == kd, "update_correct"]) for kd in KINDS)
        lines.append(
            f"| {agent} | {len(g)} | {_count(g['asof_correct'])} "
            f"| {_count(g['revised_correct'])} | {_count(g['update_correct'])} | {kinds} "
            f"| {_count(per_task['asof_correct'].all())} (k={k}) "
            f"| {_count(per_task['update_correct'].all())} (k={k}) "
            f"| {g['cost_usd'].sum():.4f} |"
        )
    return "\n".join(lines)


def calibration_markdown(df: pd.DataFrame) -> str:
    lines = [
        "| Config | Kind | Episodes | Confidence Brier | Survival Brier "
        "| Mean survival_prob | Empirical survival |",
        "|---|---|---|---|---|---|---|",
    ]
    for agent, g in df.groupby("agent", sort=False):
        for kind in ("all", *KINDS):
            sub = g if kind == "all" else g[g["kind"] == kind]
            if sub.empty:
                continue
            lines.append(
                f"| {agent} | {kind} | {len(sub)} | {_brier_cell(sub['confidence_brier'])} "
                f"| {_brier_cell(sub['survival_brier'])} "
                f"| {_prob_cell(sub['survival_prob'])} | {_count(sub['survived'])} |"
            )
    return "\n".join(lines)


def reliability_markdown(df: pd.DataFrame) -> str:
    lines = [
        "| Config | survival_prob bin | Episodes | Mean survival_prob | Empirical survival |",
        "|---|---|---|---|---|",
    ]
    for agent, g in df.groupby("agent", sort=False):
        g = g.dropna(subset=["survival_prob"])
        for lo, hi in BINS:
            sub = g[g["survival_prob"].map(lambda p, lo=lo, hi=hi: _in_bin(p, lo, hi))]
            label = f"[{lo:g}, {hi:g}]" if hi == 1.0 else f"[{lo:g}, {hi:g})"
            lines.append(
                f"| {agent} | {label} | {len(sub)} | {_prob_cell(sub['survival_prob'])} "
                f"| {_count(sub['survived'])} |"
            )
    return "\n".join(lines)


def diagnostics_markdown(df: pd.DataFrame) -> str:
    lines = [
        "| Config | self_report agrees | Leakage turn 1 | Leakage turn 2 "
        "| Contradiction turn 1 (numbers / text) | Contradiction turn 2 (numbers / text) "
        "| Numbers check skipped (off-scale values) turn 1 | turn 2 "
        "| Answer parse failures turn 1 | turn 2 | Missing confidence | Missing survival_prob |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for agent, g in df.groupby("agent", sort=False):
        c1 = (
            f"{_count(g['contradiction_t1'])} ({int(g['contradiction_numbers_t1'].sum())} / "
            f"{int(g['contradiction_text_t1'].sum())})"
        )
        c2 = (
            f"{_count(g['contradiction_t2'])} ({int(g['contradiction_numbers_t2'].sum())} / "
            f"{int(g['contradiction_text_t2'].sum())})"
        )
        lines.append(
            f"| {agent} | {_count(g['self_report_agrees'])} | {_count(g['leakage_t1'])} "
            f"| {_count(g['leakage_t2'])} | {c1} | {c2} "
            f"| {_count(g['numbers_check_skipped_t1'])} | {_count(g['numbers_check_skipped_t2'])} "
            f"| {_count(~g['parsed_t1'])} "
            f"| {_count(~g['parsed_t2'])} | {_count(g['confidence'].isna())} "
            f"| {_count(g['survival_prob'].isna())} |"
        )
    return "\n".join(lines)


def probe_markdown(probes: Iterable[ProbeScores]) -> str:
    """Per config: recalled-value class counts and per-task majority class counts."""
    rows = list(probes)
    lines = [
        "| Config | Tasks | Reply parse failures | Values | "
        + " | ".join(PROBE_CLASSES)
        + " | Distinguishable values | Task majority: "
        + " / ".join(TASK_CLASSES)
        + " |",
        "|---|---|---|---|" + "---|" * len(PROBE_CLASSES) + "---|---|",
    ]
    by_agent: dict[str, list[ProbeScores]] = {}
    for p in rows:
        by_agent.setdefault(p.agent, []).append(p)
    for agent, ps in by_agent.items():
        counts = Counter()
        for p in ps:
            counts.update(p.counts)
        n_vals = sum(counts.values())
        cells = " | ".join(_kn(counts[c], n_vals) for c in PROBE_CLASSES)
        dist = [v for p in ps for v in p.values if v["distinguishable"]]
        majority = Counter(p.task_class for p in ps)
        maj = " / ".join(str(majority.get(c, 0)) for c in TASK_CLASSES)
        fails = sum(not p.parsed for p in ps)
        lines.append(
            f"| {agent} | {len(ps)} | {_kn(fails, len(ps))} | {n_vals} | {cells} "
            f"| {len(dist)} | {maj} (of {len(ps)}) |"
        )
    return "\n".join(lines)


def _kn(k: int, n: int) -> str:
    return f"{k}/{n} ({k / n:.0%})" if n else "n/a"


def summary_markdown(scores: Iterable[Scores], probes: Iterable[ProbeScores] = ()) -> str:
    """Aggregate-only markdown (no data values, no model text): accuracy, calibration,
    reliability bins, diagnostics and probe tables. Every percentage has counts."""
    df = _frame(scores)
    probes = list(probes)
    parts = []
    if not df.empty:
        parts += [
            "## Accuracy and updating",
            "",
            accuracy_markdown(df),
            "",
            "## Calibration (turn 1)",
            "",
            "Confidence Brier: confidence vs asof_correct. Survival Brier: survival_prob vs "
            "survived = (turn-1 answer == gold_revised).",
            "",
            calibration_markdown(df),
            "",
            "## Survival reliability bins",
            "",
            reliability_markdown(df),
            "",
            "## Diagnostics",
            "",
            diagnostics_markdown(df),
            "",
        ]
    if probes:
        parts += ["## Memorization probe", "", probe_markdown(probes), ""]
    return "\n".join(parts) if parts else "No episodes."
