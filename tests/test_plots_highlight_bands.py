"""Tests for `vidigi.plots._add_highlight_bands`, the shared private helper
behind `highlight_bands=` on `plot_duration_distribution`, `plot_metric` and
`plot_resource_utilisation`.

Each band draws a filled rect shape plus, for every *explicit* bound, a
dashed line shape at that bound - an open bound (`None`) gets no boundary
line, since it isn't a real threshold, just padding out to the axis edge.
A labelled band also gets an invisible proxy `go.Scatter` marker trace for
its legend swatch.
"""

import plotly.graph_objects as go
import pytest

from vidigi.plots import _add_highlight_bands


def _rects(fig):
    return [s for s in fig.layout.shapes if s.type == "rect"]


def _lines(fig):
    return [s for s in fig.layout.shapes if s.type == "line"]


def test_no_bands_is_a_no_op():
    fig = go.Figure()
    _add_highlight_bands(fig, orientation="y", bands=None, value_min=0, value_max=10)
    assert fig.layout.shapes == ()
    assert fig.data == ()
    assert fig.layout.yaxis.range is None


def test_both_bounds_given_draws_the_exact_band_and_two_boundary_lines():
    fig = go.Figure()
    _add_highlight_bands(
        fig,
        orientation="y",
        bands=[{"lower": 2, "upper": 4, "colour": "orange"}],
        value_min=0,
        value_max=10,
    )
    rect = _rects(fig)[0]
    assert (rect.y0, rect.y1) == (2, 4)
    assert rect.fillcolor == "orange"
    lines = _lines(fig)
    assert sorted(line.y0 for line in lines) == [2, 4]


def test_open_lower_bound_extends_to_the_padded_data_minimum_not_the_boundary():
    """`upper=5` alone, against data range [0, 10]: the open (lower) end of
    the band reaches the margin-padded axis edge, but only the *explicit*
    bound (5) gets a dashed boundary line - the padded edge is not a
    threshold and must not be drawn as one. Mutation-proof: swapping which
    side gets the margin (e.g. clamping the open end to `value_min` with no
    margin) would move `rect.y0` to `0`, not `-1.5` - this assertion would
    catch that."""
    fig = go.Figure()
    _add_highlight_bands(
        fig,
        orientation="y",
        bands=[{"upper": 5, "colour": "green"}],
        value_min=0,
        value_max=10,
    )
    rect = _rects(fig)[0]
    # range = 10 (data) since 5 < 10; margin = 10 * 0.15 = 1.5
    assert rect.y0 == pytest.approx(-1.5)
    assert rect.y1 == 5
    lines = _lines(fig)
    assert len(lines) == 1
    assert lines[0].y0 == 5


def test_open_upper_bound_extends_to_the_padded_data_maximum():
    fig = go.Figure()
    _add_highlight_bands(
        fig,
        orientation="y",
        bands=[{"lower": 5, "colour": "red"}],
        value_min=0,
        value_max=10,
    )
    rect = _rects(fig)[0]
    assert rect.y0 == 5
    assert rect.y1 == pytest.approx(11.5)
    lines = _lines(fig)
    assert len(lines) == 1
    assert lines[0].y0 == 5


def test_an_explicit_bound_beyond_the_data_range_widens_the_axis_and_margin():
    """A band bound further out than the data itself (here `lower=20` against
    data max 10) must become part of what the margin is computed from, not
    be clamped to the data's own padded edge."""
    fig = go.Figure()
    _add_highlight_bands(
        fig,
        orientation="y",
        bands=[{"lower": 20, "colour": "red"}],
        value_min=0,
        value_max=10,
    )
    # raw range is now [0, 20], margin = 20 * 0.15 = 3.0
    assert fig.layout.yaxis.range == pytest.approx((-3.0, 23.0))
    rect = _rects(fig)[0]
    assert rect.y0 == 20
    assert rect.y1 == pytest.approx(23.0)


def test_multiple_bands_share_one_combined_axis_range():
    fig = go.Figure()
    _add_highlight_bands(
        fig,
        orientation="y",
        bands=[
            {"upper": 5, "colour": "green"},
            {"lower": 20, "colour": "red"},
        ],
        value_min=0,
        value_max=10,
    )
    assert len(_rects(fig)) == 2
    assert len(_lines(fig)) == 2
    # Both bands share the same axis pinning, computed from the combined extreme.
    assert fig.layout.yaxis.range == pytest.approx((-3.0, 23.0))


def test_labelled_band_adds_a_proxy_trace_with_a_matching_colour_swatch():
    fig = go.Figure()
    _add_highlight_bands(
        fig,
        orientation="y",
        bands=[{"upper": 5, "colour": "green", "label": "target"}],
        value_min=0,
        value_max=10,
    )
    assert len(fig.data) == 1
    proxy = fig.data[0]
    assert proxy.name == "target"
    assert proxy.marker.color == "green"
    assert proxy.showlegend is True
    assert proxy.x == (None,) and proxy.y == (None,)


def test_unlabelled_band_adds_no_proxy_trace():
    fig = go.Figure()
    _add_highlight_bands(
        fig,
        orientation="y",
        bands=[{"upper": 5, "colour": "green"}],
        value_min=0,
        value_max=10,
    )
    assert fig.data == ()


def test_orientation_x_draws_vrect_and_vline_instead():
    fig = go.Figure()
    _add_highlight_bands(
        fig,
        orientation="x",
        bands=[{"lower": 2, "upper": 4, "colour": "orange"}],
        value_min=0,
        value_max=10,
    )
    rect = _rects(fig)[0]
    assert (rect.x0, rect.x1) == (2, 4)
    assert fig.layout.xaxis.range is not None
    assert fig.layout.yaxis.range is None


def test_neither_bound_set_raises():
    fig = go.Figure()
    with pytest.raises(ValueError, match="lower.*upper"):
        _add_highlight_bands(
            fig, orientation="y", bands=[{"colour": "green"}], value_min=0, value_max=10
        )


def test_lower_gte_upper_raises():
    fig = go.Figure()
    with pytest.raises(ValueError, match="lower.*upper"):
        _add_highlight_bands(
            fig,
            orientation="y",
            bands=[{"lower": 5, "upper": 2}],
            value_min=0,
            value_max=10,
        )


def test_lower_equal_upper_raises():
    fig = go.Figure()
    with pytest.raises(ValueError, match="lower.*upper"):
        _add_highlight_bands(
            fig,
            orientation="y",
            bands=[{"lower": 5, "upper": 5}],
            value_min=0,
            value_max=10,
        )


def test_default_colour_is_red_and_default_opacity_is_012():
    fig = go.Figure()
    _add_highlight_bands(
        fig, orientation="y", bands=[{"upper": 5}], value_min=0, value_max=10
    )
    rect = _rects(fig)[0]
    assert rect.fillcolor == "red"
    assert rect.opacity == pytest.approx(0.12)


def test_zero_range_data_still_produces_a_non_zero_margin():
    """A single distinct value (`value_min == value_max`) would otherwise
    divide by/scale a zero range to a zero margin, collapsing the band to a
    zero-height sliver at the open end."""
    fig = go.Figure()
    _add_highlight_bands(
        fig, orientation="y", bands=[{"upper": 5}], value_min=5, value_max=5
    )
    rect = _rects(fig)[0]
    assert rect.y0 < 5
    assert rect.y1 == 5
