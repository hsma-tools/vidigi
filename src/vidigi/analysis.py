"""Numbers in, DataFrames out.

Companion module to `vidigi.plots`: every chart in `plots.py` is a thin wrapper
around a function defined here, so each plot has a public "give me the numbers"
twin for tables and reports. Nothing in this module imports plotly or
`vidigi.logging` - every function here takes DataFrames, never an `EventLogger`
or `TrialLogger`.
"""

import difflib
import warnings
from typing import Literal, Optional, TypeAlias

import pandas as pd

from vidigi.utils import _resolve_run_column

MatchMode: TypeAlias = Literal["first", "last", "occurrence"]


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
        `event_col_name`; or if `pathway_col_name` names a column that does not exist.

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
        subset["occurrence"] = subset.groupby(group_keys).cumcount()
        if match == "first":
            subset = subset.groupby(group_keys).head(1).copy()
            subset["occurrence"] = 0
        elif match == "last":
            subset = subset.groupby(group_keys).tail(1).copy()
            subset["occurrence"] = 0
        return subset

    firsts = _prepare(first_event)
    seconds = _prepare(second_event)

    if match == "occurrence":
        first_counts = firsts.groupby(group_keys).size()
        second_counts = seconds.groupby(group_keys).size()
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
