"""Tests for the synchronised-trace helpers in animation.py.

`add_subplot_panels`, `add_synchronised_trace` and
`add_synchronised_trace_from_dataframe` let a caller bolt an extra chart or
annotation onto a vidigi animation and keep it in step with the frames. The
manual way to do this (see `examples/example_13_...`) is fragile: it is easy to
desync the frame trace map and blank out the stage-label / resource-icon traces.
These tests pin that the helpers do not.
"""

import warnings

import pandas as pd
import plotly.graph_objects as go
import pytest

from vidigi.animation import (
    add_subplot_panels,
    add_synchronised_trace,
    add_synchronised_trace_from_dataframe,
    generate_animation,
)


@pytest.fixture
def anim(positioned, basic_event_position_df):
    """A plain animation: fig.data = [entities, stage_labels]; 6 frames."""
    return generate_animation(positioned, basic_event_position_df)


@pytest.fixture
def anim_with_resources(
    positioned_with_resources, basic_event_position_df, scenario_with_resources
):
    """fig.data = [entities, stage_labels, resource_markers]; 6 frames."""
    return generate_animation(
        positioned_with_resources,
        basic_event_position_df,
        scenario=scenario_with_resources,
        display_stage_labels=True,
    )


# --------------------------------------------------------------------------- #
# add_subplot_panels
# --------------------------------------------------------------------------- #


def test_subplot_panels_sets_grid_ref_and_new_axes(anim):
    add_subplot_panels(anim, row_heights=[0.75, 0.25], subplot_titles=["", "Panel"])

    assert anim._grid_ref is not None
    assert anim.layout.xaxis2 is not None
    assert anim.layout.yaxis2 is not None
    # Row 1 (the animation) now sits above row 2, not filling the whole height.
    assert anim.layout.yaxis.domain[1] <= 1.0
    assert anim.layout.yaxis.domain[0] > anim.layout.yaxis2.domain[1]


def test_subplot_panels_lets_a_trace_target_the_new_panel(anim):
    add_subplot_panels(anim, row_heights=[0.75, 0.25])

    anim.add_trace(go.Bar(x=[1], y=[1]), row=2, col=1)

    assert anim.data[-1].xaxis == "x2"
    assert anim.data[-1].yaxis == "y2"


def test_subplot_panels_hides_new_panel_axes_by_default(anim):
    add_subplot_panels(anim, row_heights=[0.6, 0.2, 0.2])

    for axis in (anim.layout.xaxis2, anim.layout.yaxis2, anim.layout.xaxis3):
        assert axis.showgrid is False
        assert axis.showticklabels is False


def test_subplot_panels_rejects_a_single_row(anim):
    with pytest.raises(ValueError, match="at least two"):
        add_subplot_panels(anim, row_heights=[1.0])


# --------------------------------------------------------------------------- #
# add_synchronised_trace
# --------------------------------------------------------------------------- #


def test_animated_trace_is_appended_to_every_frame_with_exact_trace_map(anim):
    # fig.data = [entity(0), stage_labels(1)]; each frame carries the entity
    # trace only, mapped to index 0.
    add_synchronised_trace(
        anim, lambda name, i: go.Scatter(x=[i], y=[i], mode="markers")
    )

    new_index = len(anim.data) - 1
    assert new_index == 2
    for frame in anim.frames:
        assert list(frame.traces) == [0, new_index]
        assert len(frame.data) == 2
        assert list(frame.data[-1].x) == [int(frame.name) // 10]


def test_static_trace_added_once_and_never_listed_in_a_frame(anim):
    n_before = len(anim.data)

    add_synchronised_trace(
        anim,
        lambda name, i: go.Scatter(x=[i], y=[i], mode="markers"),
        static_traces=go.Scatter(x=[0, 100], y=[1, 1], mode="lines", name="target"),
    )

    # static trace + one animated seed
    assert len(anim.data) == n_before + 2
    static_index = n_before  # static traces are added before the animated ones
    assert anim.data[static_index].name == "target"
    for frame in anim.frames:
        assert static_index not in list(frame.traces)


def test_existing_stage_label_and_resource_traces_survive(anim_with_resources):
    """Regression: the manual approach in example_13 blanks the stage-label and
    resource-icon traces the moment the frames are rewritten. This must not.

    Mutation check: replacing ``frame.traces = base_indices + animated_indices``
    with ``list(range(len(frame.data)))`` in add_synchronised_trace makes this
    fail - index 1 then lands in the frame map and the bar data overwrites the
    stage labels.
    """
    fig = anim_with_resources
    assert fig.data[1].mode == "text"  # stage labels
    assert fig.data[2].mode in ("markers", "markers+text")  # resource icons
    label_text = tuple(fig.data[1].text)
    resource_x = tuple(fig.data[2].x)

    add_synchronised_trace(
        fig, lambda name, i: go.Bar(x=[i], y=[i], xaxis="x2", yaxis="y2")
    )

    assert tuple(fig.data[1].text) == label_text
    assert fig.data[1].mode == "text"
    assert tuple(fig.data[2].x) == resource_x
    for frame in fig.frames:
        assert 1 not in list(frame.traces)
        assert 2 not in list(frame.traces)


def test_ragged_trace_count_raises_before_touching_the_figure(anim):
    n_before = len(anim.data)

    def frame_traces(name, i):
        if i == 0:
            return go.Scatter(x=[], y=[])
        return [go.Scatter(x=[], y=[]), go.Scatter(x=[], y=[])]

    with pytest.raises(ValueError, match="same number of traces"):
        add_synchronised_trace(anim, frame_traces)

    # aborted before any trace was added
    assert len(anim.data) == n_before
    assert all(frame.traces is None for frame in anim.frames)


def test_initial_traces_length_must_match(anim):
    with pytest.raises(ValueError, match="must match"):
        add_synchronised_trace(
            anim,
            lambda name, i: go.Scatter(x=[i], y=[i]),
            initial_traces=[go.Scatter(x=[0], y=[0]), go.Scatter(x=[0], y=[0])],
        )


def test_redraw_auto_enables_for_a_bar_trace(anim):
    add_synchronised_trace(anim, lambda name, i: go.Bar(x=[i], y=[i]))

    play_args = anim.layout.updatemenus[0].buttons[0].args[1]
    assert play_args["frame"]["redraw"] is True
    for slider in anim.layout.sliders:
        for step in slider["steps"]:
            assert step["args"][1]["frame"]["redraw"] is True


def test_redraw_not_enabled_for_a_plain_scatter_on_the_primary_axis(anim):
    add_synchronised_trace(
        anim, lambda name, i: go.Scatter(x=[i], y=[i], mode="markers")
    )

    play_args = anim.layout.updatemenus[0].buttons[0].args[1]
    # generate_animation leaves this at False; the helper must not flip it.
    assert play_args["frame"]["redraw"] is not True


def test_redraw_auto_enables_for_a_secondary_axis_scatter(anim):
    add_synchronised_trace(
        anim,
        lambda name, i: go.Scatter(x=[i], y=[i], mode="lines", xaxis="x2", yaxis="y2"),
    )

    play_args = anim.layout.updatemenus[0].buttons[0].args[1]
    assert play_args["frame"]["redraw"] is True


def test_explicit_redraw_false_overrides_auto(anim):
    add_synchronised_trace(anim, lambda name, i: go.Bar(x=[i], y=[i]), redraw=False)

    play_args = anim.layout.updatemenus[0].buttons[0].args[1]
    assert play_args["frame"]["redraw"] is not True


def test_figure_with_no_frames_warns_and_is_unchanged():
    fig = go.Figure(data=[go.Scatter(x=[1], y=[1])])

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = add_synchronised_trace(fig, lambda name, i: go.Scatter(x=[1], y=[1]))

    assert result is fig
    assert len(fig.data) == 1
    assert len(caught) == 1
    assert issubclass(caught[0].category, UserWarning)


# --------------------------------------------------------------------------- #
# add_synchronised_trace_from_dataframe
# --------------------------------------------------------------------------- #


@pytest.fixture
def per_snapshot_frame(positioned):
    """One row per animation snapshot, with a running value."""
    times = sorted(positioned["snapshot_time"].unique())  # [0, 10, 20, 30, 40, 50]
    return pd.DataFrame({"t": times, "value": [1, 2, 3, 4, 5, 6]})


def test_from_dataframe_snapshot_mode_feeds_one_time_step_per_frame(
    anim, per_snapshot_frame
):
    seen = []

    def make_trace(rows):
        seen.append(list(rows["value"]))
        return go.Bar(x=list(rows["t"]) or [None], y=list(rows["value"]) or [None])

    add_synchronised_trace_from_dataframe(
        anim, per_snapshot_frame, make_trace, frame_time_col="t", accumulate=False
    )

    # snapshot mode: exactly the current step's single row, every frame
    assert seen == [[1], [2], [3], [4], [5], [6]]
    for i, frame in enumerate(anim.frames):
        assert list(frame.data[-1].y) == [i + 1]


def test_from_dataframe_accumulate_mode_feeds_everything_up_to_the_frame(
    anim, per_snapshot_frame
):
    seen = []

    def make_trace(rows):
        seen.append(list(rows["value"]))
        return go.Scatter(x=list(rows["t"]), y=list(rows["value"]), mode="lines")

    add_synchronised_trace_from_dataframe(
        anim, per_snapshot_frame, make_trace, frame_time_col="t", accumulate=True
    )

    assert seen == [
        [1],
        [1, 2],
        [1, 2, 3],
        [1, 2, 3, 4],
        [1, 2, 3, 4, 5],
        [1, 2, 3, 4, 5, 6],
    ]
    # the last frame's line carries the whole series
    assert list(anim.frames[-1].data[-1].y) == [1, 2, 3, 4, 5, 6]


def test_from_dataframe_index_match_rejects_a_count_mismatch(anim):
    data = pd.DataFrame({"t": [0, 10], "value": [1, 2]})  # 2 times, 6 frames

    with pytest.raises(ValueError, match="one distinct value"):
        add_synchronised_trace_from_dataframe(
            anim,
            data,
            lambda rows: go.Bar(x=rows["t"], y=rows["value"]),
            frame_time_col="t",
            match="index",
        )


def test_from_dataframe_value_match_aligns_on_frame_name(anim):
    # Frame names are "0", "10", ... "50"; supply data for only two of them.
    data = pd.DataFrame({"t": ["10", "30"], "value": [5, 9]})

    def make_trace(rows):
        return go.Scatter(
            x=list(rows["t"]) or [None],
            y=list(rows["value"]) or [None],
            mode="markers",
        )

    add_synchronised_trace_from_dataframe(
        anim, data, make_trace, frame_time_col="t", match="value"
    )

    by_name = {frame.name: list(frame.data[-1].y) for frame in anim.frames}
    assert by_name == {
        "0": [None],
        "10": [5],
        "20": [None],
        "30": [9],
        "40": [None],
        "50": [None],
    }


def test_from_dataframe_unknown_time_column_raises(anim, per_snapshot_frame):
    with pytest.raises(ValueError, match="not a column"):
        add_synchronised_trace_from_dataframe(
            anim,
            per_snapshot_frame,
            lambda rows: go.Bar(x=[], y=[]),
            frame_time_col="nope",
        )
