
# 1.4.0

### ⚠️ Breaking changes

- Event logs containing more than one simulation run are now **rejected** by all four animation functions instead of being silently blended into a single animation. If you were passing an unfiltered multi-run log, you were not getting the animation you thought you were; filter to one replication first.
- Exit steps are written to your `event_type_col_name` column instead of a hardcoded `event_type` column — output of `reshape_for_animations` changes if you pass a custom event type column name.
- `TrialLogger.get_event_duration_stat(what="summary")` reported the *total* entity count under `unserved_count`. It now reports the number unserved, so that figure and `unserved_count_mean_per_run` will change.
- `TrialLogger` statistics now include runs added via `add_log` after construction, which were previously omitted from every calculation.
- `TrialLogger.plot_queue_size` plotted queue lengths that were wrong in three ways: capped at 61, missing every snapshot where a queue was empty, and a mean taken over only the runs that had somebody waiting. Any queue length chart you have previously reported will change.
- `TrialLogger.get_event_duration_stat(what="summary")` computed its per-run denominator only from runs where the event pair occurred at all. A run with neither event was silently excluded, so `served_count_mean_per_run` and `unserved_count_mean_per_run` were inflated whenever any run had zero of both events; both now divide by the true number of runs in the trial.

### Notes

- **BREAKING:** Multi-replication event logs are rejected rather than silently blended
    - Passing an event log containing several runs never raised and never warned — it produced an animation representing *no* run of your model. `reshape_for_animations` pivots the arrival and departure rows to work out when each entity was present, and that pivot averages duplicates: an entity arriving at t=1 in run 1 and t=41 in run 2 was given an arrival of 21 and a departure of 71. A later `groupby(...).tail(1)` then discarded one run's rows entirely
    - Every downstream check still passed, because the resulting frame is internally consistent and completely fictional
    - `reshape_for_animations`, `generate_animation_df`, `generate_animation` and `animate_activity_log` now all raise a `ValueError` naming the offending column and showing how to filter
    - Two independent checks, because neither alone suffices. A **run column** carrying more than one value is caught even when entity IDs are unique across runs; **an entity with more than one `arrival` or `depart`** is caught even when the run column is named something unexpected or is absent entirely. The second also catches entity IDs reused within a single run, which corrupts an animation in exactly the same way
    - New `run_col_name` argument on all four functions. Defaults to `"auto"`, which looks for a column named (case-insensitively) `run`, `run_number`, `replication`, `rep` or `run_id`. Pass an explicit name to override, or `None` to disable the check
    - Chosen over a deprecation period deliberately: warning first would mean another release cycle of users presenting wrong animations to stakeholders, and the only behaviour being removed is "silently produce a wrong answer". The constraint was previously documented only in a tutorial page and in a source comment sitting above code that did not enforce it
- **BREAKING:** `reshape_for_animations` now writes the exit step's event type to the column named by `event_type_col_name`
    - Previously it always assigned to a literal `"event_type"` column. A log using a custom event type column therefore came out with *two* type columns: the caller's, left empty on every exit row, and a spurious `event_type` containing nothing but `"exit"`
    - `generate_animation_df` filters on the caller's column, so exit steps were not being recognised as exits
    - If you use the default column names, nothing changes
- New `warm_up` argument on `reshape_for_animations` and `animate_activity_log`, for discarding a warm-up period without damaging the animation
    - Discarding warm-up is routine, and the obvious way to do it to an event log — `event_log[event_log["time"] >= warm_up]` — quietly breaks the result. Presence at each snapshot is worked out from arrival and departure rows, so truncating the log removes the `arrival` row of everyone who was already in the system, and those entities then appear in *no* frame at all. The entities lost are precisely the ones a steady-state animation exists to show: on a log with five entities queuing since before the boundary and two arriving after it, the queue was drawn holding two
    - `warm_up` trims the animation window instead of the log. Pass the whole event log and set `warm_up` to the end of your warm-up period; by default the snapshot grid is anchored on it, so the first frame lands exactly on the boundary — see `snapshot_alignment` below to keep the original grid instead
    - `warm_up` and `limit_duration` bound the window between them. `limit_duration` keeps its existing meaning, so adding `warm_up` to an existing call does not move the end of the animation
    - The default of `0` is a verified no-op — output is identical to omitting the argument
    - Not to be confused with `animate_activity_log`'s existing `start_time`, which is a time of day used only for labelling frames as clock times
    - Also faster than filtering afterwards, since the discarded frames are never built at all — around 4.6x on a run that is 80% warm-up
- New `snapshot_alignment` argument, controlling where the snapshot grid counts from when a `warm_up` is set
    - `"warm_up"` (the default) puts the first frame exactly on the boundary, so the animation opens on the state of the system as the warm-up ends
    - `"run_start"` keeps the grid running from time 0 and drops the early frames, so frame times stay the same ones you would get with no warm-up — useful when `warm_up` is not a multiple of `every_x_time_units` and you would rather keep round numbers. This matches the longstanding workaround of filtering the reshaped frame on `snapshot_time`, except that a snapshot falling exactly on `warm_up` is kept rather than dropped
    - The two are identical whenever `warm_up` is a multiple of `every_x_time_units`, and irrelevant when there is no warm-up
    - Alignment moves the frame times only — never which entities appear in them
- New `warm_up` argument on `add_sim_timestamp`, threaded through `EventLogger.generate_dfg`, for discarding a warm-up period before building a process map
    - This is a plain time-based filter, not a port of `reshape_for_animations`' `warm_up`. `discover_dfg` builds each case's edges from its own consecutive rows rather than reconstructing who was present at a given moment from arrival and departure rows, so dropping early rows here cannot make a case silently vanish from output it should still appear in — the animation's failure mode does not apply here
    - Two consequences worth knowing before relying on this for reporting: a case entirely within the warm-up is dropped completely, and a case that spans the cutoff loses the single edge connecting its last pre-cutoff event to its first post-cutoff event, since one side of that pair is no longer in the log. Both are intentional, so warm-up activity does not contribute to the transition statistics
    - The default of `None` keeps every row, matching current behaviour exactly, and is a drop-in replacement for filtering the event log by time before calling `add_sim_timestamp`, which is how this has been taught until now
- `backend` now matches case-insensitively for every spelling
    - The plotly express branch lowercased its input and the graph objects branch did not, so `backend="EXPRESS"` was accepted while `backend="GO"` was rejected as invalid
    - The error message also listed only two of the four graph objects spellings, so `"plotly graph objects"` and `"plotly go"` worked but were never advertised
- Closed-set string arguments are now typed as literals, so editors offer the valid values and type checkers catch a typo before the call runs
    - `backend` and `simulation_time_unit` on `generate_animation` and `animate_activity_log`, `what` on `TrialLogger.get_event_duration_stat` and `plot_metric_bar`, and the new `snapshot_alignment`
    - The runtime checks are unchanged — annotations are not enforced, and a wrong value typed into a notebook still needs to raise
    - `time_display_units` is deliberately left untyped, since alongside its named options it accepts any custom strftime format
- New warning when an event log contains entities with no `arrival` event
    - These are silently absent from every frame, because presence is decided by comparing arrival and departure times and a missing arrival compares as `False` against every snapshot
    - Nearly always the signature of a log truncated to remove a warm-up period, so the warning names the entities, explains why they will not appear, and points at `warm_up`
    - Both shapes are caught: an entity left with a `depart` row but no `arrival`, and an entity still in the system whose remaining rows are all queue or resource events, which is absent from the arrival/departure pivot entirely
- `reshape_for_animations` no longer fails on an event log in which no entity has departed
    - A truncated run, a warm-up period, or a model whose entities never leave produces no `depart` events, so the pivoted log had no `depart` column. Every snapshot was silently emptied and the function then failed with an opaque `KeyError: 'entity_id'`
    - A missing `depart` column is now read as "everyone is still in the system", which is what an absent departure means
    - A log with no `arrival` events now raises a `ValueError` naming the arguments to check, rather than failing later with an unrelated error
- `limit_duration=None` now behaves as the docstring describes in `reshape_for_animations`
    - The integer coercion applied to the argument rejected `None` before the function's own handling could run, and that handling would itself have failed by reading a column consumed by the pivot
    - It now resolves to the largest time in the event log, matching how `animate_activity_log` already computed the same default
- `wrap_queues_at=None` now behaves as documented in `generate_animation_df`
    - Two sites used the value arithmetically before the existing `None` branch was reached: the `step_snapshot_max` multiple check, and the overflow label offset inside an `np.where` (which evaluates both branches, so the condition could not short-circuit the division)
- `animate_activity_log` now respects `time_col_name` when working out a default `limit_duration`
    - It previously read a literal `"time"` column, so every caller with a custom time column hit `KeyError: 'time'`
- `hover_text_entity=None` now disables hover as documented
    - The underlying plotly express call does not accept the `hoverinfo` argument that was being passed, so this option raised `TypeError` rather than doing anything
- Passing a `scenario` for a model where no event position declares a resource no longer fails
    - This produced `KeyError: 'x_final'`, which read like a problem with the caller's data rather than a missing guard
- `custom_hover_data` is no longer modified in place
    - The list passed in was appended to directly, so it grew by an entry on every call and eventually referenced the same column twice
    - The resource column is now only offered when the event log actually contains one
- Invalid `backend` and `time_display_units` values now raise `ValueError` carrying the intended guidance
    - Both were raised as bare strings, which Python rejects with `TypeError: exceptions must derive from BaseException`, so the message explaining the valid options never reached the user
- An unrecognised `simulation_time_unit` now raises `ValueError` listing the valid units, instead of `UnboundLocalError`
- New warning when `time_display_units` is coarser than the snapshot interval
    - The animation frame is the formatted time, so e.g. ten-minute snapshots displayed as `'d'` all carry the same label. Snapshots are merged, entities from different moments are drawn on top of one another, and plotly may produce no frames at all
    - This previously happened silently and returned a plausible-looking static figure
- **BREAKING:** `TrialLogger` statistics now reflect logs added after construction
    - The combined trial dataframe was built once in `__init__` and never rebuilt, so a run added with `add_log` was counted by `summary()` while being absent from every statistic computed from that frame
    - A trial assembled by constructing empty and adding runs in a loop — a natural way to write it — produced statistics for no runs at all
    - The frame is now derived from the current set of logs on each access, so it cannot go stale
    - Any figure you have previously reported from a trial built this way was computed from a subset of your runs and will change
- **BREAKING:** `get_event_duration_stat(what="summary")` reports the number of unserved entities under `unserved_count`
    - It returned `series.size`, the total number of entities, so a trial where everyone was served still reported every entity as unserved. `unserved_count_mean_per_run` carried the same error
    - The standalone `what="unserved_count"` path was already correct, so the two routes to the same statistic disagreed
- **BREAKING:** `TrialLogger.plot_queue_size` reports the queue length that actually formed
    - Three separate errors, each of which made a queue look better than it was, and none of which produced any visual cue that something had been discarded
    - **Long queues saturated.** The chart was built by reshaping the log with the default `step_snapshot_max=60`, which caps how many entity icons an *animation* draws. With the cap applied to a line chart, a queue of 150 plotted as a flat 61 — a growing bottleneck reading as a stable queue. The cap is no longer applied here, since a line has no drawing limit
    - **Empty queues went missing.** A snapshot with nobody queuing produced no row to count, so no point was plotted and the line was drawn straight across the gap — asserting a queue over precisely the interval it had emptied. Genuine zeros are now plotted
    - **The mean was biased upwards.** It averaged only the runs that had somebody waiting at that moment, so two runs holding 1 and 0 gave a mean of 1.0 rather than 0.5. Every run now contributes at every snapshot
    - An event named in `event_list` that occurs in no run is plotted as zero throughout and now warns, since zero-filling would otherwise make a misspelt event name indistinguishable from a queue that never formed
    - Reshaping without the cap uses more memory than an equivalent animation
- `TrialLogger()` can be constructed with no arguments
    - This raised `ValueError: No objects to concatenate`, which ruled out creating an empty trial and filling it with `add_log`
- `TrialLogger.get_log_by_run(run, as_df=True)` returns a DataFrame
    - Both branches of the `as_df` check returned the same thing, so the parameter did nothing
- `TrialLogger` now rejects an `EventLogger` with no events or no `run_number`
    - The run id is read from the first event, so these previously failed with `IndexError` or stored `None` as the run id, making the log unretrievable by run
- `EventLogger.from_csv` now leaves the logger in a usable state
    - It assigned the DataFrame directly to the internal log, which is a list of records everywhere else. Afterwards `get_events_by_entity` and friends walked column names and failed with `AttributeError`, `to_json`/`to_json_string` failed with `TypeError`, and `to_csv` failed on an ambiguous truth value
    - Only `to_dataframe` and `summary` happened to work, so the breakage was easy to miss
- The "resource_id is recommended" warning now actually fires
    - It was defined as a validator on a field with a default, and pydantic skips those when the caller omits the field — precisely the case the check exists to catch. It only ever fired when a resource id *was* supplied but had the wrong type
    - Logging a `resource_use` or `resource_use_end` event with no `resource_id` now warns, as documented
- Removed a stray debug `print` from `EventLogger.plot_entity_timeline`, which dumped the entity's events to stdout on every call
- `VidigiStore.cancel_get` now works
    - It looked for the pending-request queue on itself, but `VidigiStore` wraps a `simpy.Store` rather than subclassing it. Every call raised `AttributeError`, which the method's `except ValueError` did not catch, so cancelling a request — and therefore modelling reneging with this class — was impossible
    - `VidigiPriorityStore` was unaffected, as it keeps `get_queue` as its own attribute
- `minimize_output_df` is deprecated and remains inert
    - It has never had any effect: the loop meant to implement it discarded the result of `.drop()`, so the documented default of `True` was always a no-op
    - Making it work now would change the output of every existing caller, including removing the `run` column, so the behaviour is deferred to 2.0
    - Passing it emits a `DeprecationWarning`; callers who never passed it are unaffected
- New `vidigi.analysis` module — the first piece of a numbers-in-DataFrames-out layer that the plotting functions will sit on top of
    - `event_durations(event_log, first_event, second_event, match=...)` pairs occurrences of two events per entity and computes the time between them, usable standalone on any event log, including one where an entity revisits a step
    - `match` controls how repeated occurrences are paired: `"first"`/`"last"` take the entity's earliest or latest of each event regardless of how many times either occurs; `"occurrence"` pairs the *n*-th of each in time order, and warns if an entity has an unequal count of the two
    - The pairing is an outer join, not a left join on the first event, so it captures both an entity that started but never finished, and one that finished with no matching start
    - `pathway` and `run_number` are always present in the output, even when the input log has neither column, since `EventLogger.to_dataframe()` drops all-null columns
- **BREAKING:** `TrialLogger.get_event_duration_stat` and the new `TrialLogger.get_event_durations` are now built on `vidigi.analysis.event_durations` instead of a `pivot`
    - `pivot` raises `ValueError: Index contains duplicate entries` for any entity that revisits `first_event` or `second_event` within a run - a rework loop - so those logs could not be analysed at all. This is now supported via the new `match` argument
    - At the default `match="first"`, results are identical to the old pivot everywhere it used to succeed - the only behaviour change is that logs which previously raised now return a value
    - `get_event_duration_stat`'s per-run denominator (used by `served_count_mean_per_run` and `unserved_count_mean_per_run`) is now the true number of runs in the trial rather than only those containing the event pair - see the breaking change above
    - New `TrialLogger.get_event_durations(first_event, second_event, match=...)` exposes the full per-entity duration frame directly, rather than only a single aggregated statistic
- New `vidigi.plots` module — `go.Figure`-returning charts, each a thin wrapper over the matching `vidigi.analysis` function
    - `plot_queue_size(event_log, event_list, limit_duration, ...)` is the first entry, extracted from `TrialLogger.plot_queue_size`. It operates on a plain event log DataFrame rather than a `TrialLogger`, so it also works on logs from `vidigi.ciw`, a CSV, or a hand-built frame
    - Its data preparation is `vidigi.analysis.queue_size_over_time(event_log, event_list, limit_duration, ...)`, giving queue-size-over-time a "numbers only" route for tables and reports as well as a chart
    - `**kwargs` keeps its existing meaning - forwarded straight to `plotly.express.line` - rather than being repurposed for column-name overrides, so no existing caller's styling kwargs silently start doing something else. Column names (`entity_col_name` and friends) are separate, explicitly named parameters on both functions
- `TrialLogger.plot_queue_size` gains a `warm_up` argument, for discarding a warm-up period the same way `reshape_for_animations` already supports
    - The default of `0` is a verified no-op - output is identical to omitting the argument
    - Internally, `TrialLogger.plot_queue_size` is now a thin delegator to `vidigi.plots.plot_queue_size`, called on the trial's combined dataframe. The four tests asserting exact queue-length values were left untouched, and passing unchanged is the proof the extraction is behaviour-preserving
- New `backend` argument on `plot_queue_size` (both `vidigi.plots.plot_queue_size` and `TrialLogger.plot_queue_size`), in response to feedback from advanced users who wanted a `plotly.graph_objects`-built chart to restyle afterwards
    - `backend="express"` (default) is the pre-existing behaviour, unchanged - `**kwargs` still forwards to `plotly.express.line`
    - `backend="go"` builds every trace explicitly instead: trace names, order and legend grouping are then deterministic rather than depending on `px`'s automatic per-run grouping, which is easier to target when restyling a specific run or event's trace afterwards. It also sets facet titles directly via `plotly.subplots.make_subplots`, with no need for the `event=` prefix `px`'s auto-generated annotations require stripping off. `**kwargs` is not used by this backend and is ignored with a warning if passed
    - Matches the accepted spellings and case-insensitive matching of `backend` on the animation functions (`"express"`/`"px"`/`"plotly express"`, `"go"`/`"graph objects"`/`"plotly graph objects"`/`"plotly go"`), for consistency across the package
    - Purely additive: no existing caller's output or `**kwargs` behaviour changes
- New `plot_duration_distribution` (both `vidigi.plots.plot_duration_distribution` and `TrialLogger.plot_duration_distribution`) - vidigi's first chart showing the *shape* of a duration rather than a single summary statistic
    - `kind="hist"` (default), `"box"`, `"violin"`, `"ecdf"`, `"ridgeline"` or `"heatmap"`. Histograms are numpy-binned and drawn as `go.Bar`, never `plotly.graph_objects.Histogram` - that bins in the browser, so its `y` values are never inspectable, in code or in a test. `"ecdf"` is drawn as a step line, since linear interpolation between sorted points would draw cumulative probabilities that never occurred
    - `split_by="run"` or `"pathway"` draws one trace per distinct value of that column instead of pooling every duration together, using the same bin edges across groups for `kind="hist"` so bars stay comparable
    - `"ridgeline"` and `"heatmap"` both require `split_by`, and exist for the case `split_by` was built for but a plain `"box"`/`"violin"` handles badly: comparing a duration's distribution across *many* groups (e.g. every run in a 100-replication trial) without the chart turning into an unreadable pile. `"ridgeline"` stacks one density curve per group with a slight vertical overlap; `"heatmap"` draws duration on the x-axis and one row per group, coloured by count or density, and scales further still since it costs no vertical space per row at all. Ridgeline heights are always a per-group density, never a raw count, so a group with more observations does not draw a taller ridge for the same underlying shape
    - Built entirely on the existing `vidigi.analysis.event_durations` - no new analysis function was needed, since a distribution is a reshaping of durations already, not a new statistic. Incomplete pairs (`duration` is `NaN`) are dropped before plotting
    - New-function style, per the plans for the rest of the 1.4.0/1.5.0 plotting work: no `interactive=`, always returns a figure; `**kwargs` forwards to `vidigi.analysis.event_durations` for column-name overrides, not to a plotly call - there's no single call to forward general styling to, since `go` builds several traces by hand. Style the returned figure directly, or pass `title=`
- New `[stats]` optional extra (`pip install vidigi[stats]`, pulling in `scipy>=1.10`), and two new `vidigi.analysis` functions building towards confidence intervals across replications
    - `replication_means(durations, what=...)` reduces a per-entity durations frame (e.g. `event_durations`'s output) to one value per run - the independent unit any interval must be computed over
    - `mean_confidence_interval(values, ci_level=0.95)` computes a confidence interval over those replication-level values using Student's t with `n - 1` degrees of freedom, never a normal approximation - at `n=5`, a typical replication count, `z` is 29% too narrow. Only this function needs `scipy`; it is not imported anywhere else, and raises `ImportError` naming `pip install vidigi[stats]` if missing
    - Neither function accepts pooled per-entity observations disguised as replications: entities within a run are strongly serially correlated, so an interval computed that way can be roughly 30x too narrow. `replication_means` rejects entity-counting aggregations (`"count"`, `"unserved_rate"`, `"summary"`, ...) for the same reason - they answer "how many", not "what value", and are not meaningful re-averaged across runs
- `plot_metric_bar` (both `vidigi.plots.plot_metric_bar` and `TrialLogger.plot_metric_bar`) gains `across`, `error_bars`, `ci_level` and `show_runs`, for putting an uncertainty interval on a bar chart for the first time
    - `across="entities"` (the default, unchanged) pools every entity's duration into one statistic per bar, exactly as every prior release did
    - `across="runs"` computes the chosen statistic separately within each run, then draws the mean of those per-run values - the number an `error_bars="ci"` interval is actually about
    - `error_bars`: `"ci"` (needs `scipy`), `"sd"`, `"se"`, or the asymmetric `"range"`/`"iqr"`, computed over the per-run values. Requires `across="runs"` - an interval over replication means attached to a bar pooled over entities would be internally inconsistent, since entities are correlated within a run and runs are the independent unit
    - `show_runs=True` overlays each run's individual value as a point on top of its bar; also requires `across="runs"`
    - Internally, `TrialLogger.plot_metric_bar` is now a thin delegator to the new `vidigi.plots.plot_metric_bar`, operating on the trial's combined dataframe rather than calling `get_event_duration_stat` per pair directly
    - `**kwargs` keeps forwarding to `plotly.express.bar` unchanged - the one function newly moved into `vidigi.plots` that is *not* switched to column-name passthrough, since the example notebook already relies on `title=`/`width=` reaching the chart
- New `vidigi.analysis.resource_use_intervals(event_log, ...)`, pairing `resource_use`/`resource_use_end` rows into one interval per bout of resource use — the first vidigi function able to answer "how busy was this resource"
    - Splits on `event_type`, not `event`, since a bout's start and end rows are named differently (e.g. `"treatment_begins"`/`"treatment_ends"`); the *start* row's event name is what identifies the step
    - An entity still holding a resource when the analysis window ends is **censored by default** (`unclosed="censor"`): its interval is clipped to the window end rather than dropped. Dropping understates utilisation exactly when it matters most, since entities still holding a resource at the end of a run are disproportionately those in a congested system — the same failure mode as the `plot_queue_size` bugs fixed earlier in 1.4.0. `unclosed="drop"` opts out
    - An end row with no matching start (a logging defect) is always dropped, with a warning
    - A log with no `resource_id` at all falls back to pairing on `(run, entity)`, with a warning — `busy_time`/`mean_in_use`/`utilisation` stay exact, only the per-unit breakdown is lost. A log with `resource_id` on *some* resource-use rows but not others raises, since pairing would otherwise silently cross entities using different physical units
- New `vidigi.analysis.resource_utilisation(event_log, by=..., ...)`, aggregating those intervals into busy time, mean-in-use and utilisation — always one row per run per group, matching `replication_means`'s "aggregation across runs is the plotting layer's job" convention
    - `by="step"` (default) or `"resource"` (one physical unit, capacity always `1`) — or `"run"`, pooling every step/unit together, where `capacity` is the **sum** of every pooled step's capacity (`NaN` if any is unresolved). Pooling more than one distinct step warns: a blended busy-time/utilisation figure across resource *types* (e.g. doctors and beds summed together) is rarely the number a capacity-planning question is asking, even when it is arithmetically well-defined
    - `mean_in_use` needs no capacity at all (`busy_time / window_length`) and is always populated; `utilisation` additionally divides by capacity and is `NaN` wherever that is unresolved. A resolved `utilisation` over `1` always warns — this definition of utilisation can never legitimately exceed `1`, so it is a live signal of a resolution or logging problem worth surfacing immediately rather than only visually once a plotting layer exists
    - A `(run, group)` combination absent from a specific run but present in another (a resource that happened not to be used that run) reports a genuine `busy_time` of `0` there, not a missing row — the same "real zero" convention `queue_size_over_time` already uses. This also covers `by="resource"` when `resource_id` is missing from the whole log: rather than the per-unit breakdown collapsing to zero *rows*, it reports one pooled row per run, with a warning
- New `_resolve_resource_capacities`, resolving a `{step: capacity}` mapping from **four routes**, in precedence order: an explicit `resource_capacities={step: count}` dict; `scenario=` with `resource_map={step: "attribute_name"}`; `scenario=` with `event_position_df=` (reusing the `resource` column already used by the animation functions); or `capacity="infer"`, which estimates each step's capacity as the number of distinct `resource_id`s seen for it — a **lower bound** (a never-used unit is invisible), so it always warns
    - Passing nothing at all is not an error — `utilisation` is simply `NaN` throughout, with `mean_in_use` still fully populated
    - `scenario` given without one of the three ways to use it raises, naming all three with an example each; a `resource_map`/`event_position_df` naming an attribute `scenario` does not have raises `AttributeError` naming the attribute, the step, and every available attribute on `scenario`
    - The `event_position_df` route reuses a new shared helper, `vidigi.utils._resource_map_from_event_position_df`, extracted from `animation.py`'s pre-existing resource-icon lookup so the two cannot drift on what counts as "this event has a resource". The extraction is behaviour-preserving — every existing animation test passes unchanged, which is its proof
- `log_resource_use_start`/`log_resource_use_end` gain an explicit `event=` parameter, naming the specific step (e.g. `"treatment_begins"`) rather than the generic `"start"`/`"end"` default — needed to tell different resource-use steps apart in `resource_use_intervals`. This was already possible by passing `event=` as an undocumented extra keyword argument, so behaviour for every existing caller is unchanged
- New `TrialLogger.get_resource_utilisation()`, a thin delegator to `vidigi.analysis.resource_utilisation` called on the trial's combined dataframe

### Testing

Test coverage grew from 31 to 497 tests, concentrated on the parts of the pipeline where a
mistake changes what the animation *shows*, or what the reported numbers *say*, rather
than raising an error.

- `reshape_for_animations` is now asserted by value rather than by shape: which entities are present at each snapshot, which event each is shown at, queue ordering, exit step timing, and the `step_snapshot_max` cap
- `generate_animation_df` gained its first dedicated coverage: entity and resource positions, queue wrapping, icon assignment, and the overflow placeholder
- `animation.py` gained its first dedicated coverage: frame count and ordering, animation timings, hover configuration, resource markers, every time display format, background image embedding, and the error paths
- `EventLogger` gained its first dedicated coverage: the event shape each helper produces, time taken from both simpy-style and salabim-style environments, event validation and its warnings, timestamp parsing, retrieval, and export
- `TrialLogger` gained its first dedicated coverage: construction, that statistics stay current as runs are added, and every duration statistic checked against hand-computed values including the served/unserved accounting
- The single-replication guard is covered across all four animation entry points, including column-name detection, both independent checks, and — most importantly — that a valid single-run log carrying a run column is still accepted
- Warm-up handling is covered end to end: that `warm_up` shows the entities a truncated log loses, that the truncation trap itself is detected, that both snapshot alignments move frame times without changing who is in them, and that the defaults are a true no-op rather than merely a similar result
- Every value advertised by a literal-typed argument is asserted to be accepted at runtime, so the annotations cannot drift from the checks they describe
- `process_mapping` gained its first dedicated coverage: the new `warm_up` filter, and what it does and does not affect for a case that spans the cutoff versus one entirely inside it
- `plot_queue_size` is now asserted against hand-computed queue lengths rather than only checking that a figure came back — the previous tests would have passed against a blank chart, and did pass while every long queue was saturating
- `cancel_get` is now covered for both store types, including an end-to-end reneging scenario asserting who is served and when
- Two invariants the source had flagged as unchecked are now enforced — no entity is drawn in two positions within a single frame, and each entity keeps the same icon throughout
- `vidigi.analysis.event_durations` is covered against hand-computed durations, including a rework-loop fixture the old `pivot`-based calculation cannot even run against, every pairing mode, the outer-join edge cases (started-but-unfinished and finished-but-unstarted), and the missing-run/missing-pathway-column fallbacks
- `TrialLogger.get_event_duration_stat`, the new `get_event_durations`, and `vidigi.analysis.event_durations` directly are all pinned against the old `pivot`-based calculation on every applicable existing fixture — including one with a run column spelled `run` rather than `run_number`, to check `run_col_name="auto"` against the same reference — so the rebuild is proven byte-for-byte equivalent wherever the pivot used to work. A dedicated regression test covers the per-run denominator fix, proven to fail against the old formula before being restored
- `vidigi.analysis.queue_size_over_time` and `vidigi.plots.plot_queue_size` are covered directly as free functions, not just through `TrialLogger`, including a warm-up window trim proven to fail if the argument were dropped, `run_col_name="auto"` detecting a plain `run` column, a log with no run column at all, and that plotly express kwargs still reach the chart after the extraction
- `backend="go"` on `plot_queue_size` is covered for hand-computed queue lengths (single and faceted), the empty-queue-as-zero and mean-across-runs behaviour matching the express backend, warm-up trimming, every accepted spelling and case-insensitive matching, the invalid-backend error, and that facet row placement is correct (proven to fail if a mutated row mapping put every event's traces on the same row)
- `plot_duration_distribution` is covered for every `kind` against hand-computed (or independently numpy-computed) bin edges, counts, densities, raw values and ECDF step arrays; `split_by` is checked as a full `{trace name: values}` mapping for both `"run"` and `"pathway"`, and proven to fail if the two columns were swapped; the ECDF's step shape is proven to fail if `line_shape="hv"` were dropped; incomplete pairs are confirmed dropped before plotting rather than erroring or appearing as `NaN`; and every `DistributionKind`/`SplitBy` literal value is asserted to be accepted at runtime, matching the pattern already used for `DurationStat`
- `"ridgeline"` and `"heatmap"` are covered for the full per-group polygon/matrix against independently numpy-computed bin edges and densities/counts, that both require `split_by`, and - proven to fail if the density were swapped for a raw count - that a group with more observations draws the same ridge height as one with fewer, given the same underlying shape
- `replication_means` and `mean_confidence_interval` are covered against a purpose-built fixture (`unequal_run_loggers`) whose durations are *not* all equal, so `std` and every CI half-width are non-zero and `across="entities"` genuinely differs from `across="runs"` - every expected value (run means, pooled mean, standard error, half-width) is hand-computed against a published Student's t table, never derived from `scipy` calling itself. Two mutations are proven to fail their respective tests before being reverted: computing the interval over pooled per-entity durations instead of replication means, and swapping `t.ppf` for a normal `z.ppf`. A missing `scipy` is simulated (not actually uninstalled) to confirm the `ImportError` names `pip install vidigi[stats]`
- `plot_metric_bar` is covered for both `across` modes against the same hand-computed values, every `error_bars` kind against independently computed spreads (including the asymmetric `"range"`/`"iqr"`), that `ci_level` actually reaches the confidence-interval calculation rather than being silently ignored, `show_runs`'s overlay points, that `error_bars`/`show_runs` are rejected without `across="runs"`, the "no run has a complete pair" and single-replication (`NaN` half-width, with and without a warning) edge cases, and that `**kwargs` still reaches `plotly.express.bar` unchanged after the extraction into `vidigi.plots`
- An independent adversarial review of the tests added for replication statistics and `plot_metric_bar` found one tautological test (a quantile assertion whose fixture had no per-run variation for `q` to distinguish) and one silently-untested parameter (`ci_level`); both are now fixed and mutation-proven, alongside the two edge-case gaps above
- `resource_use_intervals` is covered against a purpose-built fixture (`resource_use_loggers`) with a resource idle in one run but used in another, proving a genuine zero is reported rather than a missing row; `unclosed="censor"` vs `"drop"` are covered as a mutation-proof pair (busy time 5 vs zero rows), the orphan-end and missing/partially-null-`resource_id` paths are each covered with their warning or error, and busy-time clipping is checked against a `warm_up` trim
- `_resolve_resource_capacities` is covered for the full `{step: capacity}` dict from each of routes A-D (not sampled entries), that route A takes precedence when multiple routes are redundantly supplied, both error paths (`scenario` with no route, and a `resource_map`/`event_position_df` naming a missing attribute — checked to include the attribute, the step and the available-attributes list), and the missing-capacity/unknown-step warnings
- `resource_utilisation` is covered for all three `by` modes against the fixture's hand-computed values, that `by="resource"`'s capacity is always exactly `1` regardless of what capacity route is supplied, and that `by="run"` agrees with `by="step"` when there is only one step, sums capacities (and warns) when more than one is pooled, and propagates `NaN` if any pooled step's own capacity is unresolved
- The extraction of `vidigi.utils._resource_map_from_event_position_df` out of `animation.py` is proven behaviour-preserving by the existing animation suite (84 tests) passing unchanged
- Three independent expert reviews (Python code quality, DES/OR domain correctness, and test QA) of the resource-utilisation commit found two real bugs, now fixed and covered by a mutation-proven regression test each:
    - `event_durations` and `resource_use_intervals` both paired rows via `groupby(...).cumcount()`/`.head(1)`/`.tail(1)`, which default to `dropna=True` — a `NaN` in a pairing key (e.g. a malformed `entity_id`) either fabricated a cross-joined pairing (`match="occurrence"`, `resource_use_intervals`) or silently dropped the entity from the output entirely (`match="first"`/`"last"`), with no error or warning either way
    - `by="run"`'s "do the pooled steps share one capacity" check read `capacities` globally across the whole trial rather than the run being aggregated, so two runs each using only one (different) resource type both came out `NaN` even though each was individually well-defined — and, separately, two different resource types that happened to share the same per-unit capacity used that single value as the divisor for their *combined* busy time, silently producing utilisation over 100% instead of a coherent pooled figure. Both are fixed by the sum-based redesign described above
    - Also added along the way: `by="resource"` no longer silently returns zero rows instead of a genuine zero when `resource_id` is missing from the whole log; `resource_use_intervals`/`resource_utilisation` correctly pair an entity revisiting the same `resource_id` twice in one run (proven to fail if the pairing key that prevents this were dropped); a zero-length window (`warm_up == limit_duration`) now raises instead of silently dividing by zero; `event_type_col_name` naming a missing column now raises a legible `ValueError` instead of a bare `KeyError`; and the `capacity="infer"` warning now names the common "resource_id doesn't identify individual units" failure mode explicitly, not just "a never-used unit is invisible"

# 1.3.1

- Add support for pandas 3.13 and 3.14
- Handle pandas FutureWarning that was outputting multiple warnings for Pandas 2.2.0 and above relating to handling of grouping columns in apply
    - Subsequently replaced this entire block with a different, more performant approach that is agnostic to pandas version
- Handle pandas FutureWarning around TimeDeltaIndex unit keyword deprecation for Pandas 2.2.0 and above

# 1.3.0

### Enhancements
- Adjust how environment time is accessed to allow salabim environments to work with logger (thanks [Amy](https://github.com/amyheather)!)
- Allow passing of local background image (thanks [Amy](https://github.com/amyheather)!)
    - There may still be some issues when trying to render outputs via GitHub actions

### Fixes
- Changes to generate_animation_df to fix bug where entities would sometimes seem to reappear from the top left for their final exit step
- Change default for step_snapshot_max to 60 (from 50) so that if you use the default for this and wrap_queues_at (20), you won't end up triggering a warning (thanks [Amy](https://github.com/amyheather)!)
- Add a better default for the set_limit_duration parameter. This now defaults to the maximum time seen in the simulation rather than 1440, which was equivalent to 1 day in minutes (thanks [Amy](https://github.com/amyheather)!)

### New examples
- Example added of using vidigi with Salabim (thanks [Amy](https://github.com/amyheather)!)

# 1.2.2

### Examples
- New example available of how to use vidigi to visualise an agent based simulation

### Fixes
- Fixes to custom hover data assignment so that custom hover fields are now available
- Fixes to custom hover data assignment in case of no scenario being specified
- Fixes to docstring around custom hover text definition (incorrectly said to use column names rather than customdata[0] notation)

# 1.2.1

- Major redesign of documentation
- Add `EventLogger.generate_dfg()` method that wraps the various dfg functions for convenient access.
- Add extra debug print statement to show start time of first animation transformation step.

# 1.2.0

- [EXPERIMENTAL] Add support for creating directly-follows-graphs (process maps) from vidigi event logs
    - in Graphviz.
    - in jupyter notebooks using ipycytoscape.
    - Streamlit using streamlit-cytoscape.

e.g.
![](assets\2026-01-08-18-03-34.png)

# 1.1.1

- Fix minor bug with default hover text where incorrect/confusing time unit could display next to snapshot time in hover


# 1.1.0

- Add TrialLogger class, allowing storage of multiple EventLogger objects and access to new helper functions for trial summarisation and plotting
- Fix plot_entity_timeline() method in EventLogger
- Add from_csv() option for generating EventLogger object from existing dataframe, allowing access to EventLogger's helper functions even when you have not used it for the initial logging
- Improve default hover tooltip for entities
- Add support for custom hover tooltips for entities
- Add helper function for including ASCII gauges to better visualise large queues
- Added option to swap out '+ x more' text for an ASCII gauge in generate_animation and animate_activity_log
- Improved how '+ x more' and ASCII gauges are handled as entities, preventing them from flying in/out on most frame updates
- Various improvements to type hinting and documentation of functions
- Added various warnings for incorrect types in core functions
- Added warning when step_snapshot_limit is not a multiple of wrap_queues_at (which can cause odd behaviour for placement of the '+ x more' text or ASCII excess queue gauge)
- Added and refined several documentation pages
- Minor refactoring and efficiencies to reshape_for_animations function
- Added some very basic tests for reshape_for_animations function

# 1.0.2

- Bump minimum Python version to 3.10 to simplify support for install across both conda-forge and python. 3.9 is no longer going to be supported after October 2025.

# 1.0.1

- Added 'background_image_opacity' argument to generate_animation and animate_activity_log. Default opacity is 0.5, which matches the previous hardcoded value.
- Added 'overflow_text_color' argument to generate_animation and animate_activity_log. Default is 'black'. Overflow text refers to the '+ x more' text that appears when queue lengths exceed the snapshot size.
- Added 'stage_label_text_colour' argument to generate_animation and animate_activity_log. Default is 'black'. These are the optional labels showing the stages as defined in the event position dataframe, which you may be using instead of passing in a custom background with stage labels.
- Add ability to log custom events with non-standard event_type using the .log_custom_event() method of the EventLogger class.
- Fully empty columns are now automatically removed when
    - exporting event log as df or csv
    - using prep.reshape_for_animation
    - using prep.generate_animation_df
- Experimental: Added a graph objects backend (alternative to plotly express). This is not recommended for active use - it primarily exists to help explore ways in which further customisations could be applied to the plot.

# 1.0.0

Migration guide below!

## Changelog

### BREAKING CHANGES

- significant changes to `VidigiPriorityStore`
    - BREAKING: the original implementation of `VidigiPriorityStore` has been renamed to `VidigiPriorityStoreLegacy`
- default entity column name for all prep and animation functions is now 'entity_id' rather than 'patient'. This can be managed by passing in the argument `entity_col_name="patient"` to each of these functions.
- various classes and functions have been moved into more appropriate files, rather than all existing in `Utils`.
    - VidigiStore, VidigiPriorityStore, VidigiPriorityStoreLegacy and other resources are now in `vidigi.resources`
    - EventLogger is now in `vidigi.logging`
- parameter `icon_and_text_size` has been removed and replaced with separate parameters
    - `resource_icon_size`
    - `entity_icon_size`
    - `text_size`
- parameter `gap_between_rows` has been removed and replaced with separate parameters for queues and resources
    - `gap_between_queue_rows`
    - `gap_between_resource_rows`
- CustomResource is now called VidigiResource. This generally should not cause problems as you are likely to only be accessing it indirectly through use of VidigiStore or VidigiPriorityStore.
- `init_items` argument for VidigiStore and VidigiPriorityStore has been replaced with `num_resources`. Defaulting to none, this functions identically to the `populate_stores` function, but instead allows you to initialise the resource on start.
- the dataframe expected by `generate_animation_df` is now `full_entity_df`, not `full_patient_df`. Only the parameter name needs updating.
- the dataframe expected by `generate_animation` is now `full_entity_df_plus_pos`, not `full_patient_df_plus_pos`. Only the parameter name needs updating.

NEW FEATURES:

Adds

- an additional `VidigiStore` class to replace use of standard store
- tests to ensure identical functioning of VidigiStore, VidigiPriorityStore and VidigiPriorityStoreLegacy to their core simpy counterparts

The benefit of these new classes is that they allow the common resource requesting patterns to be used

So

```python
with self.nurse.request() as req:
    # Freeze the function until the request for a nurse can be met.
    # The patient is currently queuing.
    yield req
```

will work when using a VidigiStore or VidigiPriorityStore - mimicking the syntax of making a request from resources - while supporting the inclusion of a resource ID attribute (not possible with traditional simpy resources) that is necessary to grab for simpy.

To access the attribute, it does necessitate some small change -


```python
with self.nurse.request() as req:
    # Freeze the function until the request for a nurse can be met.
    # The patient is currently queuing.
    nurse_resource = yield req ## NEED TO ASSIGN HERE
```

So
`req.id_attribute` would not work

but

`nurse_resource.id_attribute` would

This is hopefully still a far less substantial change than was required previously, where models using resources had to switch to using `.get()` and `.put()`.

Further testing still required for more complex request logic that incorporates aspects like reneging.

Additional new features:

- allow flexible naming of all key input columns - so you're no longer limited to 'patient', 'event', 'event_type', 'resource_id', 'time', 'pathway'.
    - these are now controlled with the parameters `entity_col_name`, `event_col_name`, `event_type_col_name`,  `resource_col_name", "time_col_name", "pathway_col_name`
- add helper class for event logging (`from vidigi.logging import EventLogger`)
- add helper class and function for generating an event positioning dataframe (`from vidigi.utils import EventPosition, create_event_position_df`)
- add helper function for generating a repeating overlay to the final animation, e.g. to make it clear when something like night or a clinic closure is occurring (`from vidigi.animation import add_repeating_overlay`
- add in a wide range of additional ways that the simulation time can be displayed (e.g. 'Simulation Day 1', am/pm rather than 24 hour, or even custom strftime string)

### BUGFIXES

- fix bugs preventing the generation of 'resourceless' animations
- fix bugs relating to resource wrapping with multiple pools
- prevent shifting of entities to the exit position on the final frame
- fix bug leading to skipped frames when no entities present
- fix bugs with ordering of ciw logs
- fix bug with incorrect end type for resource use in ciw logs
- ensure sim start and end time are respected in different situations
- ensure sensible behaviour when start_time parameter is provided but start_date is not
- ensure exit step always shown

### OTHER

- bump ciw example from 2.x to 3.x
- add more complex ciw example
- add resourceless queue examples
- add multiple concurrent trace example

## 🚀 Migration Guide: `vidigi` 0.0.4 → 1.0.0

This guide will help you update your code and workflows to work with `vidigi` version **1.0.0**, which includes **breaking changes**, **new features**, and **important bug fixes**.

---

### ⚠️ Breaking Changes

#### 1. Default Entity Column Name

**Was:** `'patient'`
**Now:** `'entity_id'`

Update your function calls OR change your entity ID column name to entity_id:

    # Before
    animate_activity_log(event_log,  event_position_df)

    # After
    animate_activity_log(event_log,  event_position_df, entity_col_name="patient")

---

#### 2. Module Reorganization

Some classes and functions have moved:

Old Location | New Location
-------------|--------------
`vidigi.utils.VidigiPriorityStore` | `vidigi.resources.VidigiPriorityStoreLegacy`

Update your import statements accordingly.

---

#### 3. Visual Parameter Changes

- `icon_and_text_size` → replaced with:
    - `resource_icon_size`
    - `entity_icon_size`
    - `text_size`

- `gap_between_rows` → replaced with:
    - `gap_between_queue_rows`
    - `gap_between_resource_rows`

---

#### 4. Parameter names for main dataframes in step-by-step functions

- the dataframe expected by `generate_animation_df` is now `full_entity_df`, not `full_patient_df`. Only the parameter name needs updating.
- the dataframe expected by `generate_animation` is now `full_entity_df_plus_pos`, not `full_patient_df_plus_pos`. Only the parameter name needs updating.

#### 5. `CustomResource` Renamed

`CustomResource` is now `VidigiResource`.
This is typically used indirectly through `VidigiStore` or `VidigiPriorityStore`, so minimal changes may be needed unless you were using it directly.

---

#### 6. Resource Initialization Parameter

`init_items` has been **replaced** with `num_resources` in `VidigiStore` and `VidigiPriorityStore`.

Example:

##### Before

`resource_store = VidigiStore(simulation_env, init_items=[...])`

OR

`resource_store = simpy.Store(simulation_env)`

`populate_store(5, resource_store, simulation_env)`

##### After

`resource_store = VidigiStore(simulation_env, num_resources=3)`

---

### ✨ New Features

#### ✅ Flexible Column Names

You can now customize column names in the animation and animation prep functions, meaning you are no longer tied to using 'patient' for your entity IDs!

- `entity_col_name`
- `event_col_name`
- `event_type_col_name`
- `resource_col_name`
- `time_col_name`
- `pathway_col_name`

Defaults are

- entity_id
- event
- event_type
- resource_id
- time
- pathway

(note 'pathway' is an optional column you may choose not to populate)


### ✅ What You Should Do

- [ ] Update your column name to 'entity_id' instead of 'patient' or pass overrides in the form of 'entity_col_name="patient"`
- [ ] Update import paths
- [ ] Update parameter names for the main dataframe in `generate_animation_df` and `generation_animation` (if using the step-by-step animation functions instead of the all-in-one)
- [ ] Switch from VidigiPriorityStore to VidigiPriorityStoreLegacy if you don't want to have to make any changes to how you request resources
- [ ] Replace removed sizing and spacing parameters with new ones
- [ ] Explore new features and examples - the new resource types, event logging helpers and event positioning helpers may make your life easier!

---

If you run into issues or have questions, check out the documentation or open an issue on the repo. Thanks for upgrading!
