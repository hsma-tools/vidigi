"""Numbers in, DataFrames out.

Companion module to `vidigi.plots`: every chart in `plots.py` is a thin wrapper
around a function defined here, so each plot has a public "give me the numbers"
twin for tables and reports. Nothing in this module imports plotly or
`vidigi.logging` - every function here takes DataFrames, never an `EventLogger`
or `TrialLogger`.
"""

import difflib
import inspect
import warnings
from collections import namedtuple
from typing import Literal, Optional, Sequence, TypeAlias, Union

import numpy as np
import pandas as pd

from vidigi.prep import reshape_for_animations
from vidigi.utils import _resolve_run_column, _resource_map_from_event_position_df

MatchMode: TypeAlias = Literal["first", "last", "occurrence"]

# Statistics that can be computed over the durations between a pair of events.
# The first group are pandas Series methods applied to the durations; the second are
# computed by vidigi, and count entities rather than summarise times. Editors offer
# these as completions, but the value is still validated at runtime, since
# annotations are not enforced.
DurationStat: TypeAlias = Literal[
    "mean",
    "median",
    "max",
    "min",
    "quantile",
    "std",
    "var",
    "sum",
    "count",
    "unserved_count",
    "served_count",
    "unserved_rate",
    "served_rate",
    "summary",
]

# The subset of `DurationStat` that is a genuine per-replication statistic - a
# pandas Series method callable directly on one run's durations. The remainder
# (`"count"`, `"unserved_rate"`, `"summary"`, ...) count *entities*, not
# durations, and are not meaningful re-averaged across runs - see
# `replication_means`.
_REPLICATION_STATS = ("mean", "median", "max", "min", "quantile", "std", "var", "sum")
_SPECIAL_DURATION_AGGS = (
    "count",
    "unserved_count",
    "served_count",
    "unserved_rate",
    "served_rate",
    "summary",
)

# How an entity still holding a resource at the end of the analysis window is
# handled by `resource_use_intervals`/`resource_utilisation`.
UnclosedResourceUse: TypeAlias = Literal["censor", "drop"]

# What each row of `resource_utilisation`'s output summarises.
ResourceUtilisationBy: TypeAlias = Literal["step", "resource", "run"]


def _nearest_match_hint(name, candidates, n: int = 3) -> str:
    suggestions = difflib.get_close_matches(
        str(name), [str(c) for c in candidates], n=n
    )
    if not suggestions:
        return ""
    return f" (did you mean {', '.join(repr(s) for s in suggestions)}?)"


def _check_events_present(
    event_log: pd.DataFrame, event_col_name: str, *events: str
) -> None:
    """Raise a legible error naming any of `events` absent from `event_col_name`.

    Left unchecked, a typo'd event name does not raise at all - filtering on a name
    that matches nothing just returns no rows, and after an outer merge the result is
    a confusing all-`NaN` duration column with no indication the name was wrong.
    """
    present = set(event_log[event_col_name].dropna().unique())
    missing = [e for e in events if e not in present]
    if not missing:
        return
    parts = [f"'{e}'{_nearest_match_hint(e, present)}" for e in missing]
    raise ValueError(
        f"Event(s) not found in the '{event_col_name}' column of `event_log`: "
        f"{', '.join(parts)}. Available events: {sorted(str(e) for e in present)}."
    )


def _resolve_pathway_column(
    df: pd.DataFrame, pathway_col_name: Optional[str]
) -> Optional[str]:
    """Resolve the optional pathway column, tolerating its absence at the default name.

    `EventLogger.to_dataframe()` drops all-null columns, so a log built without a
    `pathway` on any event has no `pathway` column at all - that must not raise at the
    default. An explicit, non-default name that is missing is still an error, since
    the caller pointed at something specific.
    """
    if pathway_col_name is None:
        return None
    if pathway_col_name in df.columns:
        return pathway_col_name
    if pathway_col_name == "pathway":
        return None
    raise ValueError(
        f"`pathway_col_name` was given as '{pathway_col_name}', but that column is "
        f"not present. Available columns: {sorted(str(c) for c in df.columns)}."
    )


def _resolve_window(
    event_log: pd.DataFrame,
    limit_duration: Optional[float],
    warm_up: float,
    time_col_name: str = "time",
) -> tuple:
    """Resolve the `(window_start, window_end)` bounds shared by warm-up-aware analyses.

    `window_end` is the explicit `limit_duration` if given, else the latest time seen
    **anywhere in the trial**, not per run - a per-run maximum would give each run a
    different denominator, making cross-run quantities such as utilisation
    incomparable and any confidence interval computed over them meaningless.
    `window_start` is `warm_up`.
    """
    if warm_up < 0:
        raise ValueError(f"`warm_up` must not be negative, but {warm_up} was passed.")

    window_end = (
        event_log[time_col_name].max() if limit_duration is None else limit_duration
    )

    if warm_up > window_end:
        raise ValueError(
            f"`warm_up` ({warm_up}) is after the end of the analysis window "
            f"({window_end}), so the window is empty. `warm_up` and `limit_duration` "
            f"bound the window between them."
        )

    return warm_up, window_end


def event_durations(
    event_log: pd.DataFrame,
    first_event: str,
    second_event: str,
    *,
    match: MatchMode = "first",
    warm_up: float = 0,
    entity_col_name: str = "entity_id",
    event_col_name: str = "event",
    time_col_name: str = "time",
    run_col_name: Optional[str] = "auto",
    pathway_col_name: Optional[str] = "pathway",
    keep_incomplete: bool = True,
) -> pd.DataFrame:
    """
    Pair occurrences of two events per entity and compute the duration between them.

    Replaces a `pivot` on `event_col_name`, which raises on any log where an entity
    revisits a step - a rework loop produces duplicate `(entity_id, event)` pairs,
    which `pivot` cannot place in a single cell - and silently drops `pathway`.

    Parameters
    ----------
    event_log : pandas.DataFrame
        Long-format event log, e.g. the output of `EventLogger.to_dataframe()` or
        `TrialLogger.to_dataframe()`.
    first_event, second_event : str
        The two event names to pair, matched against `event_col_name`. Must be
        different.
    match : {"first", "last", "occurrence"}, default="first"
        How repeated occurrences of the two events for the same entity are paired:

        - ``"first"``: the entity's earliest `first_event` with its earliest
          `second_event`, regardless of how many times either occurs.
        - ``"last"``: the entity's latest of each, symmetrically.
        - ``"occurrence"``: the *n*-th `first_event` with the *n*-th `second_event`,
          in time order. An entity with an unequal number of the two events has its
          excess occurrences paired with nothing (`NaN` on the missing side), and a
          warning names how many entities are affected.
    warm_up : float, default=0
        Pairings whose `first_time` is before `warm_up` are excluded - the
        standard truncation rule for duration data (Law & Kelton): a pairing
        is discarded by when it *started*, not by whether it later straddles
        the cutoff. Unlike `resource_use_intervals`/`resource_occupancy_over_time`'s
        `warm_up`, nothing is censored or clipped mid-interval - a duration is
        one atomic observation, not a bout that can be partially inside the
        window. A pairing with no `first_time` at all (a `second_event` with
        no matching `first_event`) is never excluded by this, since there is
        no time to compare against `warm_up`. The default of `0` is a
        verified no-op.
    entity_col_name : str, default="entity_id"
        Column identifying the entity.
    event_col_name : str, default="event"
        Column holding the event name.
    time_col_name : str, default="time"
        Column holding the event time.
    run_col_name : str or None, default="auto"
        Column identifying which simulation run each row belongs to; pairing is done
        within each run rather than across the whole log. `"auto"` looks for a column
        named (case-insensitively) one of `run`, `run_number`, `replication`, `rep` or
        `run_id`. Pass an explicit column name to override, or `None` to disable and
        pair across the whole frame. If no run column is found, the output
        `run_number` column is filled with `NA`.
    pathway_col_name : str or None, default="pathway"
        Column holding the entity's pathway, carried through to the output. Its
        absence at the default name is tolerated (the output `pathway` column is then
        all `NA`); an explicit name that is missing raises.
    keep_incomplete : bool, default=True
        If True (default), rows where either the first or second event is missing for
        a pairing are kept, with `NaN` in the missing side's time and in `duration`.
        If False, they are dropped.

    Returns
    -------
    pandas.DataFrame
        One row per matched pair, with columns ``entity_id``, ``run_number``,
        ``pathway``, ``occurrence``, ``first_time``, ``second_time``, ``duration``.

    Raises
    ------
    ValueError
        If `first_event` equals `second_event`; if either is not present in
        `event_col_name`; if `pathway_col_name` names a column that does not
        exist; or if `warm_up` is negative.

    Notes
    -----
    The pairing is an **outer** join on entity (and run, and occurrence for
    `match="occurrence"`), not a left join on `first_event`. This is what preserves
    both directions of incompleteness: an entity that reached `first_event` but never
    `second_event` (the familiar "unserved" case), and - equally real, but invisible
    under a left join - one with a `second_event` that has no matching `first_event`.

    Where every entity visits each event at most once per run, `match="first"`
    reproduces exactly what the old `pivot`-based calculation produced. Where an
    entity revisits, the old calculation raised, so there is no prior behaviour to
    match.

    Examples
    --------
    >>> event_durations(event_log, "treatment_begins", "treatment_ends")
    """
    if first_event == second_event:
        raise ValueError(
            f"`first_event` and `second_event` are both '{first_event}'. "
            f"`event_durations` measures the time between two *different* events - "
            f"pass distinct event names."
        )

    if warm_up < 0:
        raise ValueError(f"`warm_up` must not be negative, but {warm_up} was passed.")

    if match not in ("first", "last", "occurrence"):
        raise ValueError(
            f"`match` must be one of 'first', 'last', 'occurrence'; got {match!r}."
        )

    _check_events_present(event_log, event_col_name, first_event, second_event)

    run_col = _resolve_run_column(event_log, run_col_name)
    pathway_col = _resolve_pathway_column(event_log, pathway_col_name)

    group_keys = ([run_col] if run_col else []) + [entity_col_name]

    def _prepare(event_name):
        subset = (
            event_log[event_log[event_col_name] == event_name]
            .sort_values(group_keys + [time_col_name])
            .copy()
        )
        subset["occurrence"] = subset.groupby(group_keys, dropna=False).cumcount()
        if match == "first":
            subset = subset.groupby(group_keys, dropna=False).head(1).copy()
            subset["occurrence"] = 0
        elif match == "last":
            subset = subset.groupby(group_keys, dropna=False).tail(1).copy()
            subset["occurrence"] = 0
        return subset

    firsts = _prepare(first_event)
    seconds = _prepare(second_event)

    if match == "occurrence":
        first_counts = firsts.groupby(group_keys, dropna=False).size()
        second_counts = seconds.groupby(group_keys, dropna=False).size()
        counts = pd.concat(
            [first_counts.rename("n_first"), second_counts.rename("n_second")],
            axis=1,
        ).fillna(0)
        mismatched = counts[counts["n_first"] != counts["n_second"]]
        if not mismatched.empty:
            example_key = mismatched.index[0]
            example = mismatched.iloc[0]
            warnings.warn(
                f"match='occurrence' pairs '{first_event}' and '{second_event}' in "
                f"order of occurrence, but {len(mismatched)} of {len(counts)} "
                f"entities have unequal counts of the two events (e.g. "
                f"{example_key!r}: {int(example['n_first'])} vs "
                f"{int(example['n_second'])}). Excess occurrences are paired with "
                f"nothing and appear with a NaN on the missing side.",
                UserWarning,
                stacklevel=2,
            )

    rename_map = {entity_col_name: "entity_id"}
    if run_col:
        rename_map[run_col] = "run_number"

    keep_cols = (["run_number"] if run_col else []) + ["entity_id", "occurrence"]

    firsts = firsts.rename(columns={**rename_map, time_col_name: "first_time"})
    seconds = seconds.rename(columns={**rename_map, time_col_name: "second_time"})

    firsts_cols = keep_cols + ["first_time"]
    seconds_cols = keep_cols + ["second_time"]
    if pathway_col:
        firsts = firsts.rename(columns={pathway_col: "pathway_first"})
        seconds = seconds.rename(columns={pathway_col: "pathway_second"})
        firsts_cols = firsts_cols + ["pathway_first"]
        seconds_cols = seconds_cols + ["pathway_second"]

    merged = firsts[firsts_cols].merge(
        seconds[seconds_cols], on=keep_cols, how="outer"
    )

    if pathway_col:
        merged["pathway"] = merged["pathway_first"].combine_first(
            merged["pathway_second"]
        )
        merged = merged.drop(columns=["pathway_first", "pathway_second"])
    else:
        merged["pathway"] = pd.NA

    if "run_number" not in merged.columns:
        merged["run_number"] = pd.NA

    merged["duration"] = merged["second_time"] - merged["first_time"]

    merged = merged[merged["first_time"].isna() | (merged["first_time"] >= warm_up)]

    if not keep_incomplete:
        merged = merged[merged["duration"].notna()]

    return merged[
        [
            "entity_id",
            "run_number",
            "pathway",
            "occurrence",
            "first_time",
            "second_time",
            "duration",
        ]
    ].reset_index(drop=True)


def _summarise_durations(
    series: pd.Series,
    what: str,
    exclude_incomplete: bool,
    n_runs: int,
    dp: Optional[int] = None,
    **kwargs,
) -> Union[float, dict]:
    """Reduce a series of durations to a single statistic (or, for `"summary"`, several).

    Shared by `TrialLogger.get_event_duration_stat` and `vidigi.plots.plot_metric_bar`'s
    `across="entities"` path, so the two cannot drift.
    """
    allowed = _REPLICATION_STATS + _SPECIAL_DURATION_AGGS

    if what not in allowed:
        sigs = []
        for name in sorted(allowed):
            try:
                func = getattr(series, name)
                sig = str(inspect.signature(func))
            except Exception:
                sig = "()"
            sigs.append(f"  - {name}{sig}")
        raise ValueError(
            f"Unsupported aggregation: {what}.\n"
            f"Allowed aggregations:\n" + "\n".join(sigs)
        )

    if what == "count":
        result = series.count() if exclude_incomplete else series.size
    elif what == "unserved_count":
        result = series.size - series.count()
    elif what == "served_count":
        result = series.count()
    elif what == "unserved_rate":
        result = (series.size - series.count()) / series.size
    elif what == "served_rate":
        result = series.count() / series.size
    elif what == "summary":
        result = {
            "mean (of complete)": series.mean(skipna=True),
            "median (of complete)": series.median(skipna=True),
            "min": series.min(),
            "max": series.max(),
            "unserved_count": series.size - series.count(),
            "served_count": series.count(),
            "unserved_rate": (series.size - series.count()) / series.size,
            "served_rate": series.count() / series.size,
            "unserved_count_mean_per_run": (series.size - series.count()) / n_runs,
            "served_count_mean_per_run": series.count() / n_runs,
        }
    else:
        method = getattr(series, what)
        try:
            result = method(skipna=exclude_incomplete, **kwargs)
        except TypeError:
            result = method(**kwargs)

    if dp is None:
        return result
    if what == "summary":
        return {k: round(v, dp) for k, v in result.items()}
    return round(result, dp)


def replication_means(
    durations: pd.DataFrame,
    *,
    value_col: str = "duration",
    run_col: str = "run_number",
    what: DurationStat = "mean",
    **kwargs,
) -> pd.DataFrame:
    """
    Reduce a per-entity durations frame to one value per replication.

    The independent unit for any confidence interval is the replication, not the
    entity - entities within a run are strongly serially correlated, so this is the
    function that produces the values `mean_confidence_interval` must be called on.
    See the *Notes* there for why.

    Parameters
    ----------
    durations : pandas.DataFrame
        Per-entity durations, e.g. the output of `event_durations`.
    value_col : str, default="duration"
        Column to aggregate within each run.
    run_col : str, default="run_number"
        Column identifying which run each row belongs to.
    what : str, default="mean"
        The per-replication statistic to compute: one of `"mean"`, `"median"`,
        `"max"`, `"min"`, `"quantile"`, `"std"`, `"var"`, `"sum"` - a genuine
        pandas Series method, callable on a single run's values. Entity-counting
        aggregations such as `"count"` or `"unserved_rate"` answer a different
        question (how many entities, not what value) and are not meaningful
        re-averaged across runs; use `TrialLogger.get_event_duration_stat` or
        `vidigi.plots.plot_metric_bar(across="entities")` for those instead.
    **kwargs : dict
        Additional keyword arguments passed to the chosen statistic, e.g.
        `q=0.9` for `what="quantile"`.

    Returns
    -------
    pandas.DataFrame
        Columns `run_col` and `"value"`, one row per run that has at least one
        non-missing `value_col`. Rows with a missing (`NaN`) `value_col` - an
        incomplete pairing - are dropped before aggregating, since a missing
        duration cannot contribute to a run's statistic.

    Raises
    ------
    ValueError
        If `what` is not one of the supported per-replication statistics.

    See Also
    --------
    mean_confidence_interval : Compute a confidence interval over this function's output.
    event_durations : The underlying per-entity durations.
    """
    if what not in _REPLICATION_STATS:
        raise ValueError(
            f"`what` must be one of {_REPLICATION_STATS} - a genuine per-replication "
            f"statistic - not {what!r}. Aggregations like 'count' or 'summary' count "
            f"entities rather than summarise a value, and are not meaningful "
            f"re-averaged across runs; use `TrialLogger.get_event_duration_stat` or "
            f"`vidigi.plots.plot_metric_bar(across='entities')` for those."
        )

    clean = durations.dropna(subset=[value_col])
    result = (
        clean.groupby(run_col, dropna=True)[value_col]
        .agg(what, **kwargs)
        .rename("value")
        .reset_index()
    )
    return result[[run_col, "value"]]


def _require_scipy():
    """Import and return `scipy.stats`, raising a legible error if unavailable.

    scipy ships as the optional `[stats]` extra rather than a hard dependency,
    since it is only needed for `error_bars="ci"` - `"sd"`, `"se"`, `"range"` and
    `"iqr"` all work with numpy/pandas alone.
    """
    try:
        from scipy import stats
    except ImportError:
        raise ImportError(
            "Computing a confidence interval requires the optional dependency "
            "'scipy', which is not installed with vidigi by default. Install it "
            "with: pip install vidigi[stats]"
        )
    return stats


ConfidenceInterval = namedtuple(
    "ConfidenceInterval", ["mean", "half_width", "lower", "upper", "n", "method"]
)


def mean_confidence_interval(
    values, *, ci_level: float = 0.95, method: Literal["t"] = "t"
) -> ConfidenceInterval:
    """
    Confidence interval for a mean, computed over independent replicate values.

    Parameters
    ----------
    values : array-like
        The replicate-level values to summarise - typically the `"value"` column
        of `replication_means`'s output. **Must be one value per replication, never
        one value per entity** - see *Notes*.
    ci_level : float, default=0.95
        Confidence level, e.g. `0.95` for a 95% interval.
    method : {"t"}, default="t"
        How the interval is computed. Only Student's t is supported: with
        `n` typically in the 5-30 range for a replicated simulation study, a
        normal approximation is systematically too narrow (at `n=5`,
        `t=2.776` vs `z=1.96` - 29% too narrow), so `t` with `n - 1` degrees of
        freedom is used unconditionally, never `z`.

    Returns
    -------
    ConfidenceInterval
        Named tuple of `(mean, half_width, lower, upper, n, method)`. If fewer
        than 2 non-missing values are given, `half_width`, `lower` and `upper`
        are `NaN` and a warning is raised - an interval needs at least 2 points
        to estimate a spread from.

    Raises
    ------
    ImportError
        If `scipy` is not installed. Install it with `pip install vidigi[stats]`.
    ValueError
        If `method` is not `"t"`.

    See Also
    --------
    replication_means : Produces the per-replication values this function summarises.

    Notes
    -----
    This must be computed over **replication means, never pooled per-entity
    observations**. Entities within a single run are strongly serially
    correlated - one bad morning makes fifty consecutive waits long together -
    so pooling treats correlated observations as independent, shrinking the
    standard error by roughly the square root of the number of entities per run
    and producing an interval that can be an order of magnitude too narrow.
    Replications are the independent unit; entities are not.

    At `n=2`, `t` gives a large interval (`t=12.71` at the 95% level) - this is
    correct and informative given only two replications, not a bug to special-case.
    """
    if method != "t":
        raise ValueError(f"`method` must be 't'; got {method!r}.")

    series = pd.Series(values).dropna()
    n = len(series)
    mean = series.mean()

    if n < 2:
        warnings.warn(
            f"Cannot compute a confidence interval from {n} replication(s) - at "
            f"least 2 are required to estimate a spread. Returning a NaN "
            f"half-width.",
            UserWarning,
            stacklevel=2,
        )
        return ConfidenceInterval(
            mean=mean,
            half_width=float("nan"),
            lower=float("nan"),
            upper=float("nan"),
            n=n,
            method=method,
        )

    stats = _require_scipy()
    std = series.std(ddof=1)
    se = std / (n**0.5)
    half_width = stats.t.ppf(1 - (1 - ci_level) / 2, df=n - 1) * se

    return ConfidenceInterval(
        mean=mean,
        half_width=half_width,
        lower=mean - half_width,
        upper=mean + half_width,
        n=n,
        method=method,
    )


def replication_precision(
    values,
    *,
    ci_level: float = 0.95,
    deviation_threshold: float = 0.05,
) -> pd.DataFrame:
    """
    Running confidence-interval precision as replications accumulate.

    For k = 1..n, in the order `values` is given, computes the confidence
    interval using only the first k replications, plus its *relative*
    half-width (`deviation`) - the standard diagnostic (Hoad, Robinson &
    Davies, 2010) for deciding how many replications a study needs: run more
    until the interval is tight enough relative to the mean, not just "run
    some fixed number and hope."

    Parameters
    ----------
    values : array-like
        Per-replication values, **already in run order** - typically
        `replication_means(...)["value"]`. This function does not sort them;
        a cumulative diagnostic is only meaningful walked through in the
        order replications were actually generated.
    ci_level : float, default=0.95
        Confidence level for each cumulative interval - see
        `mean_confidence_interval`.
    deviation_threshold : float, default=0.05
        Relative half-width threshold used for `stays_below_threshold` (see
        *Returns*). `0.05` means the CI half-width must be within 5% of the
        cumulative mean.

    Returns
    -------
    pandas.DataFrame
        One row per k = 1..n, columns:

        - ``n_replications`` : int - k.
        - ``cumulative_mean`` : float - mean of `values[:k]`.
        - ``half_width``, ``lower``, ``upper`` : float - the confidence
          interval from the first k values. `NaN` at k=1 - a spread needs at
          least 2 points, matching `mean_confidence_interval`.
        - ``deviation`` : float - `half_width / abs(cumulative_mean)`, the
          relative precision. Always non-negative, so a metric with a
          negative mean (e.g. a before/after difference) is not read as
          trivially "precise" by a negative ratio. `NaN` wherever
          `half_width` is `NaN`, or if `cumulative_mean` is `0`.
        - ``stays_below_threshold`` : bool - True at row k if `deviation` is
          defined and no greater than `deviation_threshold` at k *and every
          later row, up to n*. Deliberately "stays below", not "first drops
          below": a noisy early curve can dip under the threshold once by
          chance and rise again, which would be a spurious recommendation.
          The smallest `n_replications` with `stays_below_threshold=True` is
          the recommended minimum replication count; always `False` at k=1.
          This is a property of the batch of `n` replications actually
          supplied, not a guarantee that deviation stays low forever - a run
          flagged `True` from a 20-replication batch could fail to qualify
          once replications 21+ are added and re-checked.

    Raises
    ------
    ValueError
        If `values` is empty.
    ImportError
        If `scipy` is not installed and `n >= 2` - see
        `mean_confidence_interval`.

    See Also
    --------
    mean_confidence_interval : The single-k confidence interval this is built from.
    replication_means : Produces the per-replication values this function consumes.
    vidigi.plots.plot_replication_analysis : Plots this table.

    Notes
    -----
    Recomputing a confidence interval at every k and reading off a
    threshold-crossing point is a "look-elsewhere"-style repeated test, not a
    single test at a chosen n - this function makes no correction for that,
    and neither does Hoad, Robinson & Davies (2010), the method it follows.
    Treat the reported `stays_below_threshold`/recommended count as a
    starting point for judgement, not a statistically-corrected stopping
    rule - matching this package's deliberate choice not to fully automate
    `welch_moving_average`'s warm-up selection either.
    """
    series = pd.Series(values).reset_index(drop=True)
    n = len(series)
    if n == 0:
        raise ValueError("`values` must contain at least one replication.")

    rows = []
    for k in range(1, n + 1):
        window = series.iloc[:k]
        mean = window.mean()
        if k < 2:
            half_width = lower = upper = float("nan")
        else:
            ci = mean_confidence_interval(window, ci_level=ci_level)
            half_width, lower, upper = ci.half_width, ci.lower, ci.upper
        deviation = half_width / abs(mean) if mean != 0 else float("nan")
        rows.append(
            {
                "n_replications": k,
                "cumulative_mean": mean,
                "half_width": half_width,
                "lower": lower,
                "upper": upper,
                "deviation": deviation,
            }
        )

    result = pd.DataFrame(rows)
    suffix_max = result["deviation"][::-1].cummax()[::-1]
    result["stays_below_threshold"] = (
        result["deviation"].notna() & (suffix_max <= deviation_threshold)
    )
    return result


def queue_size_over_time(
    event_log: pd.DataFrame,
    event_list: list,
    limit_duration,
    *,
    every_x_time_units: int = 1,
    warm_up: int = 0,
    run_col_name: Optional[str] = "auto",
    entity_col_name: str = "entity_id",
    time_col_name: str = "time",
    event_type_col_name: str = "event_type",
    event_col_name: str = "event",
    pathway_col_name: Optional[str] = None,
) -> pd.DataFrame:
    """
    Compute the size of one or more queues at regular snapshots, across every run.

    Extracted from `TrialLogger.plot_queue_size`, which is now a thin wrapper over
    `vidigi.plots.plot_queue_size`, itself a thin wrapper over this function.

    Parameters
    ----------
    event_log : pandas.DataFrame
        Long-format event log spanning one or more runs, e.g. the output of
        `TrialLogger.to_dataframe()`.
    event_list : list of str
        Event names (matched against `event_col_name`) to report a queue size for.
    limit_duration : int or float
        Maximum time to include, in the same units as `time_col_name`.
    every_x_time_units : int, default=1
        Time granularity for snapshots.
    warm_up : int, default=0
        Time at which the reported window begins. Snapshots run from `warm_up` to
        `limit_duration`. Passed straight through to `reshape_for_animations`; see
        that function's docstring for why this - and not filtering the log by time
        - is the correct way to discard a warm-up period.
    run_col_name : str or None, default="auto"
        Column identifying which run each row belongs to. `"auto"` looks for a
        column named (case-insensitively) one of `run`, `run_number`,
        `replication`, `rep` or `run_id`. Pass an explicit column name to
        override, or `None` if the log holds a single run.
    entity_col_name, time_col_name, event_type_col_name, event_col_name,
    pathway_col_name : str or None
        Column names forwarded to `reshape_for_animations`. See that function's
        docstring for their meaning.

    Returns
    -------
    pandas.DataFrame
        Columns ``run_number``, ``event``, ``snapshot_time``, ``count``. One row
        per event in `event_list` per snapshot per run, including snapshots where
        the queue was empty - a queue with nobody in it is a real zero, not a
        missing row.

    Notes
    -----
    - Queue lengths are **not** capped at the `step_snapshot_max` used internally
      by `reshape_for_animations` for keeping an animation drawable; a queue is
      reported at its true length, however long it got.
    - An event in `event_list` that occurs in no run at all is reported as zero
      throughout, with a warning - otherwise a misspelt event name is
      indistinguishable from a queue that genuinely never formed.
    """
    run_col = _resolve_run_column(event_log, run_col_name)
    run_groups = (
        list(event_log.groupby(run_col, sort=False))
        if run_col
        else [(pd.NA, event_log)]
    )

    results = []
    snapshot_times = set()
    observed_events = set()

    for run_id, run_df in run_groups:
        # `step_snapshot_max` caps how many entities `reshape_for_animations` keeps
        # per event per snapshot, so an animation stays drawable. Left at its
        # default here it would saturate the *count* at `step_snapshot_max + 1`
        # rather than reporting how long the queue actually got, so it is lifted
        # above anything the log can hold.
        reshaped = reshape_for_animations(
            run_df,
            every_x_time_units=every_x_time_units,
            limit_duration=limit_duration,
            step_snapshot_max=max(len(run_df), 1),
            warm_up=warm_up,
            time_col_name=time_col_name,
            entity_col_name=entity_col_name,
            event_type_col_name=event_type_col_name,
            event_col_name=event_col_name,
            pathway_col_name=pathway_col_name,
            run_col_name=None,
        )

        # Snapshots where nobody was in the model are still represented in the
        # reshaped frame, so this collects the full time grid - including the
        # intervals whose count is zero and which would otherwise go missing.
        snapshot_times.update(reshaped["snapshot_time"].unique().tolist())
        observed_events.update(reshaped[event_col_name].dropna().unique().tolist())

        results.append(
            (
                run_id,
                reshaped[reshaped[event_col_name].isin(event_list)]
                .groupby([event_col_name, "snapshot_time"])
                .size(),
            )
        )

    unseen_events = [event for event in event_list if event not in observed_events]
    if unseen_events:
        warnings.warn(
            f"{unseen_events} did not occur in any run, so will be reported as a "
            f"queue of zero throughout. Check these against the values in your "
            f"event log's '{event_col_name}' column.",
            UserWarning,
            stacklevel=2,
        )

    # An event with nobody queuing produces no rows to count, so counting alone
    # leaves gaps - biasing any mean upwards by averaging only over the runs that
    # had somebody waiting. Filling the grid makes those genuine zeros explicit.
    full_index = pd.MultiIndex.from_product(
        [event_list, sorted(snapshot_times)], names=[event_col_name, "snapshot_time"]
    )

    event_counts = pd.concat(
        [
            counts.reindex(full_index, fill_value=0)
            .reset_index(name="count")
            .assign(run_number=run_id)
            for run_id, counts in results
        ],
        ignore_index=True,
    )

    return event_counts.rename(columns={event_col_name: "event"})[
        ["run_number", "event", "snapshot_time", "count"]
    ]


def resource_use_intervals(
    event_log: pd.DataFrame,
    *,
    unclosed: UnclosedResourceUse = "censor",
    warm_up: float = 0,
    limit_duration: Optional[float] = None,
    entity_col_name: str = "entity_id",
    time_col_name: str = "time",
    event_type_col_name: str = "event_type",
    event_col_name: str = "event",
    resource_col_name: str = "resource_id",
    run_col_name: Optional[str] = "auto",
) -> pd.DataFrame:
    """
    Pair `resource_use`/`resource_use_end` rows into one interval per bout of use.

    Parameters
    ----------
    event_log : pandas.DataFrame
        Long-format event log, e.g. the output of `TrialLogger.to_dataframe()`.
    unclosed : {"censor", "drop"}, default="censor"
        How to handle a `resource_use` row with no matching `resource_use_end` -
        an entity still holding the resource when the window ends.

        - ``"censor"`` (default): the interval's `end` is set to the window end
          and `censored` is `True`. Dropping these understates utilisation
          exactly when it matters most - entities still holding a resource at
          the end of a run are disproportionately those in a congested system.
        - ``"drop"``: the interval is excluded entirely.
    warm_up : float, default=0
        Start of the analysis window. See *Notes*.
    limit_duration : float, optional
        End of the analysis window. `None` (default) uses the latest time seen
        anywhere in the trial - not per run, so every run shares the same
        denominator. See *Notes*.
    entity_col_name, time_col_name, event_type_col_name, event_col_name,
    resource_col_name : str
        Column names in `event_log`.
    run_col_name : str or None, default="auto"
        Column identifying which run each row belongs to. See
        `event_durations`.

    Returns
    -------
    pandas.DataFrame
        Columns ``run_number``, ``entity_id``, ``event`` (the *start* row's
        event name - the end row's name is a label, not a key), ``resource_id``,
        ``start``, ``end``, ``censored``, ``busy_time``.

    Raises
    ------
    ValueError
        If `unclosed` is not `"censor"` or `"drop"`; or if `resource_col_name`
        is present for some `resource_use`/`resource_use_end` rows but not
        others.

    Notes
    -----
    Pairing is within `(run, entity, resource_id)`, matched in time order (the
    *n*-th start of that combination with its *n*-th end) - mirroring
    `event_durations`, but with no `match` argument, since a resource bout has
    no ambiguity to choose between.

    An end row with no matching start (a logging defect, not something to
    compute from) is always dropped, with a warning.

    If `resource_col_name` is missing from every row (dropped by
    `to_dataframe()`'s `dropna(axis=1, how="all")`, or present but entirely
    null), pairing falls back to `(run, entity)` only, with a warning: `busy_time`,
    `mean_in_use` and `utilisation` stay exact, only the per-unit breakdown is
    lost.

    `busy_time` is clipped to the analysis window *last*, after pairing:
    ``max(0, min(end, window_end) - max(start, warm_up))``. `window_end` is
    `limit_duration` if given, else the latest time seen anywhere in the trial -
    a per-run maximum would give each run a different denominator, making
    utilisation incomparable across runs and any confidence interval computed
    over them meaningless.

    For a censored row (`censored=True`), `end` is the window boundary, not a
    real completion time - safe for `busy_time` (an interval genuinely was
    occupied up to that point), but **not** for a service-time-type analysis.
    A naive `end - start` on a censored row understates nothing since it's
    right-truncated - filter `censored` rows out first, or pass
    `unclosed="drop"`, before treating `start`/`end` as observed bout
    durations.

    This assumes each step's capacity is constant across the whole analysis
    window. A resource whose capacity varies within the window (e.g.
    shift-based staffing) will not be represented correctly by a single
    capacity value - `resource_utilisation`'s `mean_in_use` is still a valid
    time-average, but `utilisation` (which divides by one static number) is
    not.

    See Also
    --------
    resource_utilisation : Aggregates this function's output into one row per run per group.
    """
    if unclosed not in ("censor", "drop"):
        raise ValueError(f"`unclosed` must be 'censor' or 'drop'; got {unclosed!r}.")

    if event_type_col_name not in event_log.columns:
        raise ValueError(
            f"`event_type_col_name` was given as '{event_type_col_name}', but "
            f"that column is not present. Available columns: "
            f"{sorted(str(c) for c in event_log.columns)}."
        )

    run_col = _resolve_run_column(event_log, run_col_name)
    window_start, window_end = _resolve_window(
        event_log, limit_duration, warm_up, time_col_name
    )

    starts = event_log[event_log[event_type_col_name] == "resource_use"].copy()
    ends = event_log[event_log[event_type_col_name] == "resource_use_end"].copy()

    has_resource_col = resource_col_name in event_log.columns
    if has_resource_col:
        combined = pd.concat([starts[resource_col_name], ends[resource_col_name]])
        all_null = combined.isna().all()
        any_null = combined.isna().any()
    else:
        all_null = True
        any_null = False

    if has_resource_col and any_null and not all_null:
        raise ValueError(
            f"'{resource_col_name}' is present for some resource_use/"
            f"resource_use_end rows but not others - pairing would silently "
            f"cross entities using different physical units. Every resource_use "
            f"row needs a resource_id, or none of them do."
        )

    resource_id_missing = (not has_resource_col) or all_null
    if resource_id_missing:
        warnings.warn(
            f"'{resource_col_name}' is missing from every resource_use row, so "
            f"pairing falls back to (run, entity) only. busy_time, mean_in_use "
            f"and utilisation stay exact; only the per-unit breakdown is lost.",
            UserWarning,
            stacklevel=2,
        )
        group_keys = ([run_col] if run_col else []) + [entity_col_name]
    else:
        group_keys = ([run_col] if run_col else []) + [
            entity_col_name,
            resource_col_name,
        ]

    starts = starts.sort_values(group_keys + [time_col_name])
    starts["occurrence"] = starts.groupby(group_keys, dropna=False).cumcount()

    ends = ends.sort_values(group_keys + [time_col_name])
    ends["occurrence"] = ends.groupby(group_keys, dropna=False).cumcount()

    rename_map = {entity_col_name: "entity_id"}
    if run_col:
        rename_map[run_col] = "run_number"
    if not resource_id_missing:
        rename_map[resource_col_name] = "resource_id"

    keep_cols = (
        (["run_number"] if run_col else [])
        + ["entity_id"]
        + (["resource_id"] if not resource_id_missing else [])
        + ["occurrence"]
    )

    # `resource_col_name` (or `entity_col_name`/`run_col_name`) may point at a
    # column other than the canonical target name it's being renamed to (e.g.
    # `resource_col_name="unique_resource_id"` on a log that also carries a
    # literal "resource_id" column, logged separately for animation) - drop
    # any such pre-existing column sharing a rename target's name first, or
    # the rename below would produce two identically-named columns and every
    # later `[col]` access would raise "not unique".
    collisions = [target for target in set(rename_map.values()) if target not in rename_map]
    starts = starts.drop(columns=[c for c in collisions if c in starts.columns]).rename(
        columns={**rename_map, time_col_name: "start"}
    )
    ends = ends.drop(columns=[c for c in collisions if c in ends.columns]).rename(
        columns={**rename_map, time_col_name: "end"}
    )

    merged = starts[keep_cols + ["start", event_col_name]].merge(
        ends[keep_cols + ["end"]], on=keep_cols, how="outer", indicator=True
    )
    merged = merged.rename(columns={event_col_name: "event"})

    orphan_ends = merged["_merge"] == "right_only"
    if orphan_ends.any():
        warnings.warn(
            f"{int(orphan_ends.sum())} resource_use_end row(s) had no matching "
            f"resource_use start and were dropped - this is a logging defect, "
            f"not something to compute from.",
            UserWarning,
            stacklevel=2,
        )
    merged = merged[~orphan_ends].copy()

    unclosed_mask = merged["_merge"] == "left_only"
    if unclosed_mask.any():
        if unclosed == "drop":
            merged = merged[~unclosed_mask].copy()
            unclosed_mask = pd.Series(False, index=merged.index)
        else:
            warnings.warn(
                f"{int(unclosed_mask.sum())} resource_use row(s) were still open "
                f"at the end of the window - censored at {window_end} "
                f"(unclosed='censor', the default). Pass unclosed='drop' to "
                f"exclude them instead.",
                UserWarning,
                stacklevel=2,
            )

    merged["censored"] = unclosed_mask.astype(bool)
    merged.loc[unclosed_mask, "end"] = window_end
    merged = merged.drop(columns=["_merge"])

    if resource_id_missing:
        merged["resource_id"] = pd.NA
    if "run_number" not in merged.columns:
        merged["run_number"] = pd.NA

    merged["busy_time"] = (
        merged["end"].clip(upper=window_end) - merged["start"].clip(lower=window_start)
    ).clip(lower=0)

    return merged[
        [
            "run_number",
            "entity_id",
            "event",
            "resource_id",
            "start",
            "end",
            "censored",
            "busy_time",
        ]
    ].reset_index(drop=True)


def _check_no_overlapping_resource_bouts(
    intervals: pd.DataFrame,
    *,
    resource_col_name: str = "resource_id",
    run_col_name: str = "run_number",
) -> None:
    """Warn if any `resource_id` has two busy bouts overlapping in time within
    the same run.

    Impossible for one physical unit - only one entity can hold it at once -
    and a much sharper signal of an ID collision (two different resource pools
    numbering their units the same way, e.g. two `vidigi.resources.VidigiStore`
    instances) than `utilisation` silently exceeding 1. Half-open `[start,
    end)`: a bout starting exactly when the previous one for the same
    `resource_id` ends is a legitimate handoff, not a collision.
    """
    rows = intervals.dropna(subset=[resource_col_name]).sort_values(
        [run_col_name, resource_col_name, "start"]
    )
    group_keys = [run_col_name, resource_col_name]
    prev_end = rows.groupby(group_keys, dropna=False)["end"].shift()
    overlapping = rows[rows["start"] < prev_end]

    if overlapping.empty:
        return

    pairs = sorted(
        {(row[run_col_name], row[resource_col_name]) for _, row in overlapping.iterrows()},
        key=lambda pair: (str(pair[0]), str(pair[1])),
    )
    warnings.warn(
        f"{len(pairs)} (run, resource_id) pair(s) have overlapping busy bouts "
        f"within the same run - impossible for one physical unit: "
        f"{pairs[:5]}{'...' if len(pairs) > 5 else ''}. This usually means two "
        f"different resource pools are numbering their units the same way (e.g. "
        f"two vidigi.resources.VidigiStore instances both starting from 1), so "
        f"resource_id does not identify one physical unit as by=\"resource\" "
        f"assumes. Pass a distinct label= to each pool (see "
        f"vidigi.resources.VidigiStore) and use its unique_id_attribute instead.",
        UserWarning,
        stacklevel=2,
    )


def _resolve_resource_capacities(
    intervals: pd.DataFrame,
    *,
    scenario=None,
    resource_map: Optional[dict] = None,
    event_position_df: Optional[pd.DataFrame] = None,
    resource_capacities: Optional[dict] = None,
    capacity: Optional[Literal["infer"]] = None,
    step_col_name: str = "event",
    resource_col_name: str = "resource_id",
) -> dict:
    """
    Resolve a `{step: capacity}` mapping, from one of four routes.

    Parameters
    ----------
    intervals : pandas.DataFrame
        The output of `resource_use_intervals`. Only used for route D
        (`capacity="infer"`) and for the "unknown step"/"unused capacity"
        warnings; routes A-C need nothing from it beyond that.
    scenario : object, optional
        A scenario/parameters object exposing resource counts as attributes.
        Required by routes B and C, unused by A and D.
    resource_map : dict, optional
        **Route B.** `{step: attribute_name}` - the name of the attribute on
        `scenario` holding that step's capacity. Requires `scenario`.
    event_position_df : pandas.DataFrame, optional
        **Route C.** Reuses the `resource` column already used by the
        animation functions - see `vidigi.utils.EventPosition`. Requires
        `scenario`.
    resource_capacities : dict, optional
        **Route A**, highest precedence. `{step: capacity}` directly - no
        `scenario` needed.
    capacity : {"infer"}, optional
        **Route D**, lowest precedence. Infers each step's capacity as the
        number of distinct `resource_id` values seen for it anywhere in
        `intervals` - a **lower bound**, since a unit that was never used is
        invisible, so inferred utilisation is biased upward exactly for
        underloaded resources. Always warns.
    step_col_name, resource_col_name : str
        Column names in `intervals`.

    Returns
    -------
    dict
        `{step: capacity}`, one entry per step seen in `intervals` (`NaN` for
        a step with no resolvable capacity).

    Raises
    ------
    ValueError
        If `scenario` is given but none of `resource_map`, `event_position_df`
        or `resource_capacities` accompanies it - naming all three routes.
    AttributeError
        If `resource_map`/`event_position_df` names an attribute `scenario`
        does not have - naming the attribute, the step, and every non-private
        attribute `scenario` does have.

    Notes
    -----
    Routes are tried in precedence order A, B, C, D - the first one whose
    required arguments are present is used; the rest are ignored. Passing
    nothing at all is not an error: `resource_utilisation`'s `utilisation`
    column is simply `NaN` throughout, falling back to `mean_in_use`, which
    needs no capacity at all.
    """

    def _lookup(mapping: dict, source: str) -> dict:
        result = {}
        for step, attr in mapping.items():
            try:
                result[step] = getattr(scenario, attr)
            except AttributeError:
                available = [a for a in dir(scenario) if not a.startswith("_")]
                raise AttributeError(
                    f"{source} names '{attr}' as the capacity attribute for step "
                    f"'{step}', but `scenario` has no such attribute. Available "
                    f"attributes: {available}."
                )
        return result

    route_chosen = (
        resource_capacities is not None
        or resource_map is not None
        or event_position_df is not None
        or capacity == "infer"
    )

    if resource_capacities is not None:
        capacities = dict(resource_capacities)
    elif resource_map is not None:
        if scenario is None:
            raise ValueError(
                "`resource_map` was given without `scenario`. `resource_map` "
                "only names *which attribute* on your scenario holds each "
                "step's capacity - e.g. resource_map={'treatment_begins': "
                "'n_cubicles'} - `scenario` is the object those names are "
                "looked up on."
            )
        capacities = _lookup(resource_map, "`resource_map`")
    elif event_position_df is not None:
        if scenario is None:
            raise ValueError(
                "`event_position_df` was given without `scenario`. Its "
                "`resource` column only names *which attribute* on your "
                "scenario holds each step's capacity - `scenario` is the "
                "object those names are looked up on."
            )
        attr_map = _resource_map_from_event_position_df(
            event_position_df, event_col_name=step_col_name
        )
        capacities = _lookup(attr_map, "`event_position_df`")
    elif capacity == "infer":
        warnings.warn(
            "capacity='infer' estimates each step's capacity as the number of "
            "distinct resource_id values seen for it in the log. This is a "
            "*lower bound* even in the best case - a resource unit that was "
            "never used is invisible, so inferred utilisation is biased "
            "upward for underloaded resources. It can be far worse than a "
            "small undercount: if resource_id does not identify individual "
            "physical units (e.g. every grant of a plain simpy.Resource pool "
            "logs the same id, or none at all), this infers a capacity of 1 "
            "regardless of the real capacity, and utilisation is inflated by "
            "roughly that factor. Pass resource_capacities=, or scenario= "
            "with resource_map= or event_position_df=, for an exact answer.",
            UserWarning,
            stacklevel=2,
        )
        capacities = (
            intervals.dropna(subset=[resource_col_name])
            .groupby(step_col_name)[resource_col_name]
            .nunique()
            .to_dict()
        )
    elif scenario is not None:
        raise ValueError(
            "`scenario` was given, but none of the three ways to map it to a "
            "capacity were: `resource_map={'step': 'attribute_name'}`, "
            "`event_position_df=<df with a resource column>` (see "
            "`vidigi.utils.EventPosition`), or `resource_capacities="
            "{'step': count}` (which does not need `scenario` at all). Pass "
            "one of these."
        )
    else:
        capacities = {}

    steps_in_log = set(intervals[step_col_name].dropna().unique())
    if route_chosen:
        missing = steps_in_log - set(capacities)
        if missing:
            warnings.warn(
                f"No capacity given for step(s) {sorted(str(s) for s in missing)} "
                f"- utilisation for these will be NaN.",
                UserWarning,
                stacklevel=2,
            )
            capacities.update({step: float("nan") for step in missing})

        extra = set(capacities) - steps_in_log
        if extra:
            warnings.warn(
                f"Capacity given for step(s) {sorted(str(s) for s in extra)}, "
                f"which do not appear in the log - check for a typo.",
                UserWarning,
                stacklevel=2,
            )

    return capacities


def resource_utilisation(
    event_log: pd.DataFrame,
    *,
    by: ResourceUtilisationBy = "step",
    scenario=None,
    resource_map: Optional[dict] = None,
    event_position_df: Optional[pd.DataFrame] = None,
    resource_capacities: Optional[dict] = None,
    capacity: Optional[Literal["infer"]] = None,
    warm_up: float = 0,
    limit_duration: Optional[float] = None,
    unclosed: UnclosedResourceUse = "censor",
    entity_col_name: str = "entity_id",
    time_col_name: str = "time",
    event_type_col_name: str = "event_type",
    event_col_name: str = "event",
    resource_col_name: str = "resource_id",
    run_col_name: Optional[str] = "auto",
) -> pd.DataFrame:
    """
    Summarise resource use into busy time, mean-in-use and utilisation, per run.

    Always one row per run per group - aggregating across runs (a mean, a
    confidence interval) is the plotting layer's job, exactly as
    `replication_means`/`mean_confidence_interval` do for durations.

    Parameters
    ----------
    event_log : pandas.DataFrame
        Long-format event log, e.g. the output of `TrialLogger.to_dataframe()`.
    by : {"step", "resource", "run"}, default="step"
        What each row summarises.

        - ``"step"``: one row per `(run, step)` - `step` is the *start* event's
          name, e.g. `"treatment_begins"`. Capacity comes from whichever
          capacity route was given for that step.
        - ``"resource"``: one row per `(run, resource_id)` - one physical unit.
          Capacity is always `1` (the unit itself); no capacity route needs to
          be given at all, and none of the capacity arguments below are used.
          This assumes `resource_id` is unique across the *whole* log, not
          just within one step - if two different resource pools each number
          their own units from 1 (e.g. two independent `vidigi.resources.VidigiStore`
          instances), their busy time is silently summed as if it were one
          unit, and `utilisation` can read above `1` with no error, only the
          generic over-capacity warning below. Give each pool a distinct
          `label=` (see `vidigi.resources.VidigiStore`) and use its
          `unique_id_attribute` if you plan to use `by="resource"` - this mode
          also warns directly whenever it finds two bouts for the same
          `resource_id` genuinely overlapping in time, which is impossible for
          one physical unit and a sharper signal of this exact collision than
          the over-capacity warning alone.
        - ``"run"``: one row per run, pooling every step/unit together.
          `capacity` is the **sum** of every step's resolved capacity (`NaN`
          if any step's capacity is unresolved) - the maximum number of
          resource-things that could have been busy at once, treating every
          unit of every step as equally countable. If more than one distinct
          step is pooled, a warning is raised: this is a blended figure across
          (typically different) resource *types*, e.g. doctors and beds
          summed together, which is rarely the number a capacity-planning
          question is actually asking - prefer `by="step"` unless a single
          blended load figure is genuinely what is wanted.
    scenario, resource_map, event_position_df, resource_capacities, capacity :
        Capacity resolution - see `_resolve_resource_capacities` for the four
        routes and their precedence order. All optional; with none given,
        `utilisation` is `NaN` throughout and only `busy_time`/`mean_in_use`
        are meaningful.
    warm_up, limit_duration, unclosed, entity_col_name, time_col_name,
    event_type_col_name, event_col_name, resource_col_name, run_col_name :
        Forwarded to `resource_use_intervals` - see that function.

    Returns
    -------
    pandas.DataFrame
        Columns depend on `by` (`"event"`, `"resource_id"`, or nothing extra),
        plus ``run_number``, ``busy_time``, ``mean_in_use``, ``capacity``,
        ``utilisation``. A `(run, group)` combination that appears in some run
        but not others is filled with a genuine `busy_time` of `0`, not
        omitted - the same "real zero" convention as `queue_size_over_time`.

    See Also
    --------
    resource_use_intervals : The underlying per-bout intervals this aggregates.
    mean_confidence_interval : A confidence interval over one group's `utilisation`
        (or `mean_in_use`) column, filtered to that group, across runs - already
        one value per run, so no `replication_means` reduction step is needed
        first, unlike the `event_durations` -> `replication_means` route.
    """
    if by not in ("step", "resource", "run"):
        raise ValueError(f"`by` must be one of 'step', 'resource', 'run'; got {by!r}.")

    intervals = resource_use_intervals(
        event_log,
        unclosed=unclosed,
        warm_up=warm_up,
        limit_duration=limit_duration,
        entity_col_name=entity_col_name,
        time_col_name=time_col_name,
        event_type_col_name=event_type_col_name,
        event_col_name=event_col_name,
        resource_col_name=resource_col_name,
        run_col_name=run_col_name,
    )

    # `by="resource"`'s capacity is always 1 (a physical unit's own capacity is
    # itself), so none of the four routes are consulted - calling them anyway
    # would raise/warn about capacity information this mode has no use for.
    if by == "resource":
        capacities = {}
        _check_no_overlapping_resource_bouts(intervals)
    else:
        capacities = _resolve_resource_capacities(
            intervals,
            scenario=scenario,
            resource_map=resource_map,
            event_position_df=event_position_df,
            resource_capacities=resource_capacities,
            capacity=capacity,
            step_col_name="event",
            resource_col_name="resource_id",
        )

    window_start, window_end = _resolve_window(
        event_log, limit_duration, warm_up, time_col_name
    )
    window_length = window_end - window_start
    if window_length == 0:
        raise ValueError(
            f"`warm_up` ({warm_up}) equals the end of the analysis window "
            f"({window_end}), so it has zero length - mean_in_use would be a "
            f"division by zero. Widen the window, or lower `warm_up`."
        )

    group_col = {"step": "event", "resource": "resource_id", "run": None}[by]

    run_ids = sorted(intervals["run_number"].dropna().unique().tolist()) or [pd.NA]

    if group_col is None:
        grouped = (
            intervals.groupby("run_number", dropna=False)["busy_time"]
            .sum()
            .reindex(run_ids, fill_value=0)
            .rename_axis("run_number")
            .reset_index()
        )
    else:
        # A step's own event name is never null, but `resource_id` is entirely
        # null whenever `resource_use_intervals` fell back to (run, entity)
        # pairing - `.dropna()` would then discard the only group there is,
        # silently returning zero rows instead of one pooled row per run.
        distinct_values = intervals[group_col].unique().tolist()
        non_null_values = sorted(v for v in distinct_values if pd.notna(v))
        if group_col == "resource_id" and not non_null_values and not intervals.empty:
            warnings.warn(
                "by='resource' was requested, but no bout has a resource_id "
                "(see resource_use_intervals's warning above) - reporting one "
                "pooled row per run instead of a per-unit breakdown. Use "
                "by='step' or by='run' for a breakdown that does not depend "
                "on resource_id.",
                UserWarning,
                stacklevel=2,
            )
            group_values = [pd.NA]
        else:
            group_values = non_null_values

        full_index = pd.MultiIndex.from_product(
            [run_ids, group_values], names=["run_number", group_col]
        )
        grouped = (
            intervals.groupby(["run_number", group_col], dropna=False)["busy_time"]
            .sum()
            .reindex(full_index, fill_value=0)
            .reset_index()
        )

    grouped["mean_in_use"] = grouped["busy_time"] / window_length

    if by == "step":
        grouped["capacity"] = grouped["event"].map(capacities)
    elif by == "resource":
        grouped["capacity"] = 1.0
    else:
        distinct_steps = set(intervals["event"].dropna().unique())
        if len(distinct_steps) > 1:
            warnings.warn(
                f"by='run' is pooling {len(distinct_steps)} distinct steps "
                f"({sorted(str(s) for s in distinct_steps)}) into one blended "
                f"busy-time and utilisation figure. This treats every unit of "
                f"every step as interchangeable, which is rarely the number a "
                f"capacity-planning question is asking for a system with more "
                f"than one resource type - consider by='step' instead.",
                UserWarning,
                stacklevel=2,
            )
        # Sum, not "must all agree": the pooled busy_time already sums across
        # every step, so its denominator is the total number of resource-things
        # that could have been busy at once - NaN propagates automatically if
        # any step's own capacity is unresolved.
        total_capacity = sum(capacities.values()) if capacities else float("nan")
        grouped["capacity"] = total_capacity

    grouped["utilisation"] = grouped["mean_in_use"] / grouped["capacity"]

    # Utilisation over 1 is never a valid steady-state reading for this
    # definition (mean number busy / capacity) - it always means the capacity,
    # the intervals, or both are wrong (e.g. an under-counted capacity, or
    # overlapping resource_use bouts for one unit), so it is worth surfacing
    # here rather than only as a visual cue once the plotting layer exists.
    over_capacity = grouped["utilisation"] > 1
    if over_capacity.any():
        warnings.warn(
            f"{int(over_capacity.sum())} row(s) have utilisation over 1 (up to "
            f"{grouped['utilisation'].max():.2f}) - this is never valid for "
            f"mean-number-busy/capacity, and usually means the resolved "
            f"capacity is too low, or overlapping resource_use intervals for "
            f"the same unit.",
            UserWarning,
            stacklevel=2,
        )

    ordered_cols = ["run_number"] + ([group_col] if group_col else [])
    return grouped[ordered_cols + ["busy_time", "mean_in_use", "capacity", "utilisation"]]


def resource_occupancy_over_time(
    event_log: pd.DataFrame,
    *,
    every_x_time_units: float = 1,
    warm_up: float = 0,
    limit_duration: Optional[float] = None,
    entity_col_name: str = "entity_id",
    time_col_name: str = "time",
    event_type_col_name: str = "event_type",
    event_col_name: str = "event",
    resource_col_name: str = "resource_id",
    run_col_name: Optional[str] = "auto",
) -> pd.DataFrame:
    """
    Compute how many units of each resource step were busy at regular snapshots.

    Unlike `queue_size_over_time` (built on `reshape_for_animations`, "most
    recent event per entity wins"), resource occupancy is interval containment
    - a different question. This computes it exactly via a +1/-1 sweep over
    `resource_use_intervals`'s bouts rather than a per-snapshot membership
    scan: +1 at each bout's start, -1 at its end, sorted and cumulatively
    summed, then looked up onto the snapshot grid with `searchsorted`.

    Parameters
    ----------
    event_log : pandas.DataFrame
        Long-format event log, e.g. the output of `TrialLogger.to_dataframe()`.
    every_x_time_units : float, default=1
        Time granularity for snapshots.
    warm_up : float, default=0
        Start of the analysis window. See `resource_use_intervals`.
    limit_duration : float, optional
        End of the analysis window. `None` (default) uses the latest time seen
        anywhere in the trial - not per run, so every run shares the same grid.
    entity_col_name, time_col_name, event_type_col_name, event_col_name,
    resource_col_name : str
        Column names forwarded to `resource_use_intervals`.
    run_col_name : str or None, default="auto"
        Column identifying which run each row belongs to. See `event_durations`.

    Returns
    -------
    pandas.DataFrame
        Columns ``run_number``, ``event`` (the step - the *start* event's
        name), ``snapshot_time``, ``count``. One row per step per snapshot per
        run, including snapshots where nothing was in use - a genuine zero,
        not a missing row, matching `queue_size_over_time`'s convention.
        Empty (no rows, correct columns) if the log has no resource_use bouts
        at all.

    Raises
    ------
    ValueError
        If `every_x_time_units` is not positive.

    Notes
    -----
    Unclosed resource use (an entity still holding a resource when the window
    ends) is always treated as occupied through to the window end - dropping
    it would understate occupancy exactly when it matters most, the same
    reasoning as `resource_use_intervals`'s `unclosed="censor"` default. This
    function always uses that behaviour; there is no `unclosed` parameter.

    A bout is occupied on the half-open interval ``[start, end)`` - a unit
    freed exactly at a snapshot time is not counted as busy there. Paired with
    `plot_resource_utilisation_over_time`'s `line_shape="hv"` traces, this
    draws a resource as busy right up to, and not including, the instant it is
    freed.

    See Also
    --------
    resource_use_intervals : The underlying per-bout intervals this sweeps over.
    queue_size_over_time : The equivalent computation for a queue rather than a resource.
    """
    if every_x_time_units <= 0:
        raise ValueError(
            f"`every_x_time_units` must be positive, but {every_x_time_units} "
            f"was passed."
        )

    window_start, window_end = _resolve_window(
        event_log, limit_duration, warm_up, time_col_name
    )

    intervals = resource_use_intervals(
        event_log,
        unclosed="censor",
        warm_up=warm_up,
        limit_duration=limit_duration,
        entity_col_name=entity_col_name,
        time_col_name=time_col_name,
        event_type_col_name=event_type_col_name,
        event_col_name=event_col_name,
        resource_col_name=resource_col_name,
        run_col_name=run_col_name,
    )

    steps = sorted(intervals["event"].dropna().unique().tolist(), key=str)
    if not steps:
        return pd.DataFrame(columns=["run_number", "event", "snapshot_time", "count"])

    n_snapshots = int((window_end - window_start) // every_x_time_units) + 1
    snapshot_times = window_start + np.arange(n_snapshots) * every_x_time_units
    snapshot_times = snapshot_times[snapshot_times <= window_end]

    run_ids = sorted(intervals["run_number"].dropna().unique().tolist()) or [pd.NA]

    rows = []
    for run_id in run_ids:
        run_intervals = (
            intervals[intervals["run_number"] == run_id]
            if pd.notna(run_id)
            else intervals[intervals["run_number"].isna()]
        )
        for step in steps:
            step_intervals = run_intervals[run_intervals["event"] == step]
            starts = step_intervals["start"].clip(lower=window_start).to_numpy()
            ends = step_intervals["end"].clip(upper=window_end).to_numpy()
            valid = starts < ends
            starts, ends = starts[valid], ends[valid]

            if len(starts) == 0:
                counts = np.zeros(len(snapshot_times), dtype=int)
            else:
                change_times = np.concatenate([starts, ends])
                deltas = np.concatenate(
                    [np.ones(len(starts)), -np.ones(len(ends))]
                )
                order = np.argsort(change_times, kind="stable")
                change_times = change_times[order]
                cum_counts = np.cumsum(deltas[order])

                positions = (
                    np.searchsorted(change_times, snapshot_times, side="right") - 1
                )
                counts = np.where(
                    positions >= 0,
                    cum_counts[np.clip(positions, 0, len(cum_counts) - 1)],
                    0,
                ).astype(int)

            rows.extend(
                {
                    "run_number": run_id,
                    "event": step,
                    "snapshot_time": t,
                    "count": c,
                }
                for t, c in zip(snapshot_times, counts)
            )

    return pd.DataFrame(rows)[["run_number", "event", "snapshot_time", "count"]]


def _ensemble_mean(series_by_run: Sequence[Sequence[float]]):
    """Truncate every run to the shortest length and average across runs.

    Shared by `welch_moving_average` and `plot_warm_up_diagnostic`, so the
    latter can draw the raw ensemble-average trace and feed the *same*
    length-matched runs onward to `welch_moving_average` for each window -
    truncating twice would otherwise warn twice for the same unequal-length
    input.

    Returns
    -------
    tuple
        `(m, ensemble_mean, trimmed)`: the common length, the length-`m`
        array of per-index means, and the list of length-`m` per-run arrays
        it was computed from.
    """
    lengths = [len(run) for run in series_by_run]
    m = min(lengths)
    if max(lengths) != m:
        warnings.warn(
            f"Runs of unequal length were passed (lengths {lengths}); every "
            f"run is truncated to the shortest, {m}.",
            UserWarning,
            stacklevel=3,
        )
    trimmed = [np.asarray(run[:m], dtype=float) for run in series_by_run]
    ensemble_mean = np.mean(np.array(trimmed), axis=0)
    return m, ensemble_mean, trimmed


# How `welch_moving_average` smooths the ensemble-averaged series.
WarmUpMethod: TypeAlias = Literal["welch", "cumulative", "none"]


def welch_moving_average(
    series_by_run: Sequence[Sequence[float]],
    window: Optional[int] = None,
    *,
    method: WarmUpMethod = "welch",
) -> np.ndarray:
    """
    Smooth an ensemble-averaged series to visually locate a warm-up length.

    Underlies `plot_warm_up_diagnostic`. Takes one series per replication -
    e.g. queue length at each snapshot, resource occupancy at each snapshot,
    or per-entity durations in arrival order - and reduces the replications
    to a single smoothed curve whose early instability (or lack of it) is the
    visual signal a modeller reads off to choose `warm_up=`.

    Parameters
    ----------
    series_by_run : sequence of sequence of float
        One series per replication, each already in the order its warm-up
        length will be judged against (snapshot time order, or entity
        arrival order). Runs of unequal length are truncated to the
        shortest, with a warning - the ensemble average at index i needs a
        value from every run at that index, so a longer run contributes no
        extra information past the shortest run's end.
    window : int, optional
        Half-width of the moving-average window. Required, and must be a
        positive integer less than the (truncated) series length, when
        `method="welch"`. Ignored when `method="cumulative"` or
        `method="none"`, neither of which has a window.
    method : {"welch", "cumulative", "none"}, default="welch"
        - `"welch"`: Welch's (1983) moving-average procedure, as described
          in Law, *Simulation Modeling and Analysis*. The ensemble average is
          smoothed with a symmetric window of full width `2 * window + 1`;
          for the first `window` points, where a full-width window would run
          off the start of the series, it shrinks to the narrower symmetric
          window that does exist (`2i - 1` points, i.e. only the `i - 1`
          points actually available on each side - `i` here is Welch's own
          1-indexed position in the series, `i = 1` being the first point,
          not this function's 0-indexed output array) rather than returning
          `NaN` there - this is the detail a `pandas.rolling(center=True)`
          call gets wrong. A window this wide also has no full-width
          neighbourhood in the last `window` points of the series, so those
          are not returned at all: the output has length
          `len(series) - window`, not `len(series)` - a larger `window`
          gives a smoother curve at the cost of a shorter one.
        - `"cumulative"`: the plain expanding mean of the ensemble average,
          `mean(ensemble[:i + 1])` for every `i` - simpler and needs no
          window, but each new point only shifts the running mean by `1/i`,
          so a biased early transient decays out of it far more slowly than
          out of Welch's fixed-width window. The risk is not that this curve
          looks rougher - it is *smoother*, in a way that can make it look
          settled long after (or hide a real shift long before) the series
          has actually stabilised. This is the "cumulative mean" time series
          inspection technique demonstrated in the DES RAP book (Heather et
          al., 2026 -
          https://pythonhealthdatascience.github.io/des_rap_book/pages/guide/output_analysis/length_warmup.html),
          which plots both the pooled cumulative mean and each replication's
          own cumulative mean (matching `show_runs=True` below) and cites
          Robinson, S. (2004), *Simulation: The Practice of Model Development
          and Use* (Wiley), for the general "look for where the curve
          stabilises" principle. Returned at the series' full length.
        - `"none"`: the ensemble average itself, completely unsmoothed - no
          window, no running mean, nothing. A further step beyond the
          cumulative-mean inspection above - here dropping the running-mean
          smoothing entirely rather than only the fixed window - not itself
          the specific technique the DES RAP book demonstrates. Noisier than
          either other method by construction, since nothing here reduces
          the within-replication variance the ensemble average didn't
          already remove; useful specifically when you want to see that
          noise rather than have it smoothed away. Returned at the series'
          full length, identical to what `_ensemble_mean` computes.

    Returns
    -------
    numpy.ndarray
        The smoothed series. See `method` above for its length.

    Raises
    ------
    ValueError
        If `series_by_run` is empty; if `method` is not `"welch"`,
        `"cumulative"` or `"none"`; or if `method="welch"` and `window` is
        `None`, not a positive integer, or `>=` the (truncated) series
        length, leaving nothing to return.

    Notes
    -----
    Deliberately has no automatic warm-up-length selector. Welch's procedure
    is explicitly a visual one - a flatness threshold returns a confident
    number that is wrong on any series with slow drift, silently discarding
    the wrong amount of data with no signal anything went awry. Overlay
    several `window` values (see `plot_warm_up_diagnostic`) and read off the
    point where they agree, by eye.

    See Also
    --------
    plot_warm_up_diagnostic : Builds the figure this function's output is drawn into.
    """
    if len(series_by_run) == 0:
        raise ValueError("`series_by_run` must contain at least one run.")

    if method not in ("welch", "cumulative", "none"):
        raise ValueError(
            f"`method` must be 'welch', 'cumulative' or 'none'; got {method!r}."
        )

    m, ensemble_mean, _ = _ensemble_mean(series_by_run)

    if method == "none":
        return ensemble_mean

    if method == "cumulative":
        return np.cumsum(ensemble_mean) / np.arange(1, m + 1)

    if window is None or window < 1:
        raise ValueError(
            f"`window` must be a positive integer when method='welch'; got "
            f"{window!r}."
        )
    if window >= m:
        raise ValueError(
            f"`window` ({window}) leaves nothing to return from a series of "
            f"length {m} - Welch's procedure only defines a moving average up "
            f"to `len(series) - window` points. Pass a smaller `window`."
        )

    output_length = m - window
    smoothed = np.empty(output_length)
    for i in range(output_length):
        if i < window:
            smoothed[i] = ensemble_mean[: 2 * i + 1].mean()
        else:
            smoothed[i] = ensemble_mean[i - window : i + window + 1].mean()

    return smoothed
