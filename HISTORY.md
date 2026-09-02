
# 2.0.0

### ⚠️ Breaking changes

- Event logs containing more than one simulation run are now **rejected** by all four animation functions instead of being silently blended into a single animation. If you were passing an unfiltered multi-run log, you were not getting the animation you thought you were; filter to one replication first.
- Exit steps are written to your `event_type_col_name` column instead of a hardcoded `event_type` column — output of `reshape_for_animations` changes if you pass a custom event type column name.
- `TrialLogger.get_event_duration_stat(what="summary")` reported the *total* entity count under `unserved_count`. It now reports the number unserved, so that figure and `unserved_count_mean_per_run` will change.
- `TrialLogger` statistics now include runs added via `add_log` after construction, which were previously omitted from every calculation.
- `TrialLogger.plot_queue_size` plotted queue lengths that were wrong in three ways: capped at 61, missing every snapshot where a queue was empty, and a mean taken over only the runs that had somebody waiting. Any queue length chart you have previously reported will change.
- `TrialLogger.get_event_duration_stat(what="summary")` computed its per-run denominator only from runs where the event pair occurred at all. A run with neither event was silently excluded, so `served_count_mean_per_run` and `unserved_count_mean_per_run` were inflated whenever any run had zero of both events; both now divide by the true number of runs in the trial.
- `TrialLogger.get_resource_utilisation()`, `.plot_resource_utilisation()` and `.plot_resource_utilisation_over_time()` now default `resource_col_name` to `None` (auto-detect) instead of the literal `"resource_id"`. If your trial has a `unique_resource_id` column on *some* resource-use rows but not others, a call that used to succeed under the old default now raises `ValueError` — pass `resource_col_name="resource_id"` explicitly to keep the old behaviour, or fix the partial logging.
- `animate_activity_log` / `generate_animation` now raise `ValueError` if `custom_hover_data` is passed without a custom `hover_text_entity`. The built-in default template indexes six fixed columns, so combining it with `custom_hover_data` previously rendered garbled hover text; callers who never passed `custom_hover_data`, or who already paired it with their own template, are unaffected.

### New features

- New `queue_direction` argument on `animate_activity_log`, `generate_animation` and `generate_animation_df`, plus an optional per-event `direction` column on `EventPosition` / `event_position_df`, for building a queue left-to-right instead of the default right-to-left
    - Many entity emojis face a direction that reads better with the front of the queue at the bottom-left rather than the bottom-right; `queue_direction="right"` puts it there, and the queue (and its wrapped rows) mirror accordingly
    - Per-event `direction` (`EventPosition(..., direction="right")`, or a `direction` column on a hand-built / CSV `event_position_df`) overrides the animation-wide setting; an `event_position_df` with no `direction` column at all is unaffected
    - The default `"left"` is a verified no-op - `generate_animation_df` output is byte-identical to omitting the argument
    - Resource-use icon placement and the resource-availability dots follow the same setting, so an entity in service lines up with the side it queued on; stage labels move to the opposite side of a right-building queue, and the figure margin grows on whichever side now overflows
- New `flip_entity_icons` argument on `animate_activity_log` and `generate_animation`, plus an optional per-event `flip_icons` column on `EventPosition` / `event_position_df`, for mirroring entity icons (and a `custom_resource_icon`) horizontally - independently of `queue_direction`, so a layout is no longer constrained to whichever way an icon happens to face
    - `queue_direction` only ever mirrored the *layout*; this mirrors the glyph itself, achieved by prefixing a zero-width marker onto flipped icons' text and matching a CSS rule against it, since Plotly's scatter `text` has no rotation/flip property of its own. See `vidigi.utils.entity_icon_flip_css()` / `inject_icon_flip_css()`
    - The default `False` is a no-op: with no icon ever flipped, no marker is added and no CSS is injected
    - Per-event `flip_icons` (`EventPosition(..., flip_icons=True)`, or a `flip_icons` column on a hand-built / CSV `event_position_df`) overrides the animation-wide setting
    - The CSS is injected automatically (via IPython or Streamlit) whenever any icon actually resolves to flipped, so notebooks and Streamlit apps need nothing extra; embedding a figure another way (`fig.write_html()`, a hand-built page) needs `entity_icon_flip_css()` added explicitly - see the new example. Does not affect a static export via `fig.write_image()`, which renders in its own page
    - The `+ N more` / ASCII-gauge overflow icon is always exempt, even when the whole animation is flipped - mirrored text is unreadable, whatever entity icon it happens to be attached to
    - `custom_resource_icon`'s trace now carries one text entry per resource unit rather than a single string broadcast across all of them, so each can be flipped independently - the rendered animation is identical when nothing is flipped, but code inspecting `fig.data[-1].text` directly will now see a list rather than a bare string
- New `entity_icon_font` / `entity_icon_font_weight` arguments on `animate_activity_log` and `generate_animation`, for rendering entity icons (and a `custom_resource_icon`) in an icon font instead of emoji - `custom_entity_icon_list` then supplies that font's codepoints (or, for `"material-symbols"`, ligature names like `"directions_walk"`) instead of emoji
    - Emoji cap the available icon vocabulary and are colour fonts that ignore `textfont.color` entirely; an icon font opens up thousands of glyphs (Font Awesome, Bootstrap Icons, Material Symbols and any other CSS font-family are all accepted) and, being monochrome, is what makes the new `entity_colour_by` (below) visible
    - Ships three presets - `"font-awesome"`, `"bootstrap-icons"`, `"material-symbols"` - via `vidigi.utils.ICON_FONT_PRESETS`; the CSS is injected automatically (via IPython or Streamlit) exactly like `flip_entity_icons`, with `vidigi.utils.entity_icon_font_css()` / `inject_icon_font_css()` for embedding a figure another way. No font is bundled with vidigi - presets load from a CDN, so this needs network access at view time. Does not affect a static export via `fig.write_image()`
    - **Two confirmed Plotly bugs, worked around rather than merely documented:** a `textfont.family` value containing a standalone number - exactly the shape of "Font Awesome 6 Free", the vendor's own name - is silently dropped with no error (the built-in presets are pre-aliased under a digit-free name to route around this; a custom font name shaped the same way raises a clear `ValueError` instead of failing invisibly); and a browser's automatic "does this page need this webfont" detection does not reliably notice Plotly's SVG `<text>` icons, so the injected CSS also includes a small hidden element that reliably forces the font to load
    - The default `None` is a verified no-op; the `+ N more` / ASCII-gauge overflow icon is always left on the default font, whatever this is set to - a substituted glyph in place of the ASCII art would be worse than plain text
- New `entity_colour_by` / `entity_colour_map` / `show_entity_legend` arguments on `animate_activity_log` and `generate_animation`, for colouring entity icons by a column already on the event log (priority, pathway, acuity, ...), with an optional legend
    - Only visible together with `entity_icon_font`, since emoji ignore colour entirely; `entity_colour_map` maps specific values to specific colours, falling back to Plotly's default qualitative palette for anything uncovered
    - The default `None` is a verified no-op. Overflow rows always keep `overflow_text_color` and are never added to the legend, whatever category they would otherwise fall into
    - Implemented as one Plotly Express trace per colour category rather than a true per-point channel, since Plotly Express has none for `textfont.color` on an animated figure - **works around a third confirmed Plotly bug**: Express only creates a trace for a category actually present in a given frame, so a category with zero entities at some point in the animation (nobody of a given priority has arrived yet, say) would otherwise vanish from that frame - or from the whole animation, if that happened to be true of the first frame - rather than reappearing correctly once it does have entities
    - The empty placeholder trace this fills a missing category in with **surfaced a fourth confirmed Plotly bug**, this one specific to browsers rather than the frame data itself: a placeholder's trace-level `opacity` (harmlessly `0`, alongside already-null `x`/`y`, for the empty frame that creates it) is never reset back to `1` by a later frame that does have real content, since Plotly's frame animation only patches attributes a frame's own trace data explicitly sets, and a real trace never sets one. Left unfixed, a colour category (or `entity_icon_font` alone, via its own reserved `"_entity"` bucket) that happened to be empty in whichever frame first needed a placeholder would then render invisible for the rest of the animation, however many entities it later had - confirmed by inspecting the live DOM in a real browser (a trace `<g>` element stuck at `opacity: 0`), not just by reading frame data back in Python. Fixed by dropping that trace-level `opacity` from the placeholder - the null coordinates already draw nothing on their own
- New `resource_icon` field on `EventPosition` / `event_position_df`, overriding `custom_resource_icon` per event and able to name an image (a URL, local path, or `data:` URI) instead of a text glyph, drawn via `layout.images` at the resource's actual position
    - Closes a long-standing TODO for per-resource custom icons, for text glyphs and images alike. Resource icons are static across frames, so an image adds no per-frame cost
    - An image resource icon cannot be mirrored by `flip_entity_icons` - Plotly has no per-image transform, unlike text - so supply it pre-mirrored if needed
    - New `resource_image_size` argument sizes an image `resource_icon`, defaulting to `resource_icon_size` - kept independent of `gap_between_resources`, matching a text resource icon, so widening the spacing between resources doesn't also inflate the image
- New example notebook `examples/feat_custom_icons`, walking through all three features together
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
- Closed-set string arguments are now typed as literals, so editors offer the valid values and type checkers catch a typo before the call runs
    - `backend` and `simulation_time_unit` on `generate_animation` and `animate_activity_log`, `what` on `TrialLogger.get_event_duration_stat` and `plot_metric_bar`, and the new `snapshot_alignment` and `queue_direction`
    - The runtime checks are unchanged — annotations are not enforced, and a wrong value typed into a notebook still needs to raise
    - `time_display_units` is deliberately left untyped, since alongside its named options it accepts any custom strftime format
- New warning when an event log contains entities with no `arrival` event
    - These are silently absent from every frame, because presence is decided by comparing arrival and departure times and a missing arrival compares as `False` against every snapshot
    - Nearly always the signature of a log truncated to remove a warm-up period, so the warning names the entities, explains why they will not appear, and points at `warm_up`
    - Both shapes are caught: an entity left with a `depart` row but no `arrival`, and an entity still in the system whose remaining rows are all queue or resource events, which is absent from the arrival/departure pivot entirely
- New warning when `time_display_units` is coarser than the snapshot interval
    - The animation frame is the formatted time, so e.g. ten-minute snapshots displayed as `'d'` all carry the same label. Snapshots are merged, entities from different moments are drawn on top of one another, and plotly may produce no frames at all
    - This previously happened silently and returned a plausible-looking static figure
- `log_resource_use_start`/`log_resource_use_end` gain an explicit `event=` parameter, naming the specific step (e.g. `"treatment_begins"`) rather than the generic `"start"`/`"end"` default — needed to tell different resource-use steps apart in `resource_use_intervals`. This was already possible by passing `event=` as an undocumented extra keyword argument, so behaviour for every existing caller is unchanged
- New `logger=` parameter on `VidigiStore`/`VidigiPriorityStore`, for automatic `resource_use`/`resource_use_end` logging around resource acquisition and release, removing the need to bracket every `request()`/`get_direct()` call with `EventLogger.log_resource_use_start`/`log_resource_use_end` by hand
    - Purely opt-in: omitting `logger=` (the default) leaves every existing caller's behaviour unchanged, and passing `entity_id=` to any of these methods on a store with no `logger` does nothing
    - `request()`/`.get()` (the context-manager pattern) auto-log both events given `entity_id=`: `resource_use` once the item is actually granted, `resource_use_end` in `__exit__`, right before the item is returned - the latter fires unconditionally, whether or not an exception was raised during resource use, since Python always calls `__exit__` on the way out of the `with` block. `get_direct()`/`request_direct()` (start) paired with `put()`/`return_item()` (end) get the same treatment for the manual acquisition pattern
    - The start event is logged via a callback appended to the get event immediately after it's created, not synchronously when `request()`/`get_direct()` is called - `simpy.Event.succeed()` only schedules an event for processing, it doesn't invoke callbacks immediately, so this reliably captures the true grant time even when the request has to queue, and even along `VidigiPriorityStore`'s immediate-availability path where `.succeed()` already ran synchronously. A request later abandoned via `cancel_get()` never fires this callback, so reneging produces no phantom start log
    - Default event names are derived from the pool's `label` (`f"{label}_start"`/`f"{label}_end"`), falling back to the same `"start"`/`"end"` literals `log_resource_use_start`/`log_resource_use_end` themselves already default to when the pool has no label. Overridable per call: `start_event=`/`end_event=` on `request()`/`.get()`, `event=` on `get_direct()`/`put()`/`return_item()` (meaning "start" on the former, "end" on the latter, since each of those only logs one side). `pathway=` and arbitrary `**extra_fields` are forwarded to the logged event(s) the same way - the auto-logging equivalent of `log_resource_use_start`/`log_resource_use_end`'s own `**extra_fields`, so entity-level attributes (`acuity=3`, `arrival_mode="ambulance"`, ...) still reach the log as extra columns. Via `request()`/`.get()` the same values land on both the start and end event; `get_direct()`/`request_direct()` paired with `put()`/`return_item()` each take their own `**extra_fields`, for different fields per side or a value only known once the resource is released. Shown in the multi-server tutorial's auto-logging section
    - `unique_resource_id` is added automatically alongside `resource_id` whenever the pool was built with `label=`, matching the pattern `TrialLogger` already recommends for a collision-proof `by="resource"` breakdown
    - If a logger is configured but `entity_id` is omitted on a given call, auto-logging is skipped for that call, after a one-time `UserWarning` per store (not per call) - so a model can deliberately mix auto-logging with manual `EventLogger` calls without being warned on every one of the calls it wants to log itself
    - New `auto_log=` parameter (default `True`) on `request()`/`.get()`/`get_direct()`/`request_direct()`/`put()`/`return_item()` for both stores: pass `auto_log=False` to skip auto-logging for that one call *without* the missing-`entity_id` `UserWarning`, marking the omission as deliberate rather than a mistake. The intended use is keeping the `request()` context manager's automatic item return while writing the `log_resource_use_start`/`log_resource_use_end` calls by hand - e.g. to attach different fields to the start and end events, or a value only known once the resource is released. Per-call, so other requests on the same store keep auto-logging; a pool that is always logged by hand is still better served by not passing `logger=` at all. Shown in the multi-server tutorial's auto-logging section
    - Both stores are generic pools with no type constraint on what's `put()` into them; an item lacking `id_attribute` (e.g. one that slipped in via a more complex get/put pattern) degrades to `resource_id=None` in the auto-logged event rather than crashing the model with an `AttributeError` - `EventLogger`'s existing missing-`resource_id` warning still surfaces the problem
- `VidigiStore.put()` and `VidigiPriorityStore.put()`/`return_item()` now raise `TypeError` if handed a SimPy event object or `None` instead of a resource
    - The typical cause is a reneging or conditional-request branch passing the get/request event back into the pool instead of the item it yielded; the unfulfilled request then sits in the pool and is later handed to another entity, surfacing as an unrelated error far from the mistake
    - Only these two unambiguous cases are rejected - the stores stay generic pools with no constraint that contents be `VidigiResource`/`simpy.Resource` (see the `logger=` note above)
    - The `request()`/`.get()` context manager is unaffected: it only ever returns the exact item it was granted
- `VidigiResource` gains `id` and `unique_id` as read-write aliases of `id_attribute` and `unique_id_attribute`
    - `resource.id` reads and writes the same value as `resource.id_attribute`; either name can be used at construction (`VidigiResource(id=3)`) or after. `id_attribute` / `unique_id_attribute` keep working exactly as before - no deprecation, and every example and doc that reads `.id_attribute` is unaffected
    - `unique_id` is present only when the pool was built with `label=`, exactly like `unique_id_attribute` (accessing it otherwise raises `AttributeError`, and `hasattr` is `False`)
    - Passing both names of a pair with different values (`VidigiResource(id_attribute=1, id=2)`) raises `ValueError`
    - The tutorials and the `EventLogger`-based example notebooks now teach `.id` / `.unique_id`; `__repr__` already printed `VidigiResource(id=...)`, which the constructor now genuinely accepts. The pre-1.0 manual-`event_log.append` examples are left on `.id_attribute`
- New `extra_attributes=` argument on `populate_store`, `VidigiStore` / `VidigiPriorityStore` (constructor and `.populate()`), for giving a whole pool of resources custom attributes without building it by hand
    - `VidigiStore(env, num_resources=5, label="nurse", extra_attributes={"staff_type": "nurse"})` sets `resource.staff_type == "nurse"` on every resource in the pool; your model code can then read it (break scheduling, skill mix, ...) and it is otherwise inert
    - `VidigiResource` has always accepted arbitrary keyword attributes directly (`VidigiResource(id_attribute=1, staff_type="nurse")`); this only threads them through the bulk populate helpers, replacing the documented workaround of monkeypatching `VidigiResource.__init__`
    - Keys the pool manages itself - `id_attribute`, `id`, `label`, `unique_id_attribute`, `unique_id` - are rejected with a `ValueError` naming why
    - Defaults to `None`, a verified no-op; existing calls are unchanged
- New `plot_bgcolor` and `paper_bgcolor` arguments on `generate_animation` and `animate_activity_log`, forwarded verbatim to `fig.update_layout()`
    - `plot_bgcolor` sets the colour inside the axes, `paper_bgcolor` the surround behind the title, play button and timeline; both accept any CSS colour string (`"white"`, `"#f5f5f5"`, `"rgba(0,0,0,0)"`)
    - Saves reaching for `fig.update_layout(plot_bgcolor=...)` on the returned figure, which was already possible and still works
    - Both default to `None`, leaving the active Plotly template in control — a verified no-op, so existing calls are unchanged

### New metrics

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
- New `[stats]` optional extra (`pip install vidigi[stats]`, pulling in `scipy>=1.10`), and two new `vidigi.analysis` functions building towards confidence intervals across replications
    - `replication_means(durations, what=...)` reduces a per-entity durations frame (e.g. `event_durations`'s output) to one value per run - the independent unit any interval must be computed over
    - `mean_confidence_interval(values, ci_level=0.95)` computes a confidence interval over those replication-level values using Student's t with `n - 1` degrees of freedom, never a normal approximation - at `n=5`, a typical replication count, `z` is 29% too narrow. Only this function needs `scipy`; it is not imported anywhere else, and raises `ImportError` naming `pip install vidigi[stats]` if missing
    - Neither function accepts pooled per-entity observations disguised as replications: entities within a run are strongly serially correlated, so an interval computed that way can be roughly 30x too narrow. `replication_means` rejects entity-counting aggregations (`"count"`, `"unserved_rate"`, `"summary"`, ...) for the same reason - they answer "how many", not "what value", and are not meaningful re-averaged across runs
- New `vidigi.analysis.resource_use_intervals(event_log, ...)`, pairing `resource_use`/`resource_use_end` rows into one interval per bout of resource use — the first vidigi function able to answer "how busy was this resource"
    - Splits on `event_type`, not `event`, since a bout's start and end rows are named differently (e.g. `"treatment_begins"`/`"treatment_ends"`); the *start* row's event name is what identifies the step
    - An entity still holding a resource when the analysis window ends is **censored by default** (`unclosed="censor"`): its interval is clipped to the window end rather than dropped. Dropping understates utilisation exactly when it matters most, since entities still holding a resource at the end of a run are disproportionately those in a congested system — the same failure mode as the `plot_queue_size` bugs fixed earlier in 2.0.0. `unclosed="drop"` opts out
    - An end row with no matching start (a logging defect) is always dropped, with a warning
    - A log with no `resource_id` at all falls back to pairing on `(run, entity)`, with a warning — `busy_time`/`mean_in_use`/`utilisation` stay exact, only the per-unit breakdown is lost. A log with `resource_id` on *some* resource-use rows but not others raises, since pairing would otherwise silently cross entities using different physical units
- New `vidigi.analysis.resource_utilisation(event_log, by=..., ...)`, aggregating those intervals into busy time, mean-in-use and utilisation — always one row per run per group, matching `replication_means`'s "aggregation across runs is the plotting layer's job" convention
    - `by="step"` (default) or `"resource"` (one physical unit, capacity always `1`) — or `"run"`, pooling every step/unit together, where `capacity` is the **sum** of every pooled step's capacity (`NaN` if any is unresolved). Pooling more than one distinct step warns: a blended busy-time/utilisation figure across resource *types* (e.g. doctors and beds summed together) is rarely the number a capacity-planning question is asking, even when it is arithmetically well-defined
    - `by="resource"` assumes `resource_id` is unique across the *whole* log, not just within one step — two independent resource pools that each number their own units from 1 (e.g. two separate `vidigi.resources.VidigiStore`s) have their busy time silently summed as if they were one physical unit, which can push `utilisation` above `1` with no error beyond the generic over-capacity warning. Documented in the docstring; found while writing the `feat_trial_logger` example notebook against a six-resource-type model
    - `by="resource"` now also warns directly when it finds two bouts for the same `resource_id` genuinely overlapping in time within a run — impossible for one physical unit, and a sharper, root-cause-naming signal of an ID collision than the generic over-capacity warning alone. The grouping key itself is deliberately unchanged (still bare `resource_id`, not `(step, resource_id)`) — grouping by step too would silently split one physical resource legitimately reused across several step names into several rows instead, trading one silent failure mode for a worse one
    - New opt-in `label=` parameter on `vidigi.resources.VidigiStore` (`__init__`/`.populate()`), `populate_store()`, and `VidigiPriorityStore` (`__init__`/`.populate()`). When given, each resource additionally gets `.label` (the pool's label) and `.unique_id_attribute` (`f"{label}_{index}"`, unique across pools when every pool is given a distinct label) — `id_attribute` itself is completely unchanged, since `vidigi.prep`'s animation positioning depends on it staying a small per-pool index. Log `unique_id_attribute` under a separate field name (e.g. `unique_resource_id`, via `log_resource_use_start`/`_end`'s existing `**extra_fields`) and pass `resource_col_name=` to `resource_utilisation`/`resource_use_intervals` to get a collision-proof `by="resource"` breakdown. Omitting `label` is a verified no-op on the resources produced, but now emits a `DeprecationWarning` — `label` is planned to become mandatory at vidigi 3.0, recorded in `pending_fixes.md`
    - Fixed, found by an independent review of the above: the missing-`label` `DeprecationWarning`'s `stacklevel` under-counted by one for `VidigiStore`/`VidigiPriorityStore`'s constructor path (`__init__` calls `.populate()` internally, adding a frame `populate_store()` and a direct `.populate()` call don't have), so it always attributed to the internal `.populate()` call inside `resources.py` rather than the caller's `VidigiStore(...)` line. This was not just a cosmetic mislabelling: Python's default warning filter suppresses repeats sharing the same `(message, category, module, lineno)`, so two separate unlabelled pools constructed via `VidigiStore(...)`/`VidigiPriorityStore(...)` both collapsed onto that one internal line and only warned **once** between them - fixing the first pool a reviewer's warning pointed at left the second silently unflagged
    - New check: constructing two resource pools with the same `label` on the same `simpy.Environment` now warns, since it reproduces the exact `resource_id` collision `label=` exists to prevent, silently, with no other safety net unless the two pools happen to be busy at the same instant. Deliberately scoped per environment rather than globally - reusing a label across separate replications (a fresh `simpy.Environment` per run) is normal and must not warn, or every run after the first would falsely flag itself
    - Fixed a related bug this surfaced: `resource_use_intervals`'s `resource_col_name=`/`entity_col_name=`/`run_col_name=` pointing at a column other than the canonical default (e.g. `resource_col_name="unique_resource_id"` on a log that also carries a literal `resource_id` column, logged separately for animation) used to raise `ValueError: The column label 'resource_id' is not unique`, since the internal rename produced two identically-named columns. The rename now drops any pre-existing column sharing a target name first
    - **BREAKING:** `TrialLogger.get_resource_utilisation()`, `TrialLogger.plot_resource_utilisation()` and `TrialLogger.plot_resource_utilisation_over_time()` gained the same `resource_col_name=` parameter, now defaulting to `None`: this resolves to `"unique_resource_id"` if that column is present on the trial's log, else `"resource_id"` (deliberately `None` rather than a magic string like `run_col_name`'s existing `"auto"` sentinel elsewhere in this codebase - `resource_col_name` has no pre-existing meaning for `None` to collide with, so there is no ambiguity with a log that genuinely has a column literally named `"auto"`). So a model built the recommended way - `VidigiStore(..., label=...)`, logging `unique_resource_id` alongside `resource_id` - gets a collision-proof `by="resource"` breakdown from `TrialLogger` with **no extra argument anywhere**, while a model with no `unique_resource_id` column at all behaves exactly as before. Pass an explicit column name to override. One real edge case changes results for a caller who changes nothing: a trial where `unique_resource_id` is present on *some* resource-use rows but not others (e.g. only part of a model's logging was updated to the new pattern) used to succeed under the old hard-coded `resource_id` default; it now raises `ValueError`, since `resource_use_intervals` already refuses to pair on a partially-populated column rather than risk silently crossing entities using different physical units - `resource_col_name="resource_id"` restores the old behaviour explicitly. All three methods also gained a `**kwargs` passthrough for the remaining column-name family (`entity_col_name`, `time_col_name`, `event_type_col_name`, `event_col_name`, `run_col_name`) - previously unreachable, and on `plot_resource_utilisation_over_time` entirely absent - closing a gap an independent review found: the commit that first added `resource_col_name=` to two of these three methods left the third behind on the same day, which is exactly the kind of drift hand-threading each parameter individually invites. The free `vidigi.analysis`/`vidigi.plots` functions are deliberately left untouched - explicit `resource_col_name="resource_id"` by default, no auto-detection - since they are meant to work on any log, not just one produced by `EventLogger`/`VidigiStore`
    - `mean_in_use` needs no capacity at all (`busy_time / window_length`) and is always populated; `utilisation` additionally divides by capacity and is `NaN` wherever that is unresolved. A resolved `utilisation` over `1` always warns — this definition of utilisation can never legitimately exceed `1`, so it is a live signal of a resolution or logging problem worth surfacing immediately rather than only visually once a plotting layer exists
    - A `(run, group)` combination absent from a specific run but present in another (a resource that happened not to be used that run) reports a genuine `busy_time` of `0` there, not a missing row — the same "real zero" convention `queue_size_over_time` already uses. This also covers `by="resource"` when `resource_id` is missing from the whole log: rather than the per-unit breakdown collapsing to zero *rows*, it reports one pooled row per run, with a warning
- New `_resolve_resource_capacities`, resolving a `{step: capacity}` mapping from **four routes**, in precedence order: an explicit `resource_capacities={step: count}` dict; `scenario=` with `resource_map={step: "attribute_name"}`; `scenario=` with `event_position_df=` (reusing the `resource` column already used by the animation functions); or `capacity="infer"`, which estimates each step's capacity as the number of distinct `resource_id`s seen for it — a **lower bound** (a never-used unit is invisible), so it always warns
    - Passing nothing at all is not an error — `utilisation` is simply `NaN` throughout, with `mean_in_use` still fully populated
    - `scenario` given without one of the three ways to use it raises, naming all three with an example each; a `resource_map`/`event_position_df` naming an attribute `scenario` does not have raises `AttributeError` naming the attribute, the step, and every available attribute on `scenario`
    - The `event_position_df` route reuses a new shared helper, `vidigi.utils._resource_map_from_event_position_df`, extracted from `animation.py`'s pre-existing resource-icon lookup so the two cannot drift on what counts as "this event has a resource". The extraction is behaviour-preserving — every existing animation test passes unchanged, which is its proof
- New `TrialLogger.get_resource_utilisation()`, a thin delegator to `vidigi.analysis.resource_utilisation` called on the trial's combined dataframe
- New `vidigi.analysis.resource_occupancy_over_time(event_log, ...)`, the resource equivalent of `queue_size_over_time` — how many units of each step were busy at regular snapshots, across every run
    - Deliberately **not** built on `reshape_for_animations` — occupancy is interval containment ("was this bout still open at this snapshot?"), a different question from `reshape_for_animations`' "most recent event per entity wins". Computed exactly via a +1/-1 sweep over `resource_use_intervals`'s bouts (sorted, cumulatively summed, then looked up onto the snapshot grid with `searchsorted`) rather than a per-snapshot membership scan
    - A bout is occupied on the half-open interval `[start, end)` — a unit freed exactly at a snapshot time is not counted as busy there. Always censors an unclosed resource use through to the window end (there is no `unclosed` parameter), for the same reason `resource_use_intervals` censors by default
    - A `(run, step)` combination with nothing in use at a snapshot reports a genuine `count` of `0`, not a missing row, matching `queue_size_over_time`'s convention
- New `vidigi.analysis.welch_moving_average(series_by_run, window, method=...)`, vidigi's first tool for choosing `warm_up=` rather than just applying it — see `plot_warm_up_diagnostic` under New plots for how it's visualised
    - `method="welch"` (the default) is Welch's (1983) moving-average procedure, as described in Law, *Simulation Modeling and Analysis*: replications are ensemble-averaged at each index, then smoothed with a symmetric window. The first `window` points, where a full-width window would run off the start of the series, use the narrower symmetric window that actually exists (`2i - 1` points) rather than `NaN` — the detail a `pandas.rolling(center=True)` call gets wrong — and the last `window` points, which have no full-width neighbourhood at all, are simply not returned, so the output is `window` points shorter than the input. `method="cumulative"` is the plainer expanding mean of the ensemble average instead — simpler, needs no window, but each new point only shifts it by `1/i`, so it decays a biased early transient out far more slowly than Welch's fixed-width window does; the risk is not that this curve is rougher, but that it is *smoother* in a way that can look settled long before the series actually has
    - An independent OR-specialist review confirmed the shrinking-edge/truncated-tail math and the no-automatic-selector decision against Law & Kelton's own treatment, corrected the "noisier" mischaracterisation above, and found a real gap this release also closes: `series="duration"`'s reading was in *entity count*, but nothing consuming duration data had a `warm_up=` to apply it to. See the new `event_durations` parameter directly below
    - New `method="none"`: the ensemble average with no smoothing applied at all - a further step beyond `method="cumulative"` (the "time series inspection" technique the DES RAP book, Heather et al. 2026, actually demonstrates - see that method's own entry). Noisier than either other method by construction, since nothing here reduces the within-replication variance the ensemble average didn't already remove - useful specifically when you'd rather see that noise than have it smoothed away. Drawn the same way `show_ensemble`'s reference line already was, so `show_ensemble` is a no-op under `method="none"` rather than drawing the identical line twice
    - A citation-correctness review found this had misattributed the DES RAP book's demonstration to `method="none"` - the book's own text explicitly plots a cumulative mean ("we plot the cumulative mean... look for the point where this smoothes out and stabilises"), which matches `method="cumulative"`, not the fully unsmoothed `method="none"`. The same review found the Robinson citation's year was wrong: no primary bibliographic source (Wiley, AbeBooks, Internet Archive, ACM Digital Library) shows a 2007 printing of *Simulation: The Practice of Model Development and Use* - the first (Wiley) edition is dated 2004. Both corrected throughout the docstrings and the example notebooks; `method="cumulative"`'s docstring now carries the DES RAP citation instead
- New `warm_up` parameter on `vidigi.analysis.event_durations`, threaded through everything built on it — `plot_duration_distribution`, `plot_metric_bar`, and `TrialLogger.get_event_durations()`/`.get_event_duration_stat()`/`.plot_duration_distribution()`/`.plot_metric_bar()` — so a cutoff read off `plot_warm_up_diagnostic(series="duration")` has somewhere to go
    - A pairing is excluded when its `first_time` is before `warm_up` — discarded by when it *started*, the standard truncation rule for duration data (Law & Kelton), not by whether it later straddles the cutoff. This is a genuinely different rule from `resource_use_intervals`/`resource_occupancy_over_time`'s `warm_up`, which censors/clips a bout mid-interval rather than excluding it outright — a duration is one atomic observation, not something that can be partially inside the window
    - Filters per *pairing*, not per entity: with `match="occurrence"`, an entity's early occurrence during warm-up is excluded while a later occurrence of the same entity afterwards is kept
    - A pairing with no `first_time` at all (a `second_event` with no matching `first_event`) is never excluded by `warm_up`, since there is no time to compare it against
    - The default of `0` is a verified no-op. On `plot_duration_distribution` (both the free function and `TrialLogger`'s), it reaches `event_durations` purely through the existing `**kwargs` column-name passthrough, with no new named parameter needed; `plot_metric_bar` (both) gained an explicit `warm_up=` parameter instead, since its `**kwargs` is plotly passthrough, not column-name passthrough — the one function in this module where that distinction matters
- New `vidigi.analysis.replication_precision(values, ci_level=, deviation_threshold=)` and `TrialLogger.get_replication_precision(...)`, the counterpart to `welch_moving_average` for "how many replications is enough" rather than "how much warm-up to discard"
    - For k = 1…n replications, in the order given (deterministic — `run_number` order, since a cumulative diagnostic only means "as replications accumulate" walked through generation order), reports the cumulative mean, its confidence interval (`mean_confidence_interval`) computed from only the first k replications, and the relative half-width (`deviation = half_width / abs(cumulative_mean)`) — the standard precision diagnostic (Hoad, Robinson & Davies, 2010) for deciding when enough replications have been run
    - `stays_below_threshold` marks row k `True` only if `deviation` is defined and stays at or under `deviation_threshold` (default 5%) from k *all the way to n* — deliberately "stays below", not "first drops below": a noisy early curve can dip under the threshold once by chance and rise again, which would be a spurious recommendation. The smallest `n_replications` with `stays_below_threshold=True` is the recommended minimum replication count; always `False` at k=1, where deviation is undefined
    - Scoped to duration event-pairs only (`first_event`/`second_event`, matching `plot_metric_bar`'s shape) rather than also covering queue/occupancy series the way `plot_warm_up_diagnostic`'s `series=` does — those don't have a single natural per-replication scalar without picking a snapshot rule first, so extending this to them is left for a future release rather than guessed at now
    - An independent OR-specialist review (of this still-unreleased feature) found `deviation` was computed as `half_width / cumulative_mean` with no `abs()` — harmless for the naturally-positive duration metrics this function is scoped to, but for a metric with a negative mean (e.g. a before/after difference passed through the same `values` parameter) the ratio came out negative and trivially satisfied `<= deviation_threshold`, so `stays_below_threshold` could flag `True` on a wildly imprecise interval. Fixed before release, no caller-visible change for any positive-mean metric. The same review also prompted a clarification now in the docstring and the example notebook: `stays_below_threshold` is a property of the batch of replications actually supplied, not an open-ended guarantee — intended as "read this diagnostic with judgement," matching the same stance already taken for `welch_moving_average`'s deliberate lack of an automatic selector. A follow-up check against the cited paper's primary text found a second inaccuracy in that same clarification as first written: it claimed the paper makes no correction for repeatedly testing at every k, but Hoad, Robinson & Davies (2010) address exactly this "early convergence" risk with their own "look ahead" (`kLimit`) mechanism, empirically shown in the paper to eliminate the coverage failures a naive first-crossing rule produced. Corrected to describe `stays_below_threshold` accurately as a simpler, unbounded stand-in for that same idea — not a literal implementation of `kLimit`, and, like the paper's own procedure, validated only empirically rather than derived as a formal statistical correction
- New `vidigi.analysis.entity_metric_by_arrival(event_log, first_event, second_event, arrival_event=, match=, ...)` and `TrialLogger.get_entity_metric_by_arrival(...)` — a per-entity duration (`event_durations`'s own output) joined with each entity's arrival time, for spotting whether a metric drifts depending on when the entity arrived - a non-stationary arrival process or a time-of-day/load effect, for example (see New plots for the matching chart)
    - `arrival_event` is deliberately independent of `first_event`/`second_event` — it can coincide with `first_event` (e.g. measuring time from arrival itself), but does not have to; this answers a different question from "how long did this specific interval take" ("does this duration vary depending on when the entity showed up at all")
    - The arrival lookup always uses the entity's *earliest* occurrence of `arrival_event`, regardless of `match` — an entity ordinarily arrives once, so `match` only ever governs how `first_event`/`second_event` are paired, never the arrival lookup. The join keying the two frames together is on `(run_number, entity_id)` only, not `occurrence`, so every occurrence-row for one entity under `match="occurrence"` shares the same `arrival_time`
    - An entity with a complete duration pairing but no `arrival_event` recorded in that run gets `arrival_time = NaN`, not a dropped row — matching `event_durations`'s own `keep_incomplete` philosophy

### New plots

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
    - New-function style, per the plans for the rest of the 2.0.0/2.1.0 plotting work: no `interactive=`, always returns a figure; `**kwargs` forwards to `vidigi.analysis.event_durations` for column-name overrides, not to a plotly call - there's no single call to forward general styling to, since `go` builds several traces by hand. Style the returned figure directly, or pass `title=`
- `plot_metric_bar` (both `vidigi.plots.plot_metric_bar` and `TrialLogger.plot_metric_bar`) gains `across`, `error_bars`, `ci_level` and `show_runs`, for putting an uncertainty interval on a bar chart for the first time
    - `across="entities"` (the default, unchanged) pools every entity's duration into one statistic per bar, exactly as every prior release did
    - `across="runs"` computes the chosen statistic separately within each run, then draws the mean of those per-run values - the number an `error_bars="ci"` interval is actually about
    - `error_bars`: `"ci"` (needs `scipy`), `"sd"`, `"se"`, or the asymmetric `"range"`/`"iqr"`, computed over the per-run values. Requires `across="runs"` - an interval over replication means attached to a bar pooled over entities would be internally inconsistent, since entities are correlated within a run and runs are the independent unit
    - `show_runs=True` overlays each run's individual value as a point on top of its bar; also requires `across="runs"`
    - Internally, `TrialLogger.plot_metric_bar` is now a thin delegator to the new `vidigi.plots.plot_metric_bar`, operating on the trial's combined dataframe rather than calling `get_event_duration_stat` per pair directly
    - `**kwargs` keeps forwarding to `plotly.express.bar` unchanged - the one function newly moved into `vidigi.plots` that is *not* switched to column-name passthrough, since the example notebook already relies on `title=`/`width=` reaching the chart
- New `vidigi.plots.plot_resource_utilisation(event_log, by=..., metric=..., ...)` and `TrialLogger.plot_resource_utilisation(...)`, a bar chart of resource utilisation with one bar per group across runs
    - Thin wrapper over `resource_utilisation` — that function already returns one row per run per group, so the bar height is just their mean and the error bar is built from the same per-run values, exactly as `plot_metric_bar`'s `across="runs"` does for durations. The error-bar spread computation (`"ci"`/`"sd"`/`"se"`/`"range"`/`"iqr"`) is shared with `plot_metric_bar` via an extracted helper rather than duplicated
    - `metric="utilisation"` (the default) falls back to `"mean_in_use"`, with a warning and a note in the title, if no capacity was resolved for any group — `mean_in_use` needs no capacity at all, so this avoids drawing an all-`NaN` chart when the caller has not supplied one
    - `error_bars="ci"` and `show_runs=True` are the defaults here, unlike `plot_metric_bar` — this function is new in 2.0.0, so has no pre-existing bare-bar behaviour to preserve
    - A dashed line is drawn at `y=1.0` when the plotted metric is (or falls back to being) `"utilisation"`, since a value above it is always diagnostic of a mis-resolved capacity or overlapping `resource_use` intervals
    - `by="run"` draws a single bar labelled `"All resources"`; `sort_by="value"` orders bars by descending value instead of by group
- New `vidigi.plots.plot_resource_utilisation_over_time(event_log, as_proportion=..., ...)` and `TrialLogger.plot_resource_utilisation_over_time(...)`, the resource equivalent of `plot_queue_size`
    - Thin wrapper over `resource_occupancy_over_time`. Per-run traces at `opacity=0.2` with a bold mean on top, faceted by step when more than one is present — the same visual language as `plot_queue_size`
    - Traces use `line_shape="hv"`, since occupancy is a step function — linear interpolation between snapshots would draw fractional resource counts that never existed
    - `as_proportion=True` divides each step's count by its resolved capacity. Unlike `plot_resource_utilisation`, there is no `mean_in_use`-style fallback here: a partially-`NaN` proportion trace is more misleading than an error, so a step with no resolvable capacity raises naming it
- New `vidigi.plots.plot_warm_up_diagnostic(...)` / `TrialLogger.plot_warm_up_diagnostic(...)`, built on `welch_moving_average` (see New metrics) to visualise where to set `warm_up=`
    - Deliberately no automatic warm-up-length selector: Welch's procedure is explicitly a visual one, and a flatness threshold returns a confident number that is wrong on any series with slow drift, silently discarding the wrong amount of data with no signal anything went awry. `plot_warm_up_diagnostic` overlays several `windows=` values (default `(5, 10, 20)`) so the point where they agree can be read by eye
    - `plot_warm_up_diagnostic`'s `series=` selects what's diagnosed: `"queue"` (via `queue_size_over_time`, needs `event=`), `"occupancy"` (via `resource_occupancy_over_time`, needs `event=`), or `"duration"` (via `event_durations`, needs `first_event=`/`second_event=`, plotted against arrival order rather than a time axis, since a per-entity duration series has no snapshot grid)
    - New-function style, matching the rest of 2.0.0's plotting additions: no `interactive=`, always returns a figure; `**kwargs`/`**col_kwargs` forwards column-name overrides to whichever underlying `vidigi.analysis` function `series` selects, not to a plotly call
    - New `show_runs=` on `plot_warm_up_diagnostic`/`TrialLogger.plot_warm_up_diagnostic` (default `False`), overlaying every individual replication's own raw series at `opacity=0.2` - the fuller picture the DES RAP book's own figures show alongside its pooled line. Unlike `plot_queue_size`/`plot_resource_utilisation_over_time`'s equivalent (`show_all_runs`), every run shares one legend entry ("individual runs") rather than getting its own - with a realistic replication count, a full per-run legend here would swamp the `windows=`/`method` entries that are the actual point of this plot. Each run is drawn at its own full length, not truncated to the shortest run the way the summary trace(s) are - most visible for `series="duration"`, where replications routinely complete different numbers of pairings
- New `vidigi.plots.plot_replication_analysis(...)` and `TrialLogger.plot_replication_analysis(...)`, visualising `replication_precision`'s recommendation — the counterpart to `plot_warm_up_diagnostic`
    - `plot_replication_analysis` draws the cumulative mean and its CI band, plus (`show_deviation=True`, the default) a second stacked panel underneath showing `deviation` against a dashed reference line at `deviation_threshold`. The figure title reports the recommended replication count, or states plainly that deviation never converged within the replications available
    - New `marker_size=`/`line_width=` (defaulting to the previous hard-coded 6/3, a verified no-op) on the cumulative-mean and deviation traces — the fixed default marker size overlaps into a solid, unreadable smear once a trial runs into the hundreds of replications, found while extending the example notebook to demonstrate an actually-converging case
- New `vidigi.plots.plot_metric_vs_arrival_time(event_log, first_event, second_event, arrival_event=, colour_by=, rolling_window=, rolling_time=, warm_up=, marker_size=, line_width=, ...)` and `TrialLogger.plot_metric_vs_arrival_time(...)` — see New metrics for the underlying `entity_metric_by_arrival`
    - `colour_by="run"|"pathway"|None` groups the scatter, matching `plot_duration_distribution`'s existing `split_by`
    - `rolling_window`/`rolling_time` are mutually exclusive smoothing strategies drawn over the (irregularly-spaced) scatter as a single bold trend line — a count-based and a genuine time-window moving average respectively, both symmetric and shrinking at *both* edges rather than dropping points there (unlike `welch_moving_average`'s Welch method, every entity needs to stay visible on this chart). When `colour_by` is also set, the trend line is still one line pooled over every group, not one per group — matching the existing "faint per-group traces + bold pooled mean" visual language already used by `plot_resource_utilisation_over_time`/`plot_queue_size`
    - `warm_up` excludes points by `arrival_time` — not by `first_time`, unlike every other `warm_up` in this codebase — since this chart's x-axis *is* arrival time; filtering by `first_time` instead could draw excluded points to the left of the stated cutoff whenever `arrival_event != first_event`. Applied before any rolling average, so excluded points cannot leak into the smoothing near the boundary. The default of `0` is a verified no-op
- New `return_fig=` on `EventLogger.plot_entity_timeline`, the last of vidigi's plotting functions that only ever displayed a chart and returned `None`
    - `return_fig=False` (the default, unchanged) still calls `fig.show()` and returns `None`, exactly as before. `return_fig=True` returns the figure instead, without calling `fig.show()`, for further styling or export (e.g. `fig.write_image(...)`)
    - The default will flip to `True` at vidigi 3.0, at which point the method stops calling `fig.show()` itself — noted in the docstring now so existing script callers relying on the display side-effect are not broken without warning

### New examples

- New `examples/v2_release_additions/v2_release_additions.ipynb`, a tour of everything above: `event_durations`/`get_event_durations`, resource utilisation (`resource_use_intervals`, `resource_occupancy_over_time`, `resource_utilisation`'s four capacity-resolution routes, `plot_resource_utilisation`/`plot_resource_utilisation_over_time`), `plot_entity_timeline`'s new `return_fig=`, and `VidigiStore(..., logger=...)` auto-logging - none of which had a working code example anywhere in the repo before this. `plot_duration_distribution`, `plot_metric_bar`'s `across=`/`error_bars=`, the warm-up/replication-count/metric-vs-arrival-time diagnostics, and `entity_icon_font`/`entity_colour_by`/`resource_icon` get a short, real demonstration with a link to their existing dedicated notebook (`feat_trial_logger.ipynb`, `feat_warm_up.ipynb`, `feat_replication_analysis.ipynb`, `feat_metric_vs_arrival_time.ipynb`, `feat_custom_icons.ipynb` respectively) rather than being re-explained from scratch - here, colouring patients by which of the four treatment cubicles (`resource_id`) is treating them, the same physical units `resource_utilisation` measured earlier in the same notebook
    - Reuses the same single-resource clinic model as the warm-up/replication/arrival-time notebooks, so every number is directly comparable - including an independently-derived ~78% cubicle utilisation matching the figure `feat_warm_up.ipynb` already quotes
    - Demonstrates that `VidigiStore(..., logger=...)` auto-logging and manual `log_resource_use_start`/`log_resource_use_end` calls produce byte-identical `resource_use_intervals` output for the same model and seed, once `limit_duration=` is pinned explicitly on both sides - `resource_use_intervals` resolves its analysis window's end from the latest time in whichever log it's given, which differs between a single run's own log and a multi-run trial's combined log
- `vidigi.analysis` and `vidigi.plots` gain their own `_quarto.yml` reference sections (*Analysis Functions*, *Analysis Plots*) - all 18 functions added across 2.0.0 previously had no API reference page at all, despite being documented in every docstring; only `TrialLogger`'s delegating methods were reachable via the site
- New `examples/feat_animation_warm_up/feat_animation_warm_up.ipynb`, demonstrating `reshape_for_animations`/`animate_activity_log`'s `warm_up=`/`snapshot_alignment=` - a top-of-changelog 2.0.0 feature with no worked example anywhere in the repo before this, despite every other `warm_up=` (the `vidigi.analysis` one, `generate_dfg`'s) already having one
    - Shows the naive-filtering trap directly: filtering the event log by time before reshaping triggers the new "entities with no arrival event" warning and drops every one of the patients genuinely still present at the cutoff from the animation entirely (0 of 7, in the notebook's own run), where `warm_up=` on the unfiltered log keeps all of them, present in the very first frame
    - Also demonstrates `snapshot_alignment="warm_up"` vs `"run_start"` producing different first-frame times when `warm_up` isn't a multiple of `every_x_time_units`
- `examples/feat_process_maps/process_maps.ipynb` gains a short demonstration of `generate_dfg`'s `warm_up=`, with real before/after node counts (`arrival` drops from 132 to 113 once the first 100 time units are excluded) and a note on how this `warm_up=` differs from the animation functions' - a plain time-based row filter, not presence-aware trimming, which is fine here since `discover_dfg` builds each case's edges from its own consecutive rows rather than reconstructing presence from arrival/departure rows the way the animation functions do
- New *Customising Animations* page in the site navbar (`vidigi_docs/customising_animations.qmd`), a single reference for every appearance argument to `animate_activity_log` / `generate_animation` grouped by what it changes (background colour and image, stage labels, icons, spacing and wrapping, playback, crowded-step gauges, setup mode), plus the "the figure is just Plotly, edit it directly" escape hatch. These were only discoverable by reading the full parameter list in the docstrings before

### Fixes

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
    - `animate_activity_log` now also forwards `event_type_col_name` to `generate_animation`, which builds the queue-position hover text by testing this column for `"queue"`. A custom event type column reached the reshape and positioning steps but not this one, so the call died with `KeyError: 'event_type'`
    - If you use the default column names, nothing changes
- `backend` now matches case-insensitively for every spelling
    - The plotly express branch lowercased its input and the graph objects branch did not, so `backend="EXPRESS"` was accepted while `backend="GO"` was rejected as invalid
    - The error message also listed only two of the four graph objects spellings, so `"plotly graph objects"` and `"plotly go"` worked but were never advertised
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
- A minimal `animate_activity_log(event_log=..., event_position_df=...)` call no longer clips its auto-generated stage labels or edge-of-layout icons
    - With no `override_x_max` / `override_y_max` the axis range was derived purely from event anchor points, leaving only `0.25 * x.max()` of space to the right of the last anchor — not enough for a label like `"Being Seen By Nurse"`, which was chopped at the axis. Queue and resource icons drawn left of a low-x anchor (including the `wrap_queues_at` offset) were clipped at `x = 0` the same way
    - The figure margin now expands to fit the longest label and the furthest icon, and `cliponaxis` is disabled on the content traces so they render into it. The data ranges are untouched, so node spacing, `override_x_max` alignment and background images are unchanged; margins only ever grow, so an animation whose labels already fit is identical
    - `override_x_max` / `override_y_max` remain the escape hatch for a layout the auto-sizing gets wrong
- `custom_hover_data` is no longer modified in place
    - The list passed in was appended to directly, so it grew by an entry on every call and eventually referenced the same column twice
    - The resource column is now only offered when the event log actually contains one
- **BREAKING:** `custom_hover_data` now requires a matching `hover_text_entity`. Callers who never passed `custom_hover_data`, or who already paired it with their own `hover_text_entity` (as the docstrings recommend and every example does), see no change — only the broken combination now raises instead of returning a figure with garbled hover
    - The default hover template indexes `customdata[0..5]` by fixed position (entity id, time, snapshot time, label, time in event, queue position). Passing `custom_hover_data` replaces that list wholesale, so the default template then read the wrong columns — or ran off the end of a shorter list — and rendered broken hover with no error
    - Supplying `custom_hover_data` while leaving `hover_text_entity` at its default now raises `ValueError`, which names the six default columns so a caller who wanted those plus extras can rebuild the template
- Invalid `backend` and `time_display_units` values now raise `ValueError` carrying the intended guidance
    - Both were raised as bare strings, which Python rejects with `TypeError: exceptions must derive from BaseException`, so the message explaining the valid options never reached the user
- An unrecognised `simulation_time_unit` now raises `ValueError` listing the valid units, instead of `UnboundLocalError`
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

### Deprecations

- `minimize_output_df` is deprecated and remains inert
    - It has never had any effect: the loop meant to implement it discarded the result of `.drop()`, so the documented default of `True` was always a no-op
    - Making it work now would change the output of every existing caller, including removing the `run` column, so the behaviour is deferred to 3.0
    - Passing it emits a `DeprecationWarning`; callers who never passed it are unaffected

### Testing

Test coverage grew from 31 to 780 tests, concentrated on the parts of the pipeline where a
mistake changes what the animation *shows*, or what the reported numbers *say*, rather
than raising an error.

- `reshape_for_animations` is now asserted by value rather than by shape: which entities are present at each snapshot, which event each is shown at, queue ordering, exit step timing, and the `step_snapshot_max` cap
- `generate_animation_df` gained its first dedicated coverage: entity and resource positions, queue wrapping, icon assignment, and the overflow placeholder
- `animation.py` gained its first dedicated coverage: frame count and ordering, animation timings, hover configuration, resource markers, every time display format, background image embedding, and the error paths
- The auto-layout margin fix is covered by value: `cliponaxis=False` reaching every content trace and every frame trace, the right margin growing only when a stage label overflows the last anchor (and not at all when labels are hidden), the left margin engaging only when queue icons cross `x = 0`, and a plain animation leaving both margins and the data range untouched — the margin computations each mutation-proven
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
- `resource_occupancy_over_time` is covered against the same hand-computed `resource_use_loggers` fixture as `resource_use_intervals`, with the full per-run step-function array asserted (not sampled points): the half-open `[start, end)` convention is proven to fail if the snapshot lookup were changed from a right- to a left-biased search, unclosed resource use is confirmed occupied through to the window end rather than vanishing or spanning the whole window, and a log with no resource-use events at all returns an empty frame with the correct columns rather than raising
- `plot_resource_utilisation` and `plot_resource_utilisation_over_time` are covered as free functions against the same fixture: the bar-chart mean and CI half-width against the published Student's t value for `n=2`, the full `{resource_id: value}` mapping for `by="resource"` (not sampled entries), the `by="run"` single-bar case, the `metric="utilisation"` → `"mean_in_use"` fallback and its warning (mutation-proven), the `y=1.0` line appearing only for a resolved `utilisation` metric (mutation-proven), `sort_by="value"` reordering bars away from their natural (alphabetical) group order — chosen specifically so the two orders disagree, since a fixture where they happen to coincide would pass whether or not sorting actually ran — the full per-snapshot occupancy curve and `line_shape="hv"`, and `as_proportion`'s division by capacity (mutation-proven) and its missing-capacity error. `TrialLogger`'s two delegating methods are each checked to reproduce the same hand-computed figures
- `by="resource"`'s new overlap warning is covered against a purpose-built fixture of two entities genuinely overlapping on one `resource_id` (mutation-proven to fail if the check were disabled), a fixture proving the exact half-open boundary — a bout starting exactly when the previous one ends must *not* warn (mutation-proven to fail if the comparison were `<=` instead of `<`) — and a fixture proving the grouping key is unchanged: one physical resource legitimately reused across two different step names, non-overlapping, still returns exactly one row rather than being split per step
- The new opt-in `label=` on `VidigiStore`, `populate_store()` and `VidigiPriorityStore` is covered for a true no-op at the default (`id_attribute` unchanged, and neither `.label` nor `.unique_id_attribute` present at all — not merely `None`), that omitting it now emits a `DeprecationWarning` and that passing it suppresses that warning, the exact `unique_id_attribute` value shape for a single pool, that two differently-labelled pools produce disjoint `unique_id_attribute`s while `id_attribute` itself still (correctly) collides between them, and an end-to-end test proving `label=` actually fixes the motivating problem: the same two-pool collision that makes `resource_utilisation(by="resource")` warn on the default `resource_id` column no longer does when pointed at `unique_resource_id` instead
- Found and fixed while adding the above: `resource_use_intervals`'s column-renaming raised `ValueError: The column label 'resource_id' is not unique` whenever `resource_col_name=` (or `entity_col_name=`/`run_col_name=`) pointed at a column other than the canonical default while that default name was *also* present in the log — exactly the situation of logging both `resource_id` (for animation) and a separate collision-proof ID (for analysis) side by side, which is the whole point of the new `label=` option. Mutation-proven regression test added
- The `stacklevel` fix is covered by constructing two unlabelled pools with an explicit `"default"` warning filter (not pytest's own `"always"`, which would mask the bug) and asserting both warn — mutation-proven to collapse to one warning if the fix were reverted — plus a direct check that the warning's `filename` is the test file, not `resources.py`
- The same-label collision check is covered for warning when two pools share a label on one `simpy.Environment` (mutation-proven for all three pool-construction call sites), for *not* warning when the same label is reused across two different environments — the replication-safety case, mutation-proven to produce a false positive if the check were made global rather than per-environment — and for not warning between two differently-labelled pools on the same environment
- `resource_col_name=None` (auto-detect) is covered on all three `TrialLogger` methods: a fixture where `unique_resource_id` is present and genuinely disagrees with `resource_id` (mutation-proven to fail if the auto-detection were removed), that an explicit `resource_col_name=` still overrides the default, that a log with no `unique_resource_id` column falls back to exactly the pre-existing behaviour, and — for `plot_resource_utilisation_over_time`, which had no `resource_col_name` at all before this — that the parameter genuinely reaches the underlying function (mutation-proven) via the fallback warning naming a deliberately-wrong column, plus that the `None` default doesn't spuriously trigger the same warning
- Found by an independent review: `_resolve_resource_col_name` was rebuilding the trial's combined dataframe a second time (a `pd.concat` over every run) purely to check column membership, on top of the caller's own rebuild for the real call — doubling the cost of every `by="resource"` call on the default path. Fixed by building the frame once per method and passing it into the resolver; covered by a test proving the resolver checks the dataframe it is given, not one it re-derives itself
- `welch_moving_average` is checked against a hand-computed, deliberately non-linear three-run series (`welch_series`) for both methods, full array asserted at every index including the shrinking left edge — mutation-proven to fail if the edge case were removed and the interior formula applied throughout — plus the output-length contract for each method, unequal-length runs truncating with a warning, a single-run trial for both methods (its own ensemble mean, checked against non-linear values so the shrinking-edge formula is genuinely exercised, not just an averaged-out series), and every validation error (`series_by_run` empty, unknown `method`, `window` missing/non-positive/too large for `method="welch"`), plus `method="none"` matching the ensemble mean exactly and ignoring `window` (mutation-proven). `plot_warm_up_diagnostic` is covered for all three `series=` options against hand-computed arrays reached through the full pipeline (`event_log` → `vidigi.analysis` function → ensemble mean → smoothing), the `series="duration"` x-axis being arrival order rather than time, `show_ensemble`'s extra trace, one trace per `windows=` entry, the nearest-match hint on an unknown `series="occupancy"` event, `series="queue"` with `limit_duration=None` resolving to the log's latest time without the spurious int-coercion warning a raw `.max()` would trigger, every mutually-exclusive/missing-argument validation error, and a shape-only check (rises then flattens, never a specific warm-up value) against a purpose-built non-stationary fixture, and that `method="none"` suppresses `show_ensemble`'s reference line (mutation-proven, since it would otherwise draw the identical trace twice). `show_runs=` is checked against the same hand-computed per-run occupancy values (not sampled entries, mutation-proven against truncating every run's trace to the shortest one), that every run shares one legend entry rather than getting its own (mutation-proven), and - via `unequal_run_loggers`, whose three runs have different entity counts - that each run's raw trace keeps its own full length rather than being cropped to match the shorter summary trace(s) (mutation-proven). `TrialLogger.plot_warm_up_diagnostic`'s delegation is checked against the same hand-computed figures, plus its `method="cumulative"`/`series="duration"`/`match=`/`show_runs=` paths, none of which the single original delegation test reached
- Two independent expert reviews (an OR/DES specialist and a Python QA engineer) of the Welch diagnostic found: the "cumulative" docstring wording fixed above; a coincidentally-passing `TrialLogger.plot_warm_up_diagnostic` test whose `limit_duration=20` happened to equal the fixture's own natural log end, so it couldn't have failed even with the passthrough dropped entirely — fixed to use a value that genuinely disagrees with the default, and mutation-proven; and, while re-deriving that test's expected values independently as part of the fix, a hand-computation error of my own (missed that both runs' bouts are clipped to end exactly at the new, shorter window boundary, which the half-open `[start, end)` convention then reads as unoccupied there) — caught before landing, not after, by verifying against a live run rather than trusting the arithmetic
- `event_durations`'s new `warm_up` is covered for the exclusion-by-`first_time` rule (full entity-set assertion), the exact-boundary case (mutation-proven inclusive, not exclusive), a pairing with no `first_time` surviving regardless (mutation-proven), the interaction with `keep_incomplete=False`, filtering per pairing rather than per entity under `match="occurrence"` (using the existing rework-loop fixture), the default's verified no-op, and the negative-`warm_up` error. `plot_metric_bar`'s explicit `warm_up=` and `plot_duration_distribution`'s passthrough (via `**kwargs`, needing no new parameter) are each covered with a fixture asymmetric enough that a dropped `warm_up` would give a different, not merely absent, answer — mutation-proven on `plot_metric_bar`'s threading specifically, after an initial version of that test used values that happened to coincide either way
- The now-documented **BREAKING** edge case — a trial with `unique_resource_id` on some resource-use rows but not others raising under the new default where the old hard-coded `"resource_id"` default used to succeed — is pinned by a regression test, including that `resource_col_name="resource_id"` is a working escape hatch back to the old behaviour
- `replication_precision` is checked against the same hand-computed `unequal_run_loggers` example already pinned elsewhere in this suite (cumulative means `[4.0, 4.5, 6.0]`, k=3 half-width matching the published-t-table value 6.5724), plus `stays_below_threshold`'s "stays below, not first drops below" semantics on a purpose-built series that dips to zero deviation early and then spikes — mutation-proven to fail if the check compared only each row's own deviation instead of the running suffix maximum — the always-`False`-at-k=1 edge case, a zero-cumulative-mean division producing `NaN` rather than `inf`/an error, the empty-input error, and that a single value needs no `scipy` import at all (only k>=2 does). `plot_replication_analysis` and `TrialLogger`'s two new delegating methods (`plot_replication_analysis`, `get_replication_precision`) are covered against the same hand-computed figures, including the CI-band trace's bounds (mutation-proven against a swapped upper/lower), that `ci_level`/`deviation_threshold`/`what`/`match` each genuinely reach the underlying calculation (mutation-proven), `show_deviation=False` dropping the second panel, the no-complete-pairs/fewer-than-two-replications/missing-`scipy` error paths, and that the new `marker_size=`/`line_width=` both reach the cumulative-mean and deviation traces (mutation-proven) while defaulting to the previous hard-coded values
- An independent Python-QA-engineer review of the above found the test suite trustworthy overall (all hand-computed reference values independently re-verified against scipy directly) but flagged four gaps, all closed: `TrialLogger.get_replication_precision`'s own `what=`/`match=` passthrough was untested (only its sibling `plot_replication_analysis` had `match=` coverage), `replication_precision`'s own `ci_level` had no direct test (only indirect coverage through the plot/`TrialLogger` layers), `get_replication_precision` succeeding at a single replication (unlike `plot_replication_analysis`, it has no `n>=2` guard) was unpinned, and the CI-band trace's `x` array was untested alongside its `y` bounds — each closed with a mutation-proven test
- `entity_metric_by_arrival` is covered against `unequal_run_loggers` for basic shape/values, a dedicated fixture proving `arrival_time` tracks `arrival_event` rather than `event_durations`'s own `first_time` (full array, not spot values), `rework_loop_logger` proving the arrival lookup always uses the entity's *earliest* occurrence regardless of `match` (mutation-proven against both a `match="last"` scenario and a merge-key-includes-`occurrence` mutation), a missing-arrival-event-for-one-entity case giving `NaN` rather than a dropped row, both `arrival_event`-coincides-with-`first_event`/`second_event` cases, and a raw frame with no run column proving the `NA`-to-`NA` merge join actually works through the real code path. `plot_metric_vs_arrival_time` and `TrialLogger`'s two new delegating methods are covered against the same hand-computed figures, including `colour_by="run"` as a full `{trace name: values}` mapping, `rolling_window`/`rolling_time` exact arithmetic with both-edge shrinkage on a fixture designed so the two smoothing strategies give numerically distinct answers (not a coincidental match), that `warm_up` filters by `arrival_time` rather than `first_time` (mutation-proven, using a fixture where the two orderings disagree) and is applied before smoothing rather than after (mutation-proven, using a fixture where leaked pre-warm-up data would visibly shift the result), the mutually-exclusive/non-positive `rolling_window`/`rolling_time` validation errors, and that `marker_size=`/`line_width=` reach the scatter/trend-line traces (mutation-proven) while defaulting to `plot_replication_analysis`'s equivalent values
- `VidigiStore`/`VidigiPriorityStore`'s new `logger=` auto-logging is covered end to end for both classes: exact start/end event pairs (entity_id, resource_id, default and label-derived event names) for both the immediate-availability and deferred/queued grant paths; that a queued request's start time is the actual grant time rather than the request time (mutation-proven — reverting the deferred-callback hook to a synchronous log call at request time makes this fail, by logging the waiter's start at the wrong time); an exception raised mid-resource-use still logs exactly one end event; a cancelled (reneged) request never logs a phantom start; the manual `get_direct()`/`put()` pattern and `VidigiPriorityStore.return_item()` called directly; an item lacking `id_attribute` degrading to `resource_id=None` instead of raising `AttributeError`; `label=` adding `unique_resource_id`; passing no `logger` at all being a true no-op; a logger configured with `entity_id` omitted skipping the log and warning exactly once per store, not once per call; per-call `start_event`/`end_event`/`event` overrides; `pathway`/`**extra_fields` passthrough; and that a no-arg `.populate()` top-up call leaves the pool's label (and therefore its default event names) unchanged. In the same style as `test_against_core_simpy.py`'s cross-model equivalence checks, a further pair of tests runs one non-trivial multi-entity, queueing, priority-ordered scenario twice - once with hand-written `EventLogger.log_resource_use_start`/`log_resource_use_end` calls, once with `logger=`/`entity_id=` auto-logging and no manual calls at all - and asserts the resulting logs are identical, for both the context-manager and `get_direct()`/`put()` patterns; mutation-proven by temporarily dropping `unique_resource_id` from the auto-logged path and confirming the comparison fails
- `VidigiStore`/`VidigiPriorityStore`'s new return guard (rejecting a SimPy event or `None` passed to `put()`/`return_item()`) is covered for both classes: every `simpy.Event` subclass a model realistically yields — bare `Event`, `Timeout`, `Condition`, `AllOf`, `Process`, and an unfulfilled `get_direct()` request (with `not pending.triggered` asserted so the case matches the test name) — plus `None`, all mutation-proven against weakening the guard to a `None`-only check. The guard is proven to fire *before* any side effect: a rejected call leaves `items` and both queues byte-for-byte unchanged and, on a `logger=` store, writes zero log rows — each mutation-proven against moving the guard below the auto-log call or below the raw put. Valid returns are confirmed unaffected: a real `VidigiResource` round-trips through `put()`/`return_item()` and lands back in the pool, the `request()` context manager still returns cleanly through its un-guarded `__exit__`, a `logger=` store still auto-logs a genuine release, generic non-resource contents (a string, an int) are still accepted — pinning the "no type constraint" decision — and the `cancel_get` docstring's advice is pinned end to end (returning the get event raises, returning its `.value` succeeds)
- `plot_entity_timeline`'s new `return_fig=` is covered as a mutation-proven pair: the default (`False`) calls `fig.show()` and returns `None`, `return_fig=True` returns the `go.Figure` without calling `fig.show()` at all - each proven to fail if the branch were inverted - plus a value check that the returned figure genuinely carries the requested entity's own events

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
    nurse_resource = yield req  ## NEED TO ASSIGN HERE
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
