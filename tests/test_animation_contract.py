"""Structural tests for the figures produced by animation.py.

These assert the shape of the returned plotly figure - frame count, frame
names, trace composition, animation timings - rather than comparing rendered
images. That keeps them fast and stable across plotly 5 and 6, while still
catching the ways an animation can come out wrong.

animation.py had no dedicated test file; the existing coverage is four
`try/except: pytest.fail(...)` smoke tests that assert nothing about the
figure.
"""

import datetime as dt
import typing

import pandas as pd
import plotly.graph_objects as go
import pytest

from vidigi.animation import (
    AnimationBackend,
    SimulationTimeUnit,
    add_repeating_overlay,
    animate_activity_log,
    generate_animation,
    process_background_image_path,
)
from vidigi.prep import generate_animation_df, reshape_for_animations
from vidigi.utils import EventPosition, ICON_FLIP_MARKER, create_event_position_df


def frame_names(fig):
    return [frame.name for frame in fig.frames]


# --------------------------------------------------------------------------- #
# Frames
# --------------------------------------------------------------------------- #


def test_returns_a_figure(positioned, basic_event_position_df):
    fig = generate_animation(positioned, basic_event_position_df)

    assert isinstance(fig, go.Figure)


def test_one_frame_per_snapshot(positioned, basic_event_position_df):
    """Every snapshot in the data becomes exactly one animation frame."""
    fig = generate_animation(positioned, basic_event_position_df)

    expected = sorted(positioned["snapshot_time"].unique())

    assert len(fig.frames) == len(expected)
    assert frame_names(fig) == [str(snapshot) for snapshot in expected]


def test_frames_are_in_chronological_order(positioned, basic_event_position_df):
    """Out-of-order frames would make the animation jump around in time."""
    fig = generate_animation(positioned, basic_event_position_df)

    numeric = [float(name) for name in frame_names(fig)]

    assert numeric == sorted(numeric)


def test_empty_snapshot_still_produces_a_frame(positioned, basic_event_position_df):
    """Snapshot 50 has nobody in the system but must not be skipped."""
    fig = generate_animation(positioned, basic_event_position_df)

    assert "50" in frame_names(fig)


# --------------------------------------------------------------------------- #
# Animation timings
# --------------------------------------------------------------------------- #


def test_frame_duration_reaches_the_play_button(positioned, basic_event_position_df):
    """frame_duration must land in the updatemenu args, not just be accepted.

    The source swallows an IndexError here and prints a message, so a silent
    failure to apply the setting would otherwise go unnoticed.
    """
    fig = generate_animation(
        positioned,
        basic_event_position_df,
        frame_duration=123,
        frame_transition_duration=456,
    )

    play_args = fig.layout.updatemenus[0].buttons[0].args[1]

    assert play_args["frame"]["duration"] == 123
    assert play_args["transition"]["duration"] == 456


def test_include_play_button_false_removes_controls(
    positioned, basic_event_position_df
):
    fig = generate_animation(
        positioned, basic_event_position_df, include_play_button=False
    )

    assert not fig.layout.updatemenus


# --------------------------------------------------------------------------- #
# Traces: stage labels and resources
# --------------------------------------------------------------------------- #


def test_stage_labels_add_one_trace_with_every_label(
    positioned, basic_event_position_df
):
    fig = generate_animation(
        positioned, basic_event_position_df, display_stage_labels=True
    )
    label_traces = [
        trace
        for trace in fig.data
        if trace.mode == "text" and trace.text is not None
    ]

    assert len(label_traces) == 1
    assert set(label_traces[0].text) == set(basic_event_position_df["label"])


def test_stage_labels_can_be_disabled(positioned, basic_event_position_df):
    with_labels = generate_animation(
        positioned, basic_event_position_df, display_stage_labels=True
    )
    without_labels = generate_animation(
        positioned, basic_event_position_df, display_stage_labels=False
    )

    assert len(without_labels.data) == len(with_labels.data) - 1


def test_one_resource_marker_per_available_resource(
    positioned_with_resources, basic_event_position_df, scenario_with_resources
):
    """The scenario's resource count drives how many markers are drawn."""
    fig = generate_animation(
        positioned_with_resources,
        basic_event_position_df,
        scenario=scenario_with_resources,
        display_stage_labels=False,
    )

    # The resource trace is the last one added.
    resource_trace = fig.data[-1]

    assert len(resource_trace.x) == scenario_with_resources.n_cubicles


def test_scenario_without_any_resource_positions_is_harmless(
    positioned, basic_event_position_df, scenario_with_resources
):
    """A scenario may be passed for a model where no event declares a resource.

    Regression test: the resource block exploded an empty frame and died with
    KeyError: 'x_final'.
    """
    no_resources = basic_event_position_df.copy()
    no_resources["resource"] = None

    fig = generate_animation(
        positioned, no_resources, scenario=scenario_with_resources
    )

    assert isinstance(fig, go.Figure)


def test_custom_resource_icon_is_used(
    positioned_with_resources, basic_event_position_df, scenario_with_resources
):
    fig = generate_animation(
        positioned_with_resources,
        basic_event_position_df,
        scenario=scenario_with_resources,
        custom_resource_icon="🛏️",
    )

    # One entry per resource unit - unflipped, so every one is the bare icon.
    assert list(fig.data[-1].text) == ["🛏️"] * len(fig.data[-1].x)


# --------------------------------------------------------------------------- #
# Auto-layout: keeping labels and edge icons on the canvas
# --------------------------------------------------------------------------- #
#
# With no override_x_max / override_y_max the axis range is derived purely from
# event anchor points. Long stage labels (drawn past the rightmost anchor) and
# queue/resource icons (drawn left of a low-x anchor) then fall outside the data
# range. The fix is cliponaxis=False on every content trace plus a figure margin
# that grows to fit the overflow - never a change to the data range itself.


@pytest.fixture
def positioned_low_x(basic_event_position_df):
    """A prep frame whose queue icons sit at negative x.

    Twelve entities queue simultaneously at an event anchored near x=0, so the
    wrapped queue extends left past the axis.
    """
    specs = []
    for entity_id in range(1, 13):
        specs.append((entity_id, entity_id, "arrival_departure", "arrival"))
        specs.append((entity_id, entity_id, "queue", "waiting"))
        specs.append((200 + entity_id, entity_id, "arrival_departure", "depart"))
    log = pd.DataFrame(
        [
            {"time": t, "entity_id": e, "event_type": et, "event": ev}
            for t, e, et, ev in specs
        ]
    )
    low_x = basic_event_position_df.copy()
    low_x.loc[low_x["event"] == "waiting", "x"] = 40
    reshaped = reshape_for_animations(log, every_x_time_units=10, limit_duration=60)
    return generate_animation_df(reshaped, low_x), low_x


def test_content_traces_are_not_clipped_at_the_axis(
    positioned_with_resources, basic_event_position_df, scenario_with_resources
):
    """Every scatter trace - entities, stage labels, resource icons - and every
    frame trace must carry cliponaxis=False, or content outside the data range
    is chopped at the plot edge."""
    fig = generate_animation(
        positioned_with_resources,
        basic_event_position_df,
        scenario=scenario_with_resources,
    )

    assert fig.data
    assert all(trace.cliponaxis is False for trace in fig.data)
    assert all(
        trace.cliponaxis is False
        for frame in fig.frames
        for trace in frame.data
        if getattr(trace, "type", None) == "scatter"
    )


def test_disable_axis_clipping_handles_graph_object_frame_dicts():
    """The 'go' backend stores frame data as bare dicts. The helper must not
    trip over that, and the base trace it merges onto must be unclipped."""
    from vidigi.animation import _disable_axis_clipping

    fig = go.Figure(
        data=[go.Scatter(x=[1], y=[1], mode="text", text=["x"])],
        frames=[go.Frame(data=[{"x": [2], "y": [2], "text": ["y"]}], name="1")],
    )

    _disable_axis_clipping(fig)

    assert fig.data[0].cliponaxis is False


def test_right_margin_grows_with_the_longest_stage_label(
    positioned, basic_event_position_df
):
    """A longer label needs more room to its right; a short one needs none."""
    short = basic_event_position_df.copy()
    short["label"] = ["A", "B", "C", "D"]
    long = basic_event_position_df.copy()
    long["label"] = ["A", "B", "C", "D reaching well past the rightmost anchor"]

    short_r = generate_animation(positioned, short).layout.margin.r
    long_r = generate_animation(positioned, long).layout.margin.r

    # Short labels fit inside the default margin, so it is left untouched.
    assert short_r is None
    assert long_r is not None and long_r > 80


def test_hidden_stage_labels_do_not_reserve_right_margin(
    positioned, basic_event_position_df
):
    long = basic_event_position_df.copy()
    long["label"] = ["A", "B", "C", "D reaching well past the rightmost anchor"]

    fig = generate_animation(positioned, long, display_stage_labels=False)

    assert fig.layout.margin.r is None


def test_left_margin_engages_when_icons_sit_left_of_the_axis(positioned_low_x):
    positioned, low_x = positioned_low_x

    assert positioned["x_final"].min() < 0  # fixture really does overflow left

    fig = generate_animation(positioned, low_x)

    assert fig.layout.margin.l is not None and fig.layout.margin.l > 80


def test_plain_animation_keeps_default_left_and_right_margins(
    positioned, basic_event_position_df
):
    """Nothing overflows here, so the data range and margins are left alone."""
    fig = generate_animation(positioned, basic_event_position_df)

    # basic_event_position_df's longest label ("Being Treated") does reserve a
    # right margin; the left side has nothing past the axis.
    assert fig.layout.margin.l is None
    assert fig.layout.xaxis.range is None or list(fig.layout.xaxis.range)[0] == 0


# --------------------------------------------------------------------------- #
# Queue build direction
# --------------------------------------------------------------------------- #


@pytest.fixture
def positioned_high_x(basic_event_position_df):
    """A right-building queue whose icons run past the right edge of the axis.

    Twelve entities queue simultaneously at the rightmost anchor with a wide
    gap and no wrapping, so ``x_final`` reaches well beyond ``x_max`` (which is
    ``event_position_df["x"].max() * 1.25``). The mirror of ``positioned_low_x``.
    """
    specs = []
    for entity_id in range(1, 13):
        specs.append((entity_id, entity_id, "arrival_departure", "arrival"))
        specs.append((entity_id, entity_id, "queue", "waiting"))
        specs.append((200 + entity_id, entity_id, "arrival_departure", "depart"))
    log = pd.DataFrame(
        [
            {"time": t, "entity_id": e, "event_type": et, "event": ev}
            for t, e, et, ev in specs
        ]
    )
    reshaped = reshape_for_animations(log, every_x_time_units=10, limit_duration=60)
    positioned = generate_animation_df(
        reshaped,
        basic_event_position_df,
        wrap_queues_at=None,
        gap_between_entities=20,
        queue_direction="right",
    )
    return positioned, basic_event_position_df


def test_right_margin_engages_when_a_right_building_queue_overflows(positioned_high_x):
    positioned, epd = positioned_high_x

    x_max = epd["x"].max() * 1.25
    assert positioned["x_final"].max() > x_max  # fixture really does overflow right

    fig = generate_animation(positioned, epd, queue_direction="right")

    assert fig.layout.margin.r is not None and fig.layout.margin.r > 80


def test_stage_label_sits_left_of_a_right_building_queue(
    positioned, basic_event_position_df
):
    """With the queue extending right, the label must move to the left of the
    anchor or the queue runs straight over it."""
    fig = generate_animation(positioned, basic_event_position_df, queue_direction="right")

    label_trace = [t for t in fig.data if t.mode == "text"][-1]
    anchors = basic_event_position_df["x"].to_list()

    assert list(label_trace.x) == [a - 10 for a in anchors]
    assert set(label_trace.textposition) == {"middle left"}
    # And the left margin grows to hold those labels.
    assert fig.layout.margin.l is not None and fig.layout.margin.l > 80


def test_left_building_queue_keeps_label_on_the_right(
    positioned, basic_event_position_df
):
    """The default direction is unchanged - label to the right of the anchor."""
    fig = generate_animation(positioned, basic_event_position_df)

    label_trace = [t for t in fig.data if t.mode == "text"][-1]
    anchors = basic_event_position_df["x"].to_list()

    assert list(label_trace.x) == [a + 10 for a in anchors]
    assert set(label_trace.textposition) == {"middle right"}


def test_resource_markers_follow_queue_direction(
    positioned_with_resources, basic_event_position_df, scenario_with_resources
):
    """The resource-availability dots lay out rightwards from the anchor when
    ``queue_direction="right"`` - the mirror of the default leftward layout."""
    left = generate_animation(
        positioned_with_resources,
        basic_event_position_df,
        scenario=scenario_with_resources,
    )
    right = generate_animation(
        positioned_with_resources,
        basic_event_position_df,
        scenario=scenario_with_resources,
        queue_direction="right",
    )

    def marker_xs(fig):
        trace = [t for t in fig.data if t.mode == "markers"][-1]
        return list(trace.x)

    left_xs, right_xs = marker_xs(left), marker_xs(right)
    # treatment_begins is anchored at x=400 with three cubicles, gap 10. The two
    # directions are exact mirror images of each other about the anchor.
    assert left_xs == [400.0, 390.0, 380.0]
    assert right_xs == [400.0, 410.0, 420.0]


def test_animate_activity_log_threads_queue_direction(
    simple_queue_log, basic_event_position_df
):
    """End to end: the one-call wrapper passes queue_direction all the way
    through, and it visibly moves the queued entities."""
    common = dict(every_x_time_units=10, limit_duration=50, gap_between_entities=10)
    left = animate_activity_log(
        simple_queue_log, basic_event_position_df, queue_direction="left", **common
    )
    right = animate_activity_log(
        simple_queue_log, basic_event_position_df, queue_direction="right", **common
    )

    def waiting_xs(fig):
        xs = []
        for frame in fig.frames:
            for trace in frame.data:
                if getattr(trace, "x", None) is not None:
                    xs.extend(v for v in trace.x if v is not None)
        return xs

    # Right-building queue draws entities further right than the left one.
    assert max(waiting_xs(right)) > max(waiting_xs(left))


# --------------------------------------------------------------------------- #
# Icon flipping
# --------------------------------------------------------------------------- #


def _all_entity_texts(fig):
    """Every text value actually drawn by every entity trace, across every frame.

    Covers both backends: the express backend's per-frame trace is a plotly
    graph object, the go backend's is a plain dict - both expose the same
    parallel x/y/text arrays. An empty snapshot (nobody present for a given
    event at that moment) is filled with a single all-NaN-position placeholder
    row so the frame isn't literally empty - it carries a leftover icon value
    but Plotly never draws it at a NaN coordinate, so it is excluded here too.
    """
    texts = []
    for frame in fig.frames:
        for trace in frame.data:
            trace_x = trace["x"] if isinstance(trace, dict) else trace.x
            trace_text = trace["text"] if isinstance(trace, dict) else trace.text
            if trace_x is None or trace_text is None:
                continue
            for x, text in zip(trace_x, trace_text):
                if pd.notna(x) and text is not None:
                    texts.append(text)
    return texts


@pytest.fixture
def positioned_overflow(overflow_queue_log, basic_event_position_df):
    """Twelve entities queued at once with only 5 slots shown - the rest
    collapse into a single '+ N more' overflow row per snapshot."""
    reshaped = reshape_for_animations(
        overflow_queue_log, every_x_time_units=10, limit_duration=30, step_snapshot_max=5
    )
    return generate_animation_df(
        reshaped, basic_event_position_df, step_snapshot_max=5, wrap_queues_at=5
    )


@pytest.mark.parametrize("backend", ["express", "go"])
def test_no_icon_is_flipped_by_default(positioned, basic_event_position_df, backend):
    fig = generate_animation(positioned, basic_event_position_df, backend=backend)
    texts = [t for t in _all_entity_texts(fig) if t]
    assert texts  # sanity: the fixture actually draws something
    assert all(not str(t).startswith(ICON_FLIP_MARKER) for t in texts)


@pytest.mark.parametrize("backend", ["express", "go"])
def test_flip_entity_icons_marks_every_entity_icon(
    positioned, basic_event_position_df, backend
):
    fig = generate_animation(
        positioned, basic_event_position_df, flip_entity_icons=True, backend=backend
    )
    texts = [t for t in _all_entity_texts(fig) if t]
    assert texts
    assert all(str(t).startswith(ICON_FLIP_MARKER) for t in texts)


def test_per_event_flip_icons_overrides_global(
    simple_queue_log, basic_event_position_df
):
    """Only the 'waiting' event is marked ``flip_icons=True``; the animation-wide
    default stays False, so every other event's icon must stay unflipped."""
    mixed_epd = basic_event_position_df.copy()
    mixed_epd.loc[mixed_epd["event"] == "waiting", "flip_icons"] = True

    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    positioned_mixed = generate_animation_df(reshaped, mixed_epd)

    fig = generate_animation(positioned_mixed, mixed_epd)

    waiting_texts, other_texts = [], []
    for frame in fig.frames:
        for trace in frame.data:
            trace_x = trace["x"] if isinstance(trace, dict) else trace.x
            trace_text = trace["text"] if isinstance(trace, dict) else trace.text
            if trace_x is None or trace_text is None:
                continue
            for x, text in zip(trace_x, trace_text):
                if text is None or x is None:
                    continue
                # 'waiting' queues out from x=400 (400, 390, 380 for up to three
                # simultaneously-ranked entities); 'arrival' (x=50) and 'depart'
                # (x=270) never land anywhere near that range.
                if 370 <= x <= 410:
                    waiting_texts.append(text)
                else:
                    other_texts.append(text)

    assert waiting_texts
    assert other_texts
    assert all(str(t).startswith(ICON_FLIP_MARKER) for t in waiting_texts)
    assert all(not str(t).startswith(ICON_FLIP_MARKER) for t in other_texts)


def test_overflow_icons_are_never_flipped(positioned_overflow, basic_event_position_df):
    """Mirrored text is unreadable, and the gauge/count string embeds the
    entity icon mid-string - overflow rows must be exempt from flipping even
    when the whole animation is flipped."""
    fig = generate_animation(
        positioned_overflow, basic_event_position_df, flip_entity_icons=True
    )
    overflow_texts = [t for t in _all_entity_texts(fig) if t and "more" in str(t)]
    assert overflow_texts  # sanity: overflow really is present
    assert all(not str(t).startswith(ICON_FLIP_MARKER) for t in overflow_texts)


def test_custom_resource_icon_follows_per_event_flip(
    positioned_with_resources, basic_event_position_df, scenario_with_resources
):
    unflipped = generate_animation(
        positioned_with_resources,
        basic_event_position_df,
        scenario=scenario_with_resources,
        custom_resource_icon="🛏️",
    )
    flipped = generate_animation(
        positioned_with_resources,
        basic_event_position_df,
        scenario=scenario_with_resources,
        custom_resource_icon="🛏️",
        flip_entity_icons=True,
    )

    assert list(unflipped.data[-1].text) == ["🛏️"] * len(unflipped.data[-1].x)
    assert list(flipped.data[-1].text) == [ICON_FLIP_MARKER + "🛏️"] * len(
        flipped.data[-1].x
    )


# --------------------------------------------------------------------------- #
# Custom icons: icon fonts, per-entity colour, resource images
# --------------------------------------------------------------------------- #


@pytest.fixture
def positioned_with_priority(simple_queue_log, basic_event_position_df):
    """The `positioned` fixture's log, with a `priority` column carried through -
    exactly how a real event-log column (e.g. triage priority) would reach
    `entity_colour_by`. Entities 1 and 3 are 'high', 2 is 'low'."""
    log = simple_queue_log.copy()
    log["priority"] = log["entity_id"].map({1: "high", 2: "low", 3: "high"})
    reshaped = reshape_for_animations(log, every_x_time_units=10, limit_duration=50)
    return generate_animation_df(reshaped, basic_event_position_df)


def _entity_traces(fig):
    """Every entity trace - `mode="markers+text"`, as distinct from the
    stage-label trace (`mode="text"`) appended after them."""
    return [t for t in fig.data if t.mode == "markers+text"]


def test_no_font_or_colour_is_set_by_default(positioned, basic_event_position_df):
    fig = generate_animation(positioned, basic_event_position_df)
    assert fig.data[0].textfont.family is None
    # The historic behaviour - one entity trace, uniformly coloured.
    assert len(_entity_traces(fig)) == 1


def test_entity_icon_font_applies_to_non_overflow_icons(
    positioned, basic_event_position_df
):
    fig = generate_animation(
        positioned, basic_event_position_df, entity_icon_font="font-awesome"
    )
    assert fig.data[0].textfont.family == "VidigiFontAwesomeSolid"
    assert fig.data[0].textfont.weight == 900


def test_entity_icon_font_weight_override(positioned, basic_event_position_df):
    fig = generate_animation(
        positioned,
        basic_event_position_df,
        entity_icon_font="font-awesome",
        entity_icon_font_weight=400,
    )
    assert fig.data[0].textfont.weight == 400


def test_overflow_icons_never_get_the_icon_font(
    positioned_overflow, basic_event_position_df
):
    """Checks by the overflow row's actual *content* ('+ N more'), not by which
    trace name it happens to land in - a trace-name-only check would pass even
    if overflow rows and real entities were routed to the wrong buckets, as
    long as *a* trace called "_overflow" still exists with no font set."""
    fig = generate_animation(
        positioned_overflow, basic_event_position_df, entity_icon_font="font-awesome"
    )
    overflow_family = plain_family = None
    for frame in fig.frames:
        for trace in frame.data:
            if trace.text is None or trace.x is None:
                continue
            # Pair with x: the all-NaN "empty snapshot" placeholder row carries a
            # leftover real icon string in its `icon` column despite never being
            # drawn (NaN x/y - see prep.py) - skip anything not actually rendered,
            # or it can be mistaken for a real, visible entity icon.
            for x, text in zip(trace.x, trace.text):
                if pd.notna(x) and text and "more" in str(text):
                    overflow_family = trace.textfont.family
                elif pd.notna(x) and text:
                    plain_family = trace.textfont.family

    assert overflow_family in (None, "")  # sanity: overflow really is present
    assert plain_family == "VidigiFontAwesomeSolid"


def test_reconciled_placeholder_traces_never_carry_a_trace_level_opacity(
    positioned_overflow, basic_event_position_df
):
    """Regression test for a real Plotly animation bug: a category (here,
    "_overflow" - nobody has queued long enough to overflow yet at frame 0)
    that is empty in the frame where its placeholder trace is first created
    must not have that placeholder's `opacity` "stick" once the category
    starts having real content in later frames.

    Plotly's frame animation only patches attributes a frame's trace data
    explicitly sets; a real (non-placeholder) entity trace only ever sets
    `marker.opacity` (uniformly, for every category), never a trace-level
    `opacity`. So a placeholder that sets a trace-level `opacity=0` - even
    though nulled-out x/y already draw nothing on its own frame - poisons
    every later frame that reuses the same trace slot: the category renders
    invisible for the rest of the animation, confirmed by inspecting the live
    DOM in a real browser (a `<g class="trace">` stuck at `opacity: 0`), not
    just by reading the frame data back in Python.
    """
    fig = generate_animation(
        positioned_overflow, basic_event_position_df, entity_icon_font="font-awesome"
    )
    for trace in _entity_traces(fig):
        assert trace.opacity in (None, 1)
    for frame in fig.frames:
        for trace in frame.data:
            if trace.mode == "markers+text":
                assert trace.opacity in (None, 1)


def test_custom_icon_font_with_a_standalone_digit_raises(
    positioned, basic_event_position_df
):
    # "Font Awesome 6 Free" is the vendor's own name for the exact preset this
    # rejects it in favour of - see ICON_FONT_PRESETS in vidigi/utils.py.
    with pytest.raises(ValueError, match="standalone number"):
        generate_animation(
            positioned, basic_event_position_df, entity_icon_font="Font Awesome 6 Free"
        )


def test_entity_colour_by_gives_a_stable_trace_structure_across_frames(
    positioned_with_priority, basic_event_position_df
):
    """The whole feature depends on this: Plotly Express only creates a `color=`
    trace for a category with at least one point in a given frame, so without
    reconciliation a category missing from an early frame is missing from every
    frame - confirmed via mutation testing below."""
    fig = generate_animation(
        positioned_with_priority, basic_event_position_df, entity_colour_by="priority"
    )
    base_names = sorted(t.name for t in _entity_traces(fig))
    assert "high" in base_names and "low" in base_names
    for frame in fig.frames:
        assert sorted(t.name for t in frame.data) == base_names


def test_entity_colour_by_sets_textfont_color_from_marker_color(
    positioned_with_priority, basic_event_position_df
):
    fig = generate_animation(
        positioned_with_priority,
        basic_event_position_df,
        entity_colour_by="priority",
        entity_colour_map={"high": "crimson", "low": "steelblue"},
    )
    by_name = {t.name: t for t in fig.data}
    assert by_name["high"].textfont.color == "crimson"
    assert by_name["low"].textfont.color == "steelblue"
    # Colouring entities must not repurpose overflow_text_color for real
    # categories - only the reserved buckets keep it.
    assert by_name["_overflow"].textfont.color == "black"


def test_entity_colour_map_uncovered_value_gets_a_default_colour(
    positioned_with_priority, basic_event_position_df
):
    fig = generate_animation(
        positioned_with_priority,
        basic_event_position_df,
        entity_colour_by="priority",
        entity_colour_map={"high": "crimson"},  # 'low' left uncovered
    )
    by_name = {t.name: t for t in fig.data}
    assert by_name["low"].textfont.color not in (None, "", "crimson")


def test_entity_colour_by_shows_a_legend_by_default(
    positioned_with_priority, basic_event_position_df
):
    fig = generate_animation(
        positioned_with_priority, basic_event_position_df, entity_colour_by="priority"
    )
    by_name = {t.name: t for t in fig.data}
    assert by_name["high"].showlegend is not False
    assert by_name["low"].showlegend is not False
    # Never real categories, whatever show_entity_legend says.
    assert by_name["_overflow"].showlegend is False


def test_show_entity_legend_false_hides_it(
    positioned_with_priority, basic_event_position_df
):
    fig = generate_animation(
        positioned_with_priority,
        basic_event_position_df,
        entity_colour_by="priority",
        show_entity_legend=False,
    )
    assert all(t.showlegend is False for t in _entity_traces(fig))


def test_entity_colour_by_unknown_column_raises(positioned, basic_event_position_df):
    with pytest.raises(ValueError, match="entity_colour_by"):
        generate_animation(
            positioned, basic_event_position_df, entity_colour_by="not_a_real_column"
        )


# --------------------------------------------------------------------------- #
# entity_annotation_by: a second, independently-styled text trace
# --------------------------------------------------------------------------- #


@pytest.fixture
def positioned_overflow_with_los(overflow_queue_log, basic_event_position_df):
    """`positioned_overflow`, with a `los` column carried through - annotation
    text for `entity_annotation_by`, keyed so it's trivially checkable."""
    log = overflow_queue_log.copy()
    log["los"] = log["entity_id"].astype(str)
    reshaped = reshape_for_animations(
        log, every_x_time_units=10, limit_duration=30, step_snapshot_max=5
    )
    return generate_animation_df(
        reshaped, basic_event_position_df, step_snapshot_max=5, wrap_queues_at=5
    )


def _annotation_trace(fig):
    """The `entity_annotation_by` trace, if present - always named
    "_annotation", the last trace appended before stage labels/resources."""
    matches = [t for t in fig.data if t.name == "_annotation"]
    return matches[0] if matches else None


def test_entity_annotation_by_defaults_to_a_no_op(positioned, basic_event_position_df):
    fig = generate_animation(positioned, basic_event_position_df)
    assert _annotation_trace(fig) is None
    for frame in fig.frames:
        assert all(t.name != "_annotation" for t in frame.data)


def test_entity_annotation_by_draws_the_column_text(
    positioned_with_priority, basic_event_position_df
):
    fig = generate_animation(
        positioned_with_priority,
        basic_event_position_df,
        entity_annotation_by="priority",
    )
    assert _annotation_trace(fig) is not None
    seen = set()
    for frame in fig.frames:
        annotation = next(t for t in frame.data if t.name == "_annotation")
        for x, text in zip(annotation.x, annotation.text):
            if pd.notna(x) and text is not None:
                seen.add(text)
    assert seen == {"high", "low"}


def test_entity_annotation_by_matches_entity_trace_point_for_point_per_frame(
    positioned_with_priority, basic_event_position_df
):
    """The annotation trace has to move in lockstep with the entity trace it
    labels - the same x positions, for the same count of real (non-placeholder)
    points, in every frame - not just somewhere in the same neighbourhood."""
    fig = generate_animation(
        positioned_with_priority,
        basic_event_position_df,
        entity_annotation_by="priority",
    )
    assert fig.frames  # sanity: there is something to check
    for frame in fig.frames:
        entity_xs = sorted(
            x
            for trace in frame.data
            if trace.name != "_annotation"
            for x in (trace.x if trace.x is not None else ())
            if pd.notna(x)
        )
        annotation = next(t for t in frame.data if t.name == "_annotation")
        annotation_xs = sorted(x for x in annotation.x if pd.notna(x))
        assert annotation_xs == entity_xs


def test_entity_annotation_by_offset_y(positioned_with_priority, basic_event_position_df):
    fig = generate_animation(
        positioned_with_priority,
        basic_event_position_df,
        entity_annotation_by="priority",
        entity_annotation_offset_y=-25,
    )
    icon_trace = next(
        t for t in fig.data if t.name != "_annotation" and t.mode == "markers+text"
    )
    annotation = _annotation_trace(fig)
    assert list(annotation.y) == [y - 25 for y in icon_trace.y]


def test_entity_annotation_size_and_color(positioned_with_priority, basic_event_position_df):
    fig = generate_animation(
        positioned_with_priority,
        basic_event_position_df,
        entity_annotation_by="priority",
        entity_annotation_size=20,
        entity_annotation_color="crimson",
    )
    annotation = _annotation_trace(fig)
    assert annotation.textfont.size == 20
    assert annotation.textfont.color == "crimson"
    for frame in fig.frames:
        frame_annotation = next(t for t in frame.data if t.name == "_annotation")
        assert frame_annotation.textfont.size == 20
        assert frame_annotation.textfont.color == "crimson"


def test_entity_annotation_by_is_never_flipped(
    positioned_with_priority, basic_event_position_df
):
    """Regression guard for the Plotly ceiling this feature exists to route
    around: a single SVG `<text>` node gets one transform, so text appended
    onto the icon's own string flips along with it. The annotation trace must
    never carry the flip marker, while the icon trace still must - proven by
    mutation testing below."""
    fig = generate_animation(
        positioned_with_priority,
        basic_event_position_df,
        entity_annotation_by="priority",
        flip_entity_icons=True,
    )
    icon_texts, annotation_texts = [], []
    for frame in fig.frames:
        for trace in frame.data:
            if trace.text is None or trace.x is None:
                continue
            for x, text in zip(trace.x, trace.text):
                if pd.isna(x) or text is None:
                    continue
                if isinstance(text, float) and pd.isna(text):
                    continue
                bucket = annotation_texts if trace.name == "_annotation" else icon_texts
                bucket.append(text)
    assert icon_texts and annotation_texts  # sanity: both traces really draw something
    assert all(str(t).startswith(ICON_FLIP_MARKER) for t in icon_texts)
    assert all(not str(t).startswith(ICON_FLIP_MARKER) for t in annotation_texts)


def test_entity_annotation_by_never_gets_the_icon_font(
    positioned_with_priority, basic_event_position_df
):
    fig = generate_animation(
        positioned_with_priority,
        basic_event_position_df,
        entity_annotation_by="priority",
        entity_icon_font="font-awesome",
    )
    annotation = _annotation_trace(fig)
    assert annotation.textfont.family != "VidigiFontAwesomeSolid"
    for frame in fig.frames:
        frame_annotation = next(t for t in frame.data if t.name == "_annotation")
        assert frame_annotation.textfont.family != "VidigiFontAwesomeSolid"


def test_entity_annotation_by_suppresses_the_overflow_row(
    positioned_overflow_with_los, basic_event_position_df
):
    """The synthetic '+ N more' row isn't a real entity, so it gets no
    annotation text - the same exemption the icon trace already gives it from
    flipping and icon fonts."""
    fig = generate_animation(
        positioned_overflow_with_los, basic_event_position_df, entity_annotation_by="los"
    )
    saw_overflow = False
    for frame in fig.frames:
        annotation = next(t for t in frame.data if t.name == "_annotation")
        overflow_xs = {
            x
            for trace in frame.data
            if trace.name != "_annotation"
            for x, text in zip(
                trace.x if trace.x is not None else (),
                trace.text if trace.text is not None else (),
            )
            if text and "more" in str(text)
        }
        if overflow_xs:
            saw_overflow = True
        for x, text in zip(annotation.x, annotation.text):
            if x in overflow_xs:
                assert text is None or (isinstance(text, float) and pd.isna(text))
    assert saw_overflow  # sanity: overflow really is present


def test_entity_annotation_by_unknown_column_raises(positioned, basic_event_position_df):
    with pytest.raises(ValueError, match="entity_annotation_by"):
        generate_animation(
            positioned, basic_event_position_df, entity_annotation_by="not_a_real_column"
        )


def test_resource_icon_image_becomes_a_layout_image(
    positioned_with_resources, basic_event_position_df, scenario_with_resources
):
    epd_with_image = basic_event_position_df.copy()
    epd_with_image.loc[
        epd_with_image["event"] == "treatment_begins", "resource_icon"
    ] = "https://example.com/bed.png"

    fig = generate_animation(
        positioned_with_resources, epd_with_image, scenario=scenario_with_resources
    )

    assert len(fig.layout.images) == scenario_with_resources.n_cubicles
    assert all(img.source == "https://example.com/bed.png" for img in fig.layout.images)
    # An image resource icon draws nothing on the text/marker trace it would
    # otherwise have used.
    assert not any(
        t.mode == "markers+text" for t in fig.data if t.name not in ("", None)
    )


def test_resource_icon_image_size_defaults_independently_of_gap(
    positioned_with_resources, basic_event_position_df, scenario_with_resources
):
    # Regression test: resource_image_size used to default to
    # gap_between_resources, so widening the spacing between resources also
    # inflated the image - unlike a text resource icon, whose size
    # (resource_icon_size) is independent of the spacing between icons.
    epd_with_image = basic_event_position_df.copy()
    epd_with_image.loc[
        epd_with_image["event"] == "treatment_begins", "resource_icon"
    ] = "https://example.com/bed.png"

    fig_narrow = generate_animation(
        positioned_with_resources,
        epd_with_image,
        scenario=scenario_with_resources,
        gap_between_resources=10,
        resource_icon_size=24,
    )
    fig_wide = generate_animation(
        positioned_with_resources,
        epd_with_image,
        scenario=scenario_with_resources,
        gap_between_resources=80,
        resource_icon_size=24,
    )

    assert all(img.sizex == 24 and img.sizey == 24 for img in fig_narrow.layout.images)
    assert all(img.sizex == 24 and img.sizey == 24 for img in fig_wide.layout.images)


def test_resource_image_size_overrides_the_default(
    positioned_with_resources, basic_event_position_df, scenario_with_resources
):
    epd_with_image = basic_event_position_df.copy()
    epd_with_image.loc[
        epd_with_image["event"] == "treatment_begins", "resource_icon"
    ] = "https://example.com/bed.png"

    fig = generate_animation(
        positioned_with_resources,
        epd_with_image,
        scenario=scenario_with_resources,
        resource_icon_size=24,
        resource_image_size=60,
    )

    assert all(img.sizex == 60 and img.sizey == 60 for img in fig.layout.images)


def test_resource_icon_glyph_overrides_custom_resource_icon(
    positioned_with_resources, basic_event_position_df, scenario_with_resources
):
    epd_with_glyph = basic_event_position_df.copy()
    epd_with_glyph.loc[
        epd_with_glyph["event"] == "treatment_begins", "resource_icon"
    ] = "🛌"

    fig = generate_animation(
        positioned_with_resources,
        epd_with_glyph,
        scenario=scenario_with_resources,
        custom_resource_icon="🛏️",  # overridden by resource_icon for this event
    )

    resource_trace = [t for t in fig.data if t.mode == "markers+text"][-1]
    assert list(resource_trace.text) == ["🛌"] * len(resource_trace.x)


# --------------------------------------------------------------------------- #
# Hover configuration
# --------------------------------------------------------------------------- #


def test_custom_hover_data_list_is_not_mutated(
    positioned, basic_event_position_df, scenario_with_resources
):
    """The caller's list must survive unchanged, including across repeat calls.

    Regression test: the list was used directly and appended to, so it grew by
    one entry per call and eventually referenced a column twice.
    """
    hovers = ["entity_id", "event"]

    generate_animation(
        positioned,
        basic_event_position_df,
        scenario=scenario_with_resources,
        custom_hover_data=hovers,
        hover_text_entity="%{customdata[0]}",
    )
    generate_animation(
        positioned,
        basic_event_position_df,
        scenario=scenario_with_resources,
        custom_hover_data=hovers,
        hover_text_entity="%{customdata[0]}",
    )

    assert hovers == ["entity_id", "event"]


def test_hover_text_none_disables_hover(positioned, basic_event_position_df):
    fig = generate_animation(
        positioned, basic_event_position_df, hover_text_entity=None
    )

    assert isinstance(fig, go.Figure)


def test_custom_hover_data_with_default_template_raises(
    positioned, basic_event_position_df
):
    """custom_hover_data replaces the six-column list the default template indexes.

    Leaving hover_text_entity="default" then points customdata[0..5] at the
    wrong - or missing - columns and renders broken hover with no error, so the
    combination is rejected up front.
    """
    with pytest.raises(ValueError, match="custom_hover_data.*hover_text_entity"):
        generate_animation(
            positioned,
            basic_event_position_df,
            custom_hover_data=["entity_id"],
        )


def test_custom_hover_data_with_hover_disabled_does_not_raise(
    positioned, basic_event_position_df
):
    """The guard keys on the "default" sentinel, not "not a custom string".

    hover_text_entity=None disables hover entirely, so there is no template to
    misindex and custom_hover_data alongside it must not raise.
    """
    fig = generate_animation(
        positioned,
        basic_event_position_df,
        custom_hover_data=["entity_id"],
        hover_text_entity=None,
    )

    assert isinstance(fig, go.Figure)


def test_resource_col_name_is_appended_after_custom_hover_data(
    positioned_with_resources, basic_event_position_df, scenario_with_resources
):
    """With a scenario and a resource_id column, resource_col_name lands at
    customdata[len(custom_hover_data)] - the index the docstring promises.
    """
    fig = generate_animation(
        positioned_with_resources,
        basic_event_position_df,
        scenario=scenario_with_resources,
        custom_hover_data=["entity_id"],
        hover_text_entity="entity %{customdata[0]} on resource %{customdata[1]}",
    )

    # resource_id is index 1 (right after the single custom column). The
    # resource_log fixture assigns ids 1 and 2 to the two treated entities.
    index_1_values = {
        row[1]
        for frame in fig.frames
        for trace in frame.data
        if trace.customdata is not None
        for row in trace.customdata
        if len(row) > 1
    }
    assert {1, 2} <= index_1_values


def test_custom_hover_template_is_applied_to_every_frame(
    positioned, basic_event_position_df
):
    """A hover template set on the initial trace must also reach the frames.

    Otherwise hover text is correct until the animation advances one frame.
    """
    template = "Entity %{customdata[0]}"

    fig = generate_animation(
        positioned,
        basic_event_position_df,
        custom_hover_data=["entity_id"],
        hover_text_entity=template,
    )

    assert fig.data[0].hovertemplate == template
    for frame in fig.frames:
        for trace in frame.data:
            assert trace.hovertemplate == template


# --------------------------------------------------------------------------- #
# Time display
# --------------------------------------------------------------------------- #


def _positioned_at_interval(event_position_df, interval, n_snapshots=3):
    """Positioned data whose snapshots are `interval` time units apart.

    Each display format needs a snapshot spacing at least as coarse as itself,
    or every snapshot formats to the same label and the frames collapse.
    """
    specs = []
    for index in range(n_snapshots):
        entity_id = index + 1
        arrival = index * interval
        specs += [
            (arrival, entity_id, "arrival_departure", "arrival"),
            (arrival, entity_id, "queue", "waiting"),
            (interval * n_snapshots * 5, entity_id, "arrival_departure", "depart"),
        ]
    log = pd.DataFrame(
        [
            {"time": t, "entity_id": e, "event_type": et, "event": ev}
            for t, e, et, ev in specs
        ]
    )
    reshaped = reshape_for_animations(
        log,
        every_x_time_units=interval,
        limit_duration=interval * (n_snapshots - 1),
    )
    return generate_animation_df(reshaped, event_position_df)


# Interval is in simulation minutes and must be at least as coarse as the
# display format, so each snapshot gets a distinct label.
@pytest.mark.parametrize(
    "time_display_units, interval, expected_fragment",
    [
        ("dhms", 10, "01 January 2020"),
        ("dhms_ampm", 10, "AM"),
        ("dhm", 10, "01 January 2020"),
        ("dh", 60, "01 January 2020"),
        ("d", 60 * 24, "Wednesday 01 January 2020"),
        ("m", 60 * 24 * 31, "January 2020"),
        ("y", 60 * 24 * 366, "2020"),
        ("%Y-%m-%d", 60 * 24, "2020-01-01"),
    ],
)
def test_time_display_units_formats_frame_labels(
    basic_event_position_df, time_display_units, interval, expected_fragment
):
    positioned = _positioned_at_interval(basic_event_position_df, interval)

    fig = generate_animation(
        positioned,
        basic_event_position_df,
        time_display_units=time_display_units,
        start_date="2020-01-01",
    )

    assert any(expected_fragment in name for name in frame_names(fig))


def test_display_format_coarser_than_snapshots_warns(
    positioned, basic_event_position_df
):
    """Collapsing snapshots into one label must not happen silently.

    The animation frame is the formatted time, so 10 minute snapshots shown as
    'd' all carry the same label. Plotly then produces no frames at all and
    entities from different moments are drawn on top of one another.
    """
    with pytest.warns(UserWarning, match="coarser than the snapshot interval"):
        fig = generate_animation(
            positioned,
            basic_event_position_df,
            time_display_units="d",
            start_date="2020-01-01",
        )

    # Demonstrates the consequence the warning is about.
    assert len(fig.frames) == 0


def test_day_clock_counts_from_simulation_start(
    positioned, basic_event_position_df
):
    fig = generate_animation(
        positioned,
        basic_event_position_df,
        time_display_units="day_clock",
        start_date="2020-01-01",
    )

    assert any("Simulation Day 1" in name for name in frame_names(fig))


def test_raw_simulation_time_used_when_no_display_units(
    positioned, basic_event_position_df
):
    fig = generate_animation(positioned, basic_event_position_df)

    assert frame_names(fig) == ["0", "10", "20", "30", "40", "50"]


# --------------------------------------------------------------------------- #
# Error paths
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("backend", typing.get_args(AnimationBackend))
def test_every_backend_literal_is_a_recognised_option(
    backend, positioned, basic_event_position_df
):
    """The annotation must not advertise a spelling the runtime check rejects.

    Deliberately does not assert that a figure comes back. The 'go' spellings
    reach the graph-objects branch and fail there for a separate, pre-existing
    reason - a numpy int64 handed to plotly as a trace name - which is out of
    scope here. What is pinned is the claim the annotation actually makes: that
    every advertised spelling is accepted *as a backend*.
    """
    try:
        generate_animation(positioned, basic_event_position_df, backend=backend)
    except ValueError as exc:
        assert "Invalid backend passed" not in str(exc)


@pytest.mark.parametrize("backend", ["EXPRESS", "Plotly Express", "GO", "Plotly Go"])
def test_backend_matching_is_case_insensitive(
    backend, positioned, basic_event_position_df
):
    """Both branches must treat case the same way.

    The express branch lowercased its input and the graph-objects branch did
    not, so 'EXPRESS' was accepted while 'GO' was rejected as an invalid
    backend - a difference with no reason behind it.
    """
    try:
        generate_animation(positioned, basic_event_position_df, backend=backend)
    except ValueError as exc:
        assert "Invalid backend passed" not in str(exc)


@pytest.mark.parametrize("unit", typing.get_args(SimulationTimeUnit))
def test_every_simulation_time_unit_literal_is_accepted(
    unit, positioned, basic_event_position_df
):
    fig = generate_animation(
        positioned,
        basic_event_position_df,
        simulation_time_unit=unit,
        start_date="2025-01-01",
        # Fine enough that even second-scale units get a distinct label per
        # snapshot, so this does not trip the coarse-display warning.
        time_display_units="dhms",
    )

    assert isinstance(fig, go.Figure)


def test_invalid_backend_raises_valueerror(positioned, basic_event_position_df):
    """Regression test: this raised the message as a bare string.

    `raise "some message"` produces `TypeError: exceptions must derive from
    BaseException`, so the intended guidance never reached the user.
    """
    with pytest.raises(ValueError, match="Invalid backend"):
        generate_animation(positioned, basic_event_position_df, backend="nonsense")


def test_invalid_time_display_units_raises_valueerror(
    positioned, basic_event_position_df
):
    """Regression test: also raised as a bare string."""
    with pytest.raises(ValueError, match="Invalid time_display_units"):
        generate_animation(
            positioned, basic_event_position_df, time_display_units="%Q%Q"
        )


def test_unknown_simulation_time_unit_raises_valueerror(
    positioned, basic_event_position_df
):
    """Regression test: left `unit` unbound and raised UnboundLocalError."""
    with pytest.raises(ValueError, match="Invalid `simulation_time_unit`"):
        generate_animation(
            positioned,
            basic_event_position_df,
            simulation_time_unit="fortnights",
            time_display_units="dhm",
        )


# --------------------------------------------------------------------------- #
# Background images
# --------------------------------------------------------------------------- #


def test_background_image_url_passed_through_unchanged():
    url = "https://example.com/plan.png"

    assert process_background_image_path(url) == url


def test_background_image_data_uri_passed_through_unchanged():
    uri = "data:image/png;base64,AAAA"

    assert process_background_image_path(uri) == uri


def test_local_background_image_becomes_data_uri(tmp_path):
    """Local paths are embedded so figures survive being moved between machines."""
    image = tmp_path / "plan.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    result = process_background_image_path(image)

    assert result.startswith("data:image/png;base64,")


def test_background_image_added_to_layout(
    positioned, basic_event_position_df, tmp_path
):
    image = tmp_path / "plan.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    fig = generate_animation(
        positioned,
        basic_event_position_df,
        add_background_image=str(image),
        background_image_opacity=0.25,
    )

    assert len(fig.layout.images) == 1
    assert fig.layout.images[0].source.startswith("data:image/png;base64,")
    assert fig.layout.images[0].opacity == 0.25


# --------------------------------------------------------------------------- #
# Background colours
# --------------------------------------------------------------------------- #


def test_bgcolors_left_untouched_by_default(positioned, basic_event_position_df):
    """With no override the active Plotly template keeps control of the colours."""
    fig = generate_animation(positioned, basic_event_position_df)

    assert fig.layout.plot_bgcolor is None
    assert fig.layout.paper_bgcolor is None


def test_plot_bgcolor_reaches_layout(positioned, basic_event_position_df):
    fig = generate_animation(
        positioned, basic_event_position_df, plot_bgcolor="white"
    )

    assert fig.layout.plot_bgcolor == "white"
    assert fig.layout.paper_bgcolor is None


def test_paper_bgcolor_reaches_layout(positioned, basic_event_position_df):
    fig = generate_animation(
        positioned, basic_event_position_df, paper_bgcolor="#f5f5f5"
    )

    assert fig.layout.paper_bgcolor == "#f5f5f5"
    assert fig.layout.plot_bgcolor is None


def test_animate_activity_log_forwards_bgcolors(
    simple_queue_log, basic_event_position_df
):
    fig = animate_activity_log(
        simple_queue_log,
        basic_event_position_df,
        limit_duration=50,
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    assert fig.layout.plot_bgcolor == "white"
    assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)"


# --------------------------------------------------------------------------- #
# animate_activity_log end to end
# --------------------------------------------------------------------------- #


def test_animate_activity_log_end_to_end(simple_queue_log, basic_event_position_df):
    fig = animate_activity_log(
        simple_queue_log, basic_event_position_df, limit_duration=50
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.frames) == 6


def test_animate_activity_log_honours_custom_time_column(basic_event_position_df):
    """limit_duration defaults from the caller's time column, not a literal 'time'.

    Regression test: the default read event_log["time"], so every user with a
    custom time column hit KeyError: 'time'.
    """
    log = pd.DataFrame(
        {
            "sim_time": [0, 5, 10, 15, 20, 25],
            "entity_id": [1, 1, 1, 2, 2, 2],
            "event_type": [
                "arrival_departure",
                "queue",
                "arrival_departure",
                "arrival_departure",
                "queue",
                "arrival_departure",
            ],
            "event": ["arrival", "waiting", "depart", "arrival", "waiting", "depart"],
        }
    )

    fig = animate_activity_log(
        log, basic_event_position_df, time_col_name="sim_time"
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.frames) > 0


def test_animate_activity_log_forwards_event_type_col_name(basic_event_position_df):
    """A custom event_type_col_name must reach generate_animation.

    Regression test: it was passed to reshape_for_animations and
    generate_animation_df but not generate_animation, whose queue_position hover
    logic then looked up a literal "event_type" column and died with
    KeyError: 'event_type'.
    """
    log = pd.DataFrame(
        {
            "time": [0, 0, 25, 5, 5, 35, 12, 12, 45],
            "entity_id": [1, 1, 1, 2, 2, 2, 3, 3, 3],
            "etype": [
                "arrival_departure",
                "queue",
                "arrival_departure",
                "arrival_departure",
                "queue",
                "arrival_departure",
                "arrival_departure",
                "queue",
                "arrival_departure",
            ],
            "event": [
                "arrival",
                "waiting",
                "depart",
                "arrival",
                "waiting",
                "depart",
                "arrival",
                "waiting",
                "depart",
            ],
        }
    )

    fig = animate_activity_log(
        log,
        basic_event_position_df,
        event_type_col_name="etype",
        limit_duration=50,
    )

    assert isinstance(fig, go.Figure)
    # The queue-position hover text is only produced when the "queue" rows are
    # recognised, which needs the custom column name to have been threaded through.
    rendered = [
        cell
        for frame in fig.frames
        for trace in frame.data
        if trace.customdata is not None
        for row in trace.customdata
        for cell in row
    ]
    assert any("Queue Position" in str(cell) for cell in rendered)


def test_animate_activity_log_matches_manual_pipeline(
    simple_queue_log, basic_event_position_df
):
    """The convenience wrapper must agree with running the three steps by hand."""
    combined = animate_activity_log(
        simple_queue_log, basic_event_position_df, limit_duration=50
    )

    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    positioned = generate_animation_df(reshaped, basic_event_position_df)
    manual = generate_animation(positioned, basic_event_position_df)

    assert frame_names(combined) == frame_names(manual)


# --------------------------------------------------------------------------- #
# add_repeating_overlay
# --------------------------------------------------------------------------- #


def test_overlay_adds_two_traces(positioned, basic_event_position_df):
    fig = generate_animation(positioned, basic_event_position_df)
    before = len(fig.data)

    add_repeating_overlay(
        fig,
        overlay_text="Closed",
        first_start_frame=1,
        on_duration_frames=2,
        off_duration_frames=2,
    )

    assert len(fig.data) == before + 2


def test_overlay_visibility_follows_on_off_cycle(
    positioned, basic_event_position_df
):
    """Frames inside the 'on' window carry overlay geometry; others are empty."""
    fig = generate_animation(positioned, basic_event_position_df)

    add_repeating_overlay(
        fig,
        overlay_text="Closed",
        first_start_frame=0,
        on_duration_frames=2,
        off_duration_frames=2,
    )

    # The source only switches on for i > start_frame, so frame 0 is always off
    # even when start_frame is 0. From frame 1 the cycle position is
    # (i - start) % 4, on while that is < 2: frames 1, 4, 5 on; 2, 3 off.
    visible = [len(frame.data[-1].x or []) > 0 for frame in fig.frames]

    assert visible == [False, True, False, False, True, True]


def test_overlay_on_figure_without_frames_is_a_no_op():
    fig = go.Figure()

    result = add_repeating_overlay(
        fig,
        overlay_text="Closed",
        first_start_frame=0,
        on_duration_frames=1,
        off_duration_frames=1,
    )

    assert result is fig
    assert len(result.data) == 0


def test_overlay_with_zero_cycle_length_is_a_no_op(
    positioned, basic_event_position_df
):
    fig = generate_animation(positioned, basic_event_position_df)
    before = len(fig.data)

    add_repeating_overlay(
        fig,
        overlay_text="Closed",
        first_start_frame=0,
        on_duration_frames=0,
        off_duration_frames=0,
    )

    assert len(fig.data) == before
