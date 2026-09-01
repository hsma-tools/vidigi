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


@pytest.fixture
def positioned(simple_queue_log, basic_event_position_df):
    """Output of the full prep pipeline, ready for generate_animation."""
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    return generate_animation_df(reshaped, basic_event_position_df)


@pytest.fixture
def positioned_with_resources(resource_log, basic_event_position_df):
    reshaped = reshape_for_animations(
        resource_log, every_x_time_units=10, limit_duration=50
    )
    return generate_animation_df(reshaped, basic_event_position_df)


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

    assert fig.data[-1].text == "🛏️"


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
