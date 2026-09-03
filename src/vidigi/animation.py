import datetime as dt
import time
import warnings
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from vidigi.prep import (
    SnapshotAlignment,
    generate_animation_df,
    reshape_for_animations,
)
from vidigi.utils import (
    ICON_FLIP_MARKER,
    QueueDirection,
    _check_one_arrival_per_entity,
    _check_single_run,
    _enforce_int_params,
    _is_image_source,
    _resolve_direction_sign,
    _resolve_icon_flip,
    _resolve_icon_font,
    _resource_map_from_event_position_df,
    _warn_on_event_positions_outside_range,
    inject_icon_flip_css,
    inject_icon_font_css,
)
import numpy as np
from plotly.basedatatypes import BaseTraceType
from plotly.subplots import make_subplots
from typing import Callable, Literal, Optional, Sequence, TypeAlias, Union
import base64
import mimetypes
from pathlib import Path


# Which plotly API draws the animation. Several spellings of each are accepted, and
# matching is case-insensitive; the canonical forms are listed first. Editors offer
# these as completions, but the values are still validated at runtime, since
# annotations are not enforced.
AnimationBackend: TypeAlias = Literal[
    "express",
    "px",
    "plotly express",
    "go",
    "graph objects",
    "plotly graph objects",
    "plotly go",
]

# The real-world duration of one simulation time unit, used to turn snapshot times
# into datetimes. Each is also accepted in the singular.
SimulationTimeUnit: TypeAlias = Literal[
    "seconds",
    "second",
    "minutes",
    "minute",
    "hours",
    "hour",
    "days",
    "day",
    "weeks",
    "week",
    "months",
    "month",
    "years",
    "year",
]


def process_background_image_path(source):
    """
    Prepare a background image reference so it works reliably with Plotly.

    Plain local file paths are fragile and often fail when code runs from a
    different working directory or on another machine. This helper turns local
    paths into `data:` URIs so that background images are embedded directly
    in the figure and work consistently across environments. URLs and
    existing `data:` URIs are left unchanged.

    Parameters
    ----------
    source : str or pathlib.Path
        Local path to an image file, an HTTP(S) URL, or a `data:` URI.

    Returns
    -------
    str
        Value to use as the `source` argument to
        `Figure.add_layout_image`.
    """
    # Leave URLs and existing data URIs unchanged
    if isinstance(source, str) and source.startswith(("http://", "https://", "data:")):
        return source

    # Treat everything else as a local path
    path = Path(source)
    data = path.read_bytes()

    mime, _ = mimetypes.guess_type(path.name)
    if mime is None:
        # Fallback if the extension is unknown
        mime = "application/octet-stream"

    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


# Baseline figure margins (px). Auto-layout only ever grows a side past its
# floor - it never shrinks one - so a plain animation keeps Plotly's defaults.
_MARGIN_FLOORS = {"l": 80, "r": 80, "t": 100, "b": 80}
# Ceilings, so a pathological label or a tiny responsive figure can't hand the
# whole canvas over to the margin.
_MARGIN_CAPS = {"l": 400, "r": 450, "t": 250, "b": 300}


def _reconcile_grouped_traces(fig: go.Figure, categories) -> None:
    """Guarantee exactly one trace per `color=` category, in a fixed order, in
    `fig.data` and every frame.

    Plotly Express only creates a trace for a category in the frames where it
    actually has at least one point (confirmed on plotly.js 6.7 and 5.12) - a
    category absent from a given frame (no `entity_colour_by` value of that kind
    present at that moment - including the very first frame, "frame 0" being what
    `fig.data` itself represents) is silently dropped from that frame's trace list
    entirely, rather than getting an empty placeholder the way an individual
    entity does. A category that never appears in the first frame would be
    missing from the animation outright; one only some entities have would wink
    in and out as they arrive and depart. This finds one real occurrence of each
    category (wherever it happens to exist) to carry its colour and legend
    grouping over, and fills in an empty placeholder trace - the same idiom the
    `go` backend already uses per entity - everywhere else.
    """

    def _find_template(category):
        for trace in fig.data:
            if trace.name == category:
                return trace
        for frame in fig.frames or ():
            for trace in frame.data:
                if trace.name == category:
                    return trace
        return None

    templates = {category: _find_template(category) for category in categories}

    def _placeholder(category):
        template = templates[category]
        marker_color = template.marker.color if template is not None else None
        return go.Scatter(
            x=[None],
            y=[None],
            text=[None],
            mode="markers+text",
            name=category,
            # Null x/y already draw nothing, so a trace-level `opacity=0` isn't
            # needed for *this* frame - and setting one anyway is actively
            # harmful: Plotly's frame animation only patches attributes a frame
            # explicitly sets, and a real (non-placeholder) trace from px never
            # sets a trace-level `opacity` (only `marker.opacity`, applied
            # uniformly - see the `opacity=0` passed to `px.scatter` above). So a
            # trace-level 0 here would never get reset back to 1, leaving a
            # category invisible for the rest of the animation once it does have
            # entities, if it happened to be empty in the frame that first
            # created this placeholder.
            marker=dict(opacity=0, color=marker_color),
            legendgroup=category,
            showlegend=getattr(template, "showlegend", None) if template is not None else None,
        )

    # `fig.data = (...)` only accepts a permutation of fig's *own* existing traces -
    # new ones have to be added first, then the whole set reordered into place.
    _base_names = {trace.name for trace in fig.data}
    missing = [category for category in categories if category not in _base_names]
    if missing:
        fig.add_traces([_placeholder(category) for category in missing])
    by_name = {trace.name: trace for trace in fig.data}
    fig.data = tuple(by_name[category] for category in categories)

    # `go.Frame.data` carries no such restriction - a frame is not a `BaseFigure`.
    for frame in fig.frames or ():
        existing = {trace.name: trace for trace in frame.data}
        frame.data = tuple(
            existing[category] if category in existing else _placeholder(category)
            for category in categories
        )


def _disable_axis_clipping(fig: go.Figure) -> None:
    """Stop Plotly clipping scatter markers/text at the axis line.

    Stage labels are drawn past the rightmost event anchor and queue/resource
    icons are drawn left of their anchor, so with the default
    ``cliponaxis=True`` any content outside the data range is chopped at the
    plot edge. Turning it off lets that content render into the figure margin
    (which :func:`_overflow_margin_updates` enlarges to fit it).
    """
    for trace in fig.data:
        if trace.type == "scatter":
            trace.cliponaxis = False
    for frame in fig.frames or ():
        for trace in frame.data:
            if getattr(trace, "type", None) == "scatter":
                try:
                    trace.cliponaxis = False
                except (ValueError, TypeError):
                    # Frame data stored as a bare dict - the base trace it
                    # merges onto already carries cliponaxis=False.
                    pass


def _series_min(df: Optional[pd.DataFrame], col: str) -> Optional[float]:
    """Smallest finite value in ``df[col]``, or ``None`` if unavailable."""
    if df is None or col not in getattr(df, "columns", []) or not len(df):
        return None
    value = pd.to_numeric(df[col], errors="coerce").min()
    return float(value) if pd.notna(value) else None


def _series_max(df: Optional[pd.DataFrame], col: str) -> Optional[float]:
    """Largest finite value in ``df[col]``, or ``None`` if unavailable."""
    if df is None or col not in getattr(df, "columns", []) or not len(df):
        return None
    value = pd.to_numeric(df[col], errors="coerce").max()
    return float(value) if pd.notna(value) else None


def _overflow_margin_updates(
    *,
    event_position_df: pd.DataFrame,
    entity_df: Optional[pd.DataFrame],
    resource_df: Optional[pd.DataFrame],
    x_max: float,
    y_max: float,
    text_size: int,
    plotly_width: Optional[int],
    plotly_height: Optional[int],
    display_stage_labels: bool,
    queue_direction: QueueDirection = "left",
) -> dict:
    """Figure-margin overrides that keep auto-positioned content on-canvas.

    The data ranges are deliberately left untouched - widening them would
    rescale every diagram built without ``override_x_max`` / ``override_y_max``
    and shift alignment against background images. Instead the margin grows so
    ``cliponaxis=False`` content has somewhere to go. Returns only the sides
    that need to exceed :data:`_MARGIN_FLOORS`; an empty dict means "leave the
    margins alone".
    """
    need = dict(_MARGIN_FLOORS)

    ref_w = plotly_width or 700
    ref_h = plotly_height or 900

    # Stage labels are drawn just past the anchor - to the right of a
    # left-building queue, to the left of a right-building one. Reserve room for
    # the longest label on whichever side(s) it actually falls. ~0.55 em per
    # character for a proportional font, plus the 10-unit trace offset and a
    # little breathing room.
    if display_stage_labels and "label" in getattr(event_position_df, "columns", []):
        label_sign = _resolve_direction_sign(event_position_df, queue_direction)
        left_lens = [
            len(str(s))
            for s, sign in zip(event_position_df["label"].to_list(), label_sign)
            if sign > 0
        ]
        right_lens = [
            len(str(s))
            for s, sign in zip(event_position_df["label"].to_list(), label_sign)
            if sign <= 0
        ]
        if right_lens:
            need["r"] = max(right_lens) * 0.55 * text_size + 20
        if left_lens:
            need["l"] = max(need["l"], max(left_lens) * 0.55 * text_size + 20)

    # Top: a label vertically centred on the topmost anchor overhangs upwards
    # by about half its height.
    if display_stage_labels:
        need["t"] = max(need["t"], text_size * 1.5)

    # Left / bottom: how far, in pixels, the furthest queue or resource icon
    # sits outside [0, .]. Converted from data units via the axis span and a
    # reference figure size (the real width is often unknown at build time).
    x_candidates = [0.0]
    for value in (_series_min(entity_df, "x_final"), _series_min(resource_df, "x_final")):
        if value is not None:
            x_candidates.append(value)
    x_min_data = min(x_candidates)

    y_candidates = [0.0]
    entity_y_min = _series_min(entity_df, "y_final")
    if entity_y_min is not None:
        y_candidates.append(entity_y_min)
    resource_y_min = _series_min(resource_df, "y_final")
    if resource_y_min is not None:
        # resource icons are drawn 10 units below their y_final
        y_candidates.append(resource_y_min - 10)
    y_min_data = min(y_candidates)

    # Right: how far the furthest right-building queue or resource icon sits
    # past x_max (the mirror of the left-margin logic below).
    x_candidates_hi = [x_max]
    for value in (_series_max(entity_df, "x_final"), _series_max(resource_df, "x_final")):
        if value is not None:
            x_candidates_hi.append(value)
    x_max_data = max(x_candidates_hi)

    if x_max and x_min_data < 0:
        need["l"] = max(
            need["l"], (-x_min_data) / (x_max - x_min_data) * ref_w + 20
        )
    if y_max and y_min_data < 0:
        need["b"] = (-y_min_data) / (y_max - y_min_data) * ref_h + 20
    if x_max and x_max_data > x_max:
        need["r"] = max(
            need["r"],
            (x_max_data - x_max) / (x_max_data - x_min_data) * ref_w + 20,
        )

    return {
        side: int(min(value, _MARGIN_CAPS[side]))
        for side, value in need.items()
        if value > _MARGIN_FLOORS[side]
    }


@_enforce_int_params(["plotly_height"])
def generate_animation(
    full_entity_df_plus_pos: pd.DataFrame,
    event_position_df: pd.DataFrame,
    scenario: Optional[object] = None,
    time_col_name: str = "time",
    entity_col_name: str = "entity_id",
    event_col_name: str = "event",
    event_type_col_name: str = "event_type",
    resource_col_name: str = "resource_id",
    simulation_time_unit: SimulationTimeUnit = "minutes",
    plotly_height: int = 900,
    plotly_width: Optional[int] = None,
    include_play_button: bool = True,
    add_background_image: Optional[str] = None,
    display_stage_labels: bool = True,
    entity_icon_size: int = 24,
    text_size: int = 24,
    hover_text_entity: Optional[str] = "default",
    custom_hover_data: Optional[list[str]] = None,
    resource_icon_size: int = 24,
    override_x_max: Optional[int] = None,
    override_y_max: Optional[int] = None,
    time_display_units: Optional[int] = None,
    start_date: Optional[str] = None,
    start_time: Optional[str] = None,
    resource_opacity: float = 0.8,
    custom_resource_icon: Optional[str] = None,
    wrap_resources_at: Optional[int] = 20,
    gap_between_resources: int = 10,
    gap_between_resource_rows: int = 30,
    queue_direction: QueueDirection = "left",
    flip_entity_icons: bool = False,
    entity_icon_font: Optional[str] = None,
    entity_icon_font_weight: Optional[int] = None,
    entity_colour_by: Optional[str] = None,
    entity_colour_map: Optional[dict] = None,
    show_entity_legend: bool = True,
    entity_annotation_by: Optional[str] = None,
    entity_annotation_size: int = 14,
    entity_annotation_color: str = "black",
    entity_annotation_offset_y: float = -15,
    resource_image_size: Optional[float] = None,
    setup_mode: bool = False,
    frame_duration: int = 400,  # milliseconds
    frame_transition_duration: int = 600,  # milliseconds
    debug_mode: bool = False,
    background_image_opacity: float = 0.5,
    overflow_text_color: str = "black",
    stage_label_text_colour: str = "black",
    plot_bgcolor: Optional[str] = None,
    paper_bgcolor: Optional[str] = None,
    backend: AnimationBackend = "express",
    run_col_name: Optional[str] = "auto",
) -> go.Figure:
    """
    Generate an animated visualization of patient flow through a system.

    This function creates an interactive Plotly animation based on patient data
    and event positions.

    Parameters
    ----------
    full_entity_df_plus_pos : pd.DataFrame
        DataFrame containing entity data with position information. This will
        be the output of passing an event log through the
        reshape_for_animations() and generate_animation_df() functions.
    event_position_df : pd.DataFrame
        DataFrame specifying the positions of different events.
    scenario : object, optional
        Object whose attributes give the number of each resource available at a
        step, e.g. ``scenario.n_nurses`` (default is None). Used for two
        independent things:

        - Drawing the resource-availability icons at each stage. This also needs
          a ``resource`` column on ``event_position_df`` naming the attribute to
          read for that step (e.g. ``resource="n_nurses"``).
        - Appending the resource identifier column (``resource_col_name``,
          "resource_id" by default) to the hover ``customdata``, so a custom
          ``hover_text_entity`` template can display it. This happens only when
          the event log actually contains that column, i.e. the model logged
          resource use via ``log_resource_use_start`` / ``log_resource_use_end``.
          The built-in default template does not reference it, and a scenario
          passed for a model with no resource-use logging is harmless - the
          column is simply not appended.
    time_col_name : str, optional
        Name of the column in `event_log` that contains the timestamp of each
        event (default is "time"). Timestamps should represent the number of
        time units since the simulation began.
    entity_col_name : str, optional
        Name of the column in `event_log` that contains the unique identifier
        for each entity (e.g., "entity_id", "entity", "patient", "patient_id",
        "customer", "ID") (default is "entity_id").
    event_col_name : str, optional
        Name of the column in `event_log` that specifies the actual event that
        occurred (default is "event").
    event_type_col_name : str, optional
        Name of the column in `event_log` that specifies the category of the
        event (default is "event_type"). Supported event types include
        'arrival_departure', 'resource_use', 'resource_use_end', and 'queue'.
    resource_col_name : str, optional
        Name of the column for the resource identifier (default is
        "resource_id"). Used for 'resource_use' events.
    simulation_time_unit: str, optional
        Time unit used within the simulation (default is "minutes"). Possible
        values are 'seconds', 'minutes', 'hours', 'days', 'weeks', 'years'.
    plotly_height : int, optional
        Height of the Plotly figure in pixels (default is 900).
    plotly_width : int, optional
        Width of the Plotly figure in pixels (default is None).
    include_play_button : bool, optional
        Whether to include a play button in the animation (default is True).
    add_background_image : str, optional
        Path to a background image file to add to the animation (default is
        None).
    display_stage_labels : bool, optional
        Whether to display labels for each stage (default is True).
    entity_icon_size : int, optional
        Size of entity icons in the animation (default is 24).
    text_size : int, optional
        Size of text labels in the animation (default is 24).
    hover_text_entity: str, optional
        String to define the hover text. If None, hover on entity icons will be
        disabled. Default will display the entity ID, their current time in the
        system, etc. Must be provided in the format
        "%{customdata[0]} some text" etc.
        See https://plotly.com/python/hover-text-and-formatting/#customizing-hover-text-with-a-hovertemplate
        for full details. It is recommended you pair this with custom_hover_data to have control
        over the order of column names present in the customdata list.
    custom_hover_data: list of str, optional
        A list of column names, which must be defined as strings. If provided,
        becomes a list of additional columns that can be accessed as part of
        the string defined within hover_text_entity. customdata[0] is the first
        column specified customdata[1] is the second etc. So e.g. if you pass
        in ["widgets_created_cumulative"] as your custom_hover_data, your
        hover_text_entity may be "Widgets created so far: %{customdata[0]}".
        When ``scenario`` is set and the event log has a ``resource_col_name``
        column, that column is appended to the list automatically, landing at
        ``customdata[len(custom_hover_data)]``.
        Because ``custom_hover_data`` replaces the fixed column list the default
        ``hover_text_entity`` template indexes, you must also pass your own
        ``hover_text_entity`` string - supplying ``custom_hover_data`` while
        leaving ``hover_text_entity`` at its default raises ``ValueError``.
    resource_icon_size : int, optional
        Size of resource icons in the animation (default is 24).
    override_x_max : int, optional
        Override the maximum x-coordinate (default is None). The figure margin
        already auto-expands to fit auto-generated stage labels, so this is only
        needed to reframe a layout the auto-sizing gets wrong. The axis then runs
        exactly ``[0, override_x_max]``; a `UserWarning` is raised if any event
        anchor falls outside that, as its queue / resources would be drawn
        off-canvas.
    override_y_max : int, optional
        Override the maximum y-coordinate (default is None). Same off-canvas
        `UserWarning` as `override_x_max`.
    time_display_units : str, optional
        Format for displaying time on the animation timeline. This affects how
        simulation time is converted into human-readable dates or clock
        formats. If `None` (default), the raw simulation time is used.

        Predefined options:

        - 'dhms' : Day Month Year + HH:MM:SS (e.g., "06 June 2025 14:23:45")
        - 'dhms_ampm' : Same as 'dhms', but in 12-hour format with AM/PM
          (e.g., "06 June 2025 02:23:45 PM")
        - 'dhm' : Day Month Year + HH:MM (e.g., "06 June 2025 14:23")
        - 'dhm_ampm' : 12-hour format with AM/PM
        - (e.g., "06 June 2025 02:23 PM")
        - 'dh' : Day Month Year + HH (e.g., "06 June 2025 14")
        - 'dh_ampm' : 12-hour format with AM/PM (e.g., "06 June 2025 02 PM")
        - 'd' : Full weekday and date (e.g., "Friday 06 June 2025")
        - 'm' : Month and year (e.g., "June 2025")
        - 'y' : Year only (e.g., "2025")
        - 'day_clock' or 'simulation_day_clock' : Show simulation-relative day
           and time (e.g., "Simulation Day 3 14:15")
        - 'day_clock_ampm' or 'simulation_day_clock_ampm' : Same as above, but
           time is shown in 12-hour clock with AM/PM
           (e.g., "Simulation Day 3 02:15 PM")

        Alternatively, you can supply a custom strftime (https://strftime.org/)
        format string (e.g., '%Y-%m-%d %H') to control the display manually.
    start_date : str, optional
        Start date for the animation in 'YYYY-MM-DD' format. Only used when
        time_display_units is 'd' or 'dhm' (default is None).
    start_time : str, optional
        Start time for the animation in 'HH:MM:SS' format. Only used when
        time_display_units is 'd' or 'dhm' (default is None).
    resource_opacity : float, optional
        Opacity of resource icons (default is 0.8).
    custom_resource_icon : str, optional
        Custom icon to use for resources (default is None).
    wrap_resources_at : int, optional
        Number of resources to show before wrapping to a new row (default is
        20). If this has been set elsewhere, it is also important to set it in
        this function to ensure the visual indicators of the resources wrap in
        the same way the entities using those resources do.
    gap_between_resources : int, optional
        Spacing between resources in pixels (default is 10).
    gap_between_resource_rows : int, optional
        Vertical spacing between rows in pixels (default is 30).
    queue_direction : {"left", "right"}, default="left"
        Which way queues (and rows of resources) build out from their anchor.
        "left" is the historic behaviour - the anchor is the front of the queue
        and entities stack up to its left. "right" mirrors this, so the anchor
        becomes the bottom-left corner and the queue extends rightwards, which
        suits entity emojis that face right. Stage labels flip to the opposite
        side of a right-building queue. If set here it must also be set on
        `generate_animation_df`; overridden per event by a `direction` column
        on `event_position_df`.
    flip_entity_icons : bool, default=False
        Mirror entity icons (and a `custom_resource_icon`) horizontally - useful
        when an emoji faces the wrong way for a particular layout, independently
        of `queue_direction`. Overridden per event by a `flip_icons` column on
        `event_position_df` (or `EventPosition(..., flip_icons=...)`). Requires
        CSS to reach the page - this is injected automatically (see
        `vidigi.utils.inject_icon_flip_css`) whenever any icon actually resolves
        to flipped; embedding the figure a different way may need
        `vidigi.utils.entity_icon_flip_css()` added explicitly. Does not affect
        a static export via `fig.write_image()`.
    entity_icon_font : str, optional
        Render entity icons (and a `custom_resource_icon`) in an icon font
        instead of emoji - lets an icon be any glyph the font provides, and,
        because icon fonts are monochrome rather than colour fonts, is what
        makes `entity_colour_by` visible on the icon itself. One of
        `vidigi.utils.ICON_FONT_PRESETS` (currently `"font-awesome"`,
        `"bootstrap-icons"`, `"material-symbols"`), or any CSS font-family name
        already available on the page. `custom_entity_icon_list` then supplies
        that font's codepoints (or, for `"material-symbols"`, ligature names
        like `"directions_walk"`) instead of emoji. The overflow `+ N more` /
        ASCII-gauge icon is always left on the default font, whatever this is
        set to - seeing tofu or a substituted glyph in place of ASCII art would
        be worse than the plain text. See `vidigi.utils.entity_icon_font_css`
        for what reaching the page involves and two Plotly quirks it works
        around; like `flip_entity_icons`, the CSS is injected automatically.
    entity_icon_font_weight : int, optional
        Overrides a preset's default weight (Font Awesome ships Solid at 900
        and Regular at 400, say). Ignored for a raw custom family in
        `entity_icon_font` - most fonts have only one.
    entity_colour_by : str, optional
        Name of a column - typically one already on your event log, such as
        `priority` or `pathway` - to colour entity icons by by. Unlike emoji,
        which are colour fonts and ignore `textfont.color` entirely, this only
        has a visible effect together with `entity_icon_font`. Overflow rows
        keep `overflow_text_color` and are never coloured or added to the
        legend, whatever category they would otherwise fall into.
    entity_colour_map : dict, optional
        Maps values of `entity_colour_by` to specific colours, e.g.
        `{"high": "crimson", "low": "steelblue"}`. A value with no entry falls
        back to Plotly's default qualitative palette.
    show_entity_legend : bool, default=True
        Show a legend for `entity_colour_by`. Ignored when `entity_colour_by`
        is not set - there is nothing to key.
    entity_annotation_by : str, optional
        Name of a column to draw as a second line of text offset below each
        entity's icon - e.g. a running length-of-stay figure or a delay flag.
        Express backend only (see `backend`). Appending extra text directly
        onto `icon`/`icon_display` is cheaper and is what vidigi has always
        drawn - prefer it whenever `flip_entity_icons`/`entity_icon_font`
        aren't in play for this animation. It stops working once either of
        those is combined with baked-in text, though: Plotly gives a single
        SVG `<text>` node one `font-family` and one transform, so flipping or
        re-fonting the icon does the same to any text appended into the same
        string. `entity_annotation_by` draws the annotation as a genuinely
        separate scatter trace instead, so it is structurally untouched by
        either - at the cost of roughly doubling the per-frame point/text
        payload for every entity, for the whole animation. `None` (default)
        draws no second trace at all. Raises `ValueError` if the column isn't
        found, matching `entity_colour_by`.
    entity_annotation_size : int, default=14
        Font size (in points) of the `entity_annotation_by` text. Independent
        of `entity_icon_size`.
    entity_annotation_color : str, default="black"
        Colour of the `entity_annotation_by` text. Independent of
        `entity_colour_by`/`overflow_text_color`.
    entity_annotation_offset_y : float, default=-15
        Vertical offset, in data units (the same units as
        `event_position_df`'s `x`/`y`), of `entity_annotation_by` text below
        (negative) or above (positive) each entity's icon. Given its own
        literal default rather than derived from an unrelated spacing
        argument - check it against your `entity_icon_size` if icons and
        annotations start to overlap.
    resource_image_size : float, optional
        Size, in data units (the same units as `event_position_df`'s `x`/`y`),
        of an image `resource_icon` (see `EventPosition.resource_icon`).
        Defaults to `resource_icon_size`, kept independent of
        `gap_between_resources` so changing the spacing between resources
        doesn't also change their size. Has no effect on a text glyph
        resource icon, which is sized by `resource_icon_size` as before.
    setup_mode : bool, optional
        Whether to run in setup mode, showing grid and tick marks (default is
        False).
    frame_duration : int, optional
        Duration of each frame in milliseconds (default is 400).
    frame_transition_duration : int, optional
        Duration of transition between frames in milliseconds (default is 600).
    debug_mode : bool, optional
        Whether to run in debug mode with additional output (default is False).
    background_image_opacity : float, optional
        Opacity (0 is transparent, to 1, completely opaque) of the provided
        background image
    overflow_text_color : str, optional
        Color of the text displayed on top of entity icons in the animation
        (default is black).
    stage_label_text_colour : str, optional
        Color of the stage label text added next to each event position when
        display_stage_labels is True (default is black).
    plot_bgcolor : str, optional
        Background colour of the plotting area (inside the axes), passed
        straight to ``fig.update_layout(plot_bgcolor=...)``. Accepts any CSS
        colour string, e.g. "white" or "#f5f5f5". If None (default), Plotly's
        template default is left untouched.
    paper_bgcolor : str, optional
        Background colour of the area surrounding the plotting area (behind the
        title, play button and timeline), passed straight to
        ``fig.update_layout(paper_bgcolor=...)``. Accepts any CSS colour string.
        If None (default), Plotly's template default is left untouched.
    backend: str, optional
        EXPERIMENTAL. Whether to use the plotly express backend for the initial
        plot (default), or the experimental plotly go backend. The go approach
        is currently unstable and much slower. Use at your own risk.
    run_col_name : str or None, optional
        Name of the column identifying which simulation run (replication) each
        row belongs to, used to reject data containing more than one
        replication. Default is "auto", which looks for a column named
        (case-insensitively) one of 'run', 'run_number', 'replication', 'rep' or
        'run_id'. Pass an explicit column name to override the search, or `None`
        to disable the check.

    Returns
    -------
    plotly.graph_objs._figure.Figure
        An animated Plotly figure object representing the patient flow.

    Notes
    -----
    - **This function animates a single replication only.** Data containing more
      than one run is rejected with a `ValueError`, because the runs would
      otherwise be blended into an animation representing no run of your model.
    - The function uses Plotly Express to create an animated scatter plot.
    - Time can be displayed as actual dates or as model time units.
    - The animation supports customization of icon sizes, resource
      representation, and animation speed.
    - A background image can be added to provide context for the patient flow.
    - If `time_display_units` is specified, the simulation time is converted
      into real-world datetimes using the `simulation_time_unit` and optionally
      `start_date` and `start_time`.
    - If `start_date` and/or `start_time` are not provided, a default offset
      from today's date is used.
    - The `snapshot_time` column is transformed to datetime strings, and a
      `snapshot_time_display` column is created for visual display.
    """
    # The run column survives both earlier pipeline stages, so a multi-replication
    # frame that reached this far is still caught rather than animated as a blend.
    _check_single_run(
        full_entity_df_plus_pos,
        run_col_name=run_col_name,
        frame_arg="full_entity_df_plus_pos",
    )

    full_entity_df_plus_pos_copy = full_entity_df_plus_pos.copy()

    if override_x_max is not None:
        x_max = override_x_max
    else:
        x_max = event_position_df["x"].max() * 1.25

    if override_y_max is not None:
        y_max = override_y_max
    else:
        y_max = event_position_df["y"].max() * 1.1

    # A caller-supplied override becomes the axis bound directly, so an event
    # anchor outside it is drawn off-canvas and that step disappears silently.
    _warn_on_event_positions_outside_range(
        event_position_df,
        override_x_max=override_x_max,
        override_y_max=override_y_max,
        event_col_name=event_col_name,
        stacklevel=3,
    )

    # If we're displaying time as a clock instead of as units of whatever time
    # our model is working in, create a snapshot_time_display column that will
    # display as a pseudo datetime

    # We need to keep the original snapshot time and exact time columns in
    # existence because they're important for sorting
    full_entity_df_plus_pos_copy["snapshot_time_base"] = full_entity_df_plus_pos_copy[
        "snapshot_time"
    ]

    # Assuming time display units are set to something other

    if time_display_units is not None:
        if simulation_time_unit in ("second", "seconds"):
            unit = "s"
        elif simulation_time_unit in ("minute", "minutes"):
            unit = "m"
        elif simulation_time_unit in ("hour", "hours"):
            unit = "h"
        elif simulation_time_unit in ("day", "days"):
            unit = "d"
        elif simulation_time_unit in ("week", "weeks"):
            unit = "w"
        elif simulation_time_unit in ("month", "months"):
            # Approximate 1 month as 30 days
            full_entity_df_plus_pos_copy["snapshot_time"] *= 30
            unit = "d"
        elif simulation_time_unit in ("year", "years"):
            # Approximate 1 year as 365 days
            full_entity_df_plus_pos_copy["snapshot_time"] *= 365
            unit = "d"
        else:
            raise ValueError(
                f"Invalid `simulation_time_unit` '{simulation_time_unit}'. Valid options "
                f"are: 'seconds', 'minutes', 'hours', 'days', 'weeks', 'months', 'years' "
                f"(each also accepted in the singular)."
            )

        if start_date is None and start_time is None:
            full_entity_df_plus_pos_copy["snapshot_time"] = (
                dt.date.today()
                + pd.DateOffset(days=165)
                + pd.to_timedelta(
                    full_entity_df_plus_pos_copy["snapshot_time"], unit=unit
                )
            )

        elif start_date is not None and start_time is None:
            full_entity_df_plus_pos_copy["snapshot_time"] = dt.datetime.strptime(
                start_date, "%Y-%m-%d"
            ) + pd.to_timedelta(
                full_entity_df_plus_pos_copy["snapshot_time"], unit=unit
            )

        else:
            start_time_dt = dt.datetime.strptime(start_time, "%H:%M:%S")

            start_time_time_delta = dt.timedelta(
                hours=start_time_dt.hour,
                minutes=start_time_dt.minute,
                seconds=start_time_dt.second,
            )

            if start_date is None:
                full_entity_df_plus_pos_copy["snapshot_time"] = (
                    dt.date.today()
                    + pd.DateOffset(days=165)
                    + start_time_time_delta
                    + pd.to_timedelta(
                        full_entity_df_plus_pos_copy["snapshot_time"],
                        unit=unit,
                    )
                )

            else:
                full_entity_df_plus_pos_copy["snapshot_time"] = (
                    dt.datetime.strptime(start_date, "%Y-%m-%d")
                    + start_time_time_delta
                    + pd.to_timedelta(
                        full_entity_df_plus_pos_copy["snapshot_time"],
                        unit=unit,
                    )
                )

        # https://strftime.org/
        if time_display_units in ("dhms", "dhms_ampm"):
            fmt = (
                "%d %B %Y\n%I:%M:%S %p"
                if time_display_units.endswith("ampm")
                else "%d %B %Y\n%H:%M:%S"
            )
            full_entity_df_plus_pos_copy["snapshot_time_display"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, fmt)
                )
            )
            full_entity_df_plus_pos_copy["snapshot_time"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, fmt)
                )
            )

        elif time_display_units in ("dhm", "dhm_ampm"):
            fmt = (
                "%d %B %Y\n%I:%M %p"
                if time_display_units.endswith("ampm")
                else "%d %B %Y\n%H:%M"
            )
            full_entity_df_plus_pos_copy["snapshot_time_display"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, fmt)
                )
            )
            full_entity_df_plus_pos_copy["snapshot_time"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, fmt)
                )
            )

        elif time_display_units in ("dh", "dh_ampm"):
            fmt = (
                "%d %B %Y\n%I %p"
                if time_display_units.endswith("ampm")
                else "%d %B %Y\n%H"
            )
            full_entity_df_plus_pos_copy["snapshot_time_display"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, fmt)
                )
            )
            full_entity_df_plus_pos_copy["snapshot_time"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, fmt)
                )
            )

        elif time_display_units in ("d"):
            full_entity_df_plus_pos_copy["snapshot_time_display"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, "%A %d %B %Y")
                )
            )
            full_entity_df_plus_pos_copy["snapshot_time"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, "%Y-%m-%d")
                )
            )

        elif time_display_units in ("m"):
            full_entity_df_plus_pos_copy["snapshot_time_display"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, "%B %Y")
                )
            )
            full_entity_df_plus_pos_copy["snapshot_time"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, "%B %Y")
                )
            )

        elif time_display_units in ("y"):
            full_entity_df_plus_pos_copy["snapshot_time_display"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, "%Y")
                )
            )
            full_entity_df_plus_pos_copy["snapshot_time"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, "%Y")
                )
            )
        elif time_display_units in (
            "day_clock",
            "simulation_day_clock",
            "day_clock_ampm",
            "simulation_day_clock_ampm",
        ):
            use_ampm = time_display_units.endswith("_ampm")

            def format_day_clock(t):
                delta = t - pd.Timestamp(t.date())
                sim_day = (
                    t.normalize()
                    - full_entity_df_plus_pos_copy["snapshot_time"].min().normalize()
                ).days + 1
                time_fmt = "%I:%M %p" if use_ampm else "%H:%M"
                return f"Simulation Day {sim_day}\n{t.strftime(time_fmt)}"

            full_entity_df_plus_pos_copy["snapshot_time_display"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: format_day_clock(pd.to_datetime(x))
                )
            )
            full_entity_df_plus_pos_copy["snapshot_time"] = (
                full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: format_day_clock(pd.to_datetime(x))
                )
            )
        else:
            try:
                full_entity_df_plus_pos_copy["snapshot_time_display"] = (
                    full_entity_df_plus_pos_copy["snapshot_time"].apply(
                        lambda x: dt.datetime.strftime(x, time_display_units)
                    )
                )
                full_entity_df_plus_pos_copy["snapshot_time"] = (
                    full_entity_df_plus_pos_copy["snapshot_time"].apply(
                        lambda x: dt.datetime.strftime(x, time_display_units)
                    )
                )
            except Exception as exc:
                raise ValueError(
                    f"Invalid time_display_units option provided: "
                    f"'{time_display_units}'. Valid options are: dhms, dhm, dh, d, m, y. "
                    f"Alternatively, you can provide your own valid strftime format "
                    f"(e.g. '%Y-%m-%d %H'). See the strftime documentation for more "
                    f"details: https://strftime.org/"
                ) from exc

    else:
        full_entity_df_plus_pos_copy["snapshot_time_display"] = (
            full_entity_df_plus_pos_copy["snapshot_time"]
        )

    # We are effectively making use of an animated plotly express scatterplot
    # to do all of the heavy lifting
    # Because of the way plots animate in this, it deals with all of the
    # difficulty of paths between individual positions - so we just have to
    # tell it where to put people at each defined step of the process, and the
    # scattergraph will move them

    # The default hover template indexes customdata[0..5] by fixed meaning (entity
    # id, time, snapshot time, label, time in event, queue position). A caller-
    # supplied custom_hover_data replaces that list wholesale, so the default
    # template would then point at the wrong - or missing - columns and render
    # broken hover with no error. Make the mismatch legible instead.
    if custom_hover_data and hover_text_entity == "default":
        raise ValueError(
            "`custom_hover_data` was provided but `hover_text_entity` is still the "
            "default template, which expects exactly these six columns in this "
            "order: entity id, time, snapshot time, label, time in event, queue "
            "position. Pass your own `hover_text_entity` string that references "
            "your columns by position - e.g. hover_text_entity=\"Widgets: "
            "%{customdata[0]}\" for custom_hover_data=[\"widgets\"] - or drop "
            "`custom_hover_data` to use the default hover text."
        )

    # If we have been passed a custom hover data list, use this.
    # Copy it - appending to the caller's list would grow it on every call.
    if custom_hover_data:
        hovers = list(custom_hover_data)
        # Only offer the resource column if the log actually has one. A scenario can be
        # passed for a model with no resource_use events, in which case referencing it
        # would fail inside plotly with an unrelated-looking error.
        if scenario is not None and resource_col_name in full_entity_df_plus_pos_copy:
            hovers.append(resource_col_name)

    else:
        full_entity_df_plus_pos_copy["event_start"] = (
            full_entity_df_plus_pos_copy.groupby([entity_col_name, event_col_name])[
                time_col_name
            ].transform("min")
        )
        full_entity_df_plus_pos_copy["time_in_event"] = (
            full_entity_df_plus_pos_copy["snapshot_time_base"]
            - full_entity_df_plus_pos_copy["event_start"]
        )

        if "additional" in full_entity_df_plus_pos_copy:
            full_entity_df_plus_pos_copy["queue_position"] = (
                full_entity_df_plus_pos_copy.apply(
                    lambda x: (
                        ""
                        if x["additional"] > 1.0
                        else (
                            f"<br>Queue Position: {x['rank']:.0f}"
                            if x[event_type_col_name] == "queue"
                            else ""
                        )
                    ),
                    axis=1,
                )
            )
        else:
            full_entity_df_plus_pos_copy["queue_position"] = (
                full_entity_df_plus_pos_copy.apply(
                    lambda x: (
                        f"<br>Queue Position: {x['rank']:.0f}"
                        if x[event_type_col_name] == "queue"
                        else ""
                    ),
                    axis=1,
                )
            )

        if "additional" in full_entity_df_plus_pos_copy:
            full_entity_df_plus_pos_copy["entity_display_hover"] = (
                full_entity_df_plus_pos_copy.apply(
                    lambda x: ("N/A" if x["additional"] > 1.0 else x[entity_col_name]),
                    axis=1,
                )
            )

            full_entity_df_plus_pos_copy["time_hover"] = (
                full_entity_df_plus_pos_copy.apply(
                    lambda x: ("N/A" if x["additional"] > 1.0 else x[time_col_name]),
                    axis=1,
                )
            )

            full_entity_df_plus_pos_copy["time_in_event"] = (
                full_entity_df_plus_pos_copy.apply(
                    lambda x: ("N/A" if x["additional"] > 1.0 else x["time_in_event"]),
                    axis=1,
                )
            )

            hovers = [
                "entity_display_hover",
                "time_hover",
                "snapshot_time",
                "label",
                "time_in_event",
                "queue_position",
            ]
        else:
            hovers = [
                entity_col_name,
                time_col_name,
                "snapshot_time",
                "label",
                "time_in_event",
                "queue_position",
            ]

        # As above, only when the column is actually present.
        if scenario is not None and resource_col_name in full_entity_df_plus_pos_copy:
            hovers.append(resource_col_name)

    if hover_text_entity == "default":
        hover_text = (
            "<b>%{customdata[2]}"
            "<br><b>Entity ID:</b> %{customdata[0]}"
            "<br>Event '%{customdata[3]}' began at %{customdata[1]:.2f}"
            f" {simulation_time_unit}"
            "<br>Time spent in event so far: %{customdata[4]:.2f}"
            f" {simulation_time_unit}"
            "%{customdata[5]}"
        )
    else:
        hover_text = hover_text_entity

    # Add opacity where not present for backwards compatibility prior to 1.0.1
    if "opacity" not in full_entity_df_plus_pos_copy:
        full_entity_df_plus_pos_copy["opacity"] = 1

    # Resolve which events have their entity icon mirrored, from `event_position_df`
    # directly rather than any column that survived onto the entity frame - this is
    # the same source `_resolve_direction_sign` reads for stage labels below, so a
    # row's icon flip and its layout direction can never disagree about where an
    # event's settings come from.
    _event_flip_map = dict(
        zip(
            event_position_df[event_col_name],
            _resolve_icon_flip(event_position_df, flip_entity_icons),
        )
    )
    # `.map(dict.get, ...)` rather than `.map(_event_flip_map).fillna(False)` -
    # an event absent from the map (or NaN, for the all-NaN-position filler row
    # that keeps an otherwise-empty snapshot from vanishing entirely) resolves
    # straight to False, with no NaN-then-downcast step to trigger pandas'
    # object-dtype fillna deprecation warning.
    _entity_flip = full_entity_df_plus_pos_copy[event_col_name].map(
        lambda event: _event_flip_map.get(event, False)
    )
    any_icons_flipped = bool(_entity_flip.any())

    # Overflow rows ('+ N more', the ASCII gauge bars) are never flipped - the
    # ASCII bar / count string is unreadable mirrored, whatever entity icon it
    # happens to be attached to (`ascii_queue_icon` takes an `icon` argument but
    # never actually uses it in its output).
    if "additional" in full_entity_df_plus_pos_copy.columns:
        _entity_flip = _entity_flip & full_entity_df_plus_pos_copy["additional"].isna()

    full_entity_df_plus_pos_copy["icon_display"] = full_entity_df_plus_pos_copy["icon"]
    full_entity_df_plus_pos_copy.loc[_entity_flip, "icon_display"] = (
        ICON_FLIP_MARKER + full_entity_df_plus_pos_copy.loc[_entity_flip, "icon"]
    )

    if any_icons_flipped:
        inject_icon_flip_css()

    # Icon font: a single choice for the whole animation (not per-event, unlike
    # queue_direction/flip_icons - this is a font, not a layout concern), applied
    # per point only so overflow rows can be exempted from it, the same way they
    # are exempted from flipping - a substituted glyph in place of the ASCII gauge
    # would be worse than plain text, and font metrics for a wide bar-and-count
    # string were never designed against an icon font in mind.
    #
    # A row with no entity at all - the all-NaN placeholder that keeps an
    # otherwise-empty snapshot from vanishing - is exempted the same way: it
    # never renders (NaN x/y), and without this it would surface as its own
    # spurious "nan" colour-group category below (`entity_colour_by`/`icon`
    # cast to plain strings), one entry no real entity ever belongs to.
    _not_overflow = full_entity_df_plus_pos_copy[entity_col_name].notna()
    if "additional" in full_entity_df_plus_pos_copy.columns:
        _not_overflow &= full_entity_df_plus_pos_copy["additional"].isna()

    _resolved_family = _resolved_weight = None
    if entity_icon_font is not None:
        _resolved_family, _resolved_weight = _resolve_icon_font(
            entity_icon_font, entity_icon_font_weight
        )
        inject_icon_font_css(entity_icon_font, entity_icon_font_weight)

    # Per-entity colour needs its own trace per category, since Plotly Express has
    # no per-point channel for `textfont.color` on an animated figure (the same gap
    # `flip_entity_icons` works around for text, by folding the marker into the
    # string itself - not an option here, since colour is a real Plotly attribute
    # rather than something that can be smuggled into `text`). `color=` is reused
    # for the font exemption too: overflow rows are routed into their own reserved
    # category, `_entity_icon_group="_overflow"`, so the two concerns share one
    # mechanism instead of needing separate mid-animation restyling passes.
    _icon_group_column = None
    if entity_colour_by is not None or entity_icon_font is not None:
        if entity_colour_by is not None:
            if entity_colour_by not in full_entity_df_plus_pos_copy.columns:
                raise ValueError(
                    f"`entity_colour_by='{entity_colour_by}'` is not a column on the "
                    f"positioned entity frame. Available columns: "
                    f"{sorted(str(c) for c in full_entity_df_plus_pos_copy.columns)}. "
                    f"This is usually a column carried straight through from your "
                    f"event log (e.g. 'priority', 'pathway')."
                )
            _base_group = full_entity_df_plus_pos_copy[entity_colour_by].astype(str)
        else:
            # No real category - one synthetic bucket, so every non-overflow entity
            # still lands in its own trace, separate from the overflow row's.
            _base_group = pd.Series("_entity", index=full_entity_df_plus_pos_copy.index)

        _icon_group_column = "_entity_icon_group"
        _icon_group_values = _base_group.where(_not_overflow, "_overflow")
        full_entity_df_plus_pos_copy[_icon_group_column] = _icon_group_values

        # Every category that will ever occur, across the whole animation - not
        # just whichever ones px.scatter's own first frame happens to draw. Fed to
        # `_reconcile_grouped_traces` below, which is what actually makes a
        # category missing from a given frame (nobody of that `entity_colour_by`
        # value has arrived yet, say) show up there anyway, as an empty
        # placeholder - see its docstring for the Plotly Express behaviour this
        # works around.
        _all_icon_categories = sorted(_icon_group_values.unique())

    # Validated unconditionally (like `entity_colour_by` above) so a typo'd column
    # name is caught even on the `go` backend, which doesn't otherwise look at
    # `entity_annotation_by` at all - see the express-only trace build below.
    if entity_annotation_by is not None:
        if entity_annotation_by not in full_entity_df_plus_pos_copy.columns:
            raise ValueError(
                f"`entity_annotation_by='{entity_annotation_by}'` is not a column on "
                f"the positioned entity frame. Available columns: "
                f"{sorted(str(c) for c in full_entity_df_plus_pos_copy.columns)}. "
                f"This is usually a column carried straight through from your event "
                f"log (e.g. 'los', 'priority')."
            )

    # The animation frame is the *formatted* time, so a display format coarser than the
    # snapshot interval silently merges snapshots into a single frame - e.g. 10 minute
    # snapshots displayed as 'd' collapse a whole day into one. Plotly then drops the
    # animation entirely, and entities from different moments are drawn on top of one
    # another. Say so rather than returning a quietly wrong figure.
    distinct_snapshots = full_entity_df_plus_pos_copy["snapshot_time_base"].nunique()
    distinct_labels = full_entity_df_plus_pos_copy["snapshot_time_display"].nunique()
    if distinct_labels < distinct_snapshots:
        warnings.warn(
            f"`time_display_units` is coarser than the snapshot interval: "
            f"{distinct_snapshots} snapshots collapse into {distinct_labels} distinct "
            f"frame label(s), so snapshots will be merged and the animation will show "
            f"fewer - possibly no - frames. Either use a finer `time_display_units`, or "
            f"increase `every_x_time_units` so each snapshot gets its own label.",
            UserWarning,
            stacklevel=3,
        )

    # Reused by both express calls below - a group with no explicit colour still
    # gets one, from px's own default qualitative palette, by leaving it out of
    # the map entirely rather than trying to pre-assign a default ourselves.
    _px_color_kwargs = {}
    if _icon_group_column is not None:
        _color_map = dict(entity_colour_map) if entity_colour_map else {}
        _color_map.setdefault("_overflow", overflow_text_color)
        _color_map.setdefault("_entity", overflow_text_color)
        _px_color_kwargs = dict(color=_icon_group_column, color_discrete_map=_color_map)

    if str.lower(backend) in ["express", "px", "plotly express"]:
        if hover_text_entity is None:
            fig = px.scatter(
                full_entity_df_plus_pos_copy.sort_values("snapshot_time_base"),
                x="x_final",
                y="y_final",
                # Each frame is one step of time, with the gap being determined
                # in the reshape_for_animation function
                animation_frame="snapshot_time_display",
                # Important to group by patient here
                animation_group=entity_col_name,
                text="icon_display",
                range_x=[0, x_max],
                range_y=[0, y_max],
                height=plotly_height,
                width=plotly_width,
                # This sets the opacity of the points that sit behind
                opacity=0,
                **_px_color_kwargs,
            )

            if _icon_group_column is not None:
                _reconcile_grouped_traces(fig, _all_icon_categories)

            # plotly express does not accept `hoverinfo`, so hover has to be
            # switched off on the resulting traces instead.
            fig.update_traces(hoverinfo="skip", hovertemplate=None)
            for frame in fig.frames:
                for trace in frame.data:
                    trace.hoverinfo = "skip"
                    trace.hovertemplate = None
        else:
            fig = px.scatter(
                full_entity_df_plus_pos_copy.sort_values("snapshot_time_base"),
                x="x_final",
                y="y_final",
                # Each frame is one step of time, with the gap being determined
                # in the reshape_for_animation function
                animation_frame="snapshot_time_display",
                # Important to group by patient here
                animation_group=entity_col_name,
                text="icon_display",
                hover_name=event_col_name,
                custom_data=hovers,
                range_x=[0, x_max],
                range_y=[0, y_max],
                height=plotly_height,
                width=plotly_width,
                # This sets the opacity of the points that sit behind
                opacity=0,
                **_px_color_kwargs,
            )

            if _icon_group_column is not None:
                _reconcile_grouped_traces(fig, _all_icon_categories)

            # update hover text in initial frame
            fig.update_traces(hovertemplate=hover_text)

            # update hover text in subsequent frames
            for frame in fig.frames:
                for trace in frame.data:
                    trace.hovertemplate = hover_text

    # EXPERIMENTAL
    # Lowercased to match the express branch above, which has always accepted
    # 'Express'. Without it, 'GO' was rejected while 'EXPRESS' was accepted.
    elif str.lower(backend) in [
        "go",
        "graph objects",
        "plotly graph objects",
        "plotly go",
    ]:
        # No per-row overflow exemption in this backend (unlike express) - out of
        # scope for the experimental path. `entity_colour_by` and the legend are
        # not supported here at all.
        _go_backend_font_kwargs = {}
        if _resolved_family is not None:
            _go_backend_font_kwargs["family"] = _resolved_family
            if _resolved_weight is not None:
                _go_backend_font_kwargs["weight"] = _resolved_weight

        # Get sorted lists of unique entities and animation frames
        unique_entities = sorted(full_entity_df_plus_pos_copy[entity_col_name].unique())
        unique_frames = sorted(
            full_entity_df_plus_pos_copy["snapshot_time_display"].unique()
        )

        # Pre-group data by frame for efficient lookup
        frames_data = {}
        for frame_time in unique_frames:
            frame_df = full_entity_df_plus_pos_copy[
                full_entity_df_plus_pos_copy["snapshot_time_display"] == frame_time
            ]
            frames_data[frame_time] = frame_df.groupby(entity_col_name)

        # Initialize the figure
        fig = go.Figure()

        # --- Create the initial traces (for ALL entities, not just first frame) ---
        first_frame_groups = frames_data[unique_frames[0]]

        for entity in unique_entities:
            # Set text opacity once
            text_opacity = 1.0 if entity == "Patient_0" else 0.5

            # Check if entity exists in first frame
            if entity in first_frame_groups.groups:
                entity_df = first_frame_groups.get_group(entity)

                fig.add_trace(
                    go.Scatter(
                        x=entity_df["x_final"],
                        y=entity_df["y_final"],
                        name=entity,
                        text=entity_df["icon_display"],
                        mode="text",
                        textfont=dict(
                            size=16,
                            color=f"rgba(0, 0, 0, {text_opacity})",
                            **_go_backend_font_kwargs,
                        ),
                        hovertemplate=(
                            f"<b>{entity_df[event_col_name].iloc[0]}</b><br><br>"
                            "x: %{x}<br>"
                            "y: %{y}<br>"
                            "Info: %{customdata[0]}"
                            "<extra></extra>"
                        ),
                        customdata=entity_df[hovers],
                    )
                )
            else:
                # Create empty trace for entities not in first frame
                fig.add_trace(
                    go.Scatter(
                        x=[None],
                        y=[None],
                        name=entity,
                        text=[""],
                        mode="text",
                        textfont=dict(
                            size=16,
                            color=f"rgba(0, 0, 0, {text_opacity})",
                            **_go_backend_font_kwargs,
                        ),
                        hovertemplate="<extra></extra>",
                        customdata=[[""]],
                    )
                )

        # --- Create animation frames (optimized) ---
        frames = []

        # Pre-calculate text opacities for all entities
        text_opacities = {
            entity: 1.0 if entity == "Patient_0" else 0.5 for entity in unique_entities
        }

        for frame_time in unique_frames:
            frame_groups = frames_data[frame_time]

            # Build frame data efficiently
            data_for_frame = []

            for entity in unique_entities:
                text_opacity = text_opacities[entity]

                if entity in frame_groups.groups:
                    entity_df = frame_groups.get_group(entity)

                    # Only include necessary properties in frame data
                    data_for_frame.append(
                        {
                            "x": entity_df["x_final"].tolist(),
                            "y": entity_df["y_final"].tolist(),
                            "text": entity_df["icon_display"].tolist(),
                            "customdata": entity_df[hovers].values.tolist(),
                            "textfont.color": f"rgba(0, 0, 0, {text_opacity})",
                        }
                    )
                else:
                    # Empty data for missing entities
                    data_for_frame.append(
                        {
                            "x": [None],
                            "y": [None],
                            "text": [""],
                            "customdata": [[""]],
                            "textfont.color": f"rgba(0, 0, 0, {text_opacity})",
                        }
                    )

            frames.append(go.Frame(data=data_for_frame, name=str(frame_time)))

        fig.frames = frames

        # --- Optimized animation settings ---
        play_settings = {
            "frame": {"duration": 300, "redraw": False},
            "transition": {"duration": 50, "easing": "linear"},
        }

        pause_settings = {
            "frame": {"duration": 0, "redraw": False},
            "transition": {"duration": 0},
        }

        fig.update_layout(
            title_text="Animated Patient Locations (Graph Objects)",
            height=plotly_height,
            width=plotly_width,
            xaxis=dict(range=[0, x_max], autorange=False),
            yaxis=dict(range=[0, y_max], autorange=False),
            # Fixed control buttons
            updatemenus=[
                {
                    "type": "buttons",
                    "showactive": False,
                    "x": 0.1,
                    "y": 0,
                    "buttons": [
                        {
                            "label": "▶ Play",
                            "method": "animate",
                            "args": [None, play_settings],
                        },
                        {
                            "label": "⏸ Pause",
                            "method": "animate",
                            "args": [
                                None,
                                {
                                    "frame": {"duration": 0},
                                    "mode": "immediate",
                                },
                            ],
                        },
                        {
                            "label": "⏮ Reset",
                            "method": "animate",
                            "args": [str(unique_frames[0]), pause_settings],
                        },
                    ],
                }
            ],
            # Optimized slider
            sliders=[
                {
                    "active": 0,
                    "yanchor": "top",
                    "xanchor": "left",
                    "currentvalue": {
                        "font": {"size": 20},
                        "prefix": "Time: ",
                        "visible": True,
                        "xanchor": "right",
                    },
                    "steps": [
                        {
                            "label": str(f),
                            "method": "animate",
                            "args": [str(f), pause_settings],
                        }
                        for f in unique_frames
                    ],
                }
            ],
        )
    else:
        raise ValueError(
            f"Invalid backend passed: '{backend}'. Options are: 'express'|'px'|"
            f"'plotly express' for the original vidigi backend, or 'go'|"
            f"'graph objects'|'plotly graph objects'|'plotly go' for the advanced "
            f"backend. Matching is case-insensitive."
        )

    # `color=` grouping is express-only (see `_px_color_kwargs` above) - the `go`
    # backend sets its own font at trace-construction time instead, and never
    # supports colour/legend at all (see its params' docstrings).
    _is_express_backend = str.lower(backend) in ["express", "px", "plotly express"]

    def _style_entity_trace(trace):
        """Apply size, and colour/font-by-category if grouping is active, to one
        entity trace - shared between the base traces and every frame's, since a
        colour-grouped frame trace carries its own (initially empty) `textfont`
        that otherwise blocks it inheriting `family`/`color` from the base trace -
        confirmed via mutation testing, and the reason this exists as its own
        per-frame pass rather than a single pass over `fig.data`.
        """
        trace.textfont.size = entity_icon_size
        if _icon_group_column is not None and _is_express_backend:
            # One trace per `_entity_icon_group` category (see its construction
            # above) - each already carries its own colour via `trace.marker.color`
            # (from `color_discrete_map`, or px's own default palette for a
            # category the map doesn't cover), so copy that across rather than
            # overwriting every trace with the same `overflow_text_color`, which
            # would defeat the point of colouring entities in the first place.
            trace.textfont.color = trace.marker.color
            if trace.name != "_overflow" and _resolved_family is not None:
                trace.textfont.family = _resolved_family
                if _resolved_weight is not None:
                    trace.textfont.weight = _resolved_weight
        else:
            trace.textfont.color = overflow_text_color

    # Update the size of the icons and labels
    # This is what determines the size of the individual emojis that
    # represent our people!
    # fig.data[0].textfont.size = entity_icon_size
    # Apply entity_icon_size to all traces that represent entities
    for trace in fig.data:
        if "marker" in trace:
            _style_entity_trace(trace)

    if _icon_group_column is not None and _is_express_backend:
        for trace in fig.data:
            # "_entity" (no real `entity_colour_by`, just the font exemption's own
            # grouping) and "_overflow" are never real categories - never worth a
            # legend entry, whatever `show_entity_legend` says.
            if trace.name in ("_entity", "_overflow") or not show_entity_legend:
                trace.showlegend = False

        for frame in fig.frames or ():
            for trace in frame.data:
                if "marker" in trace:
                    _style_entity_trace(trace)

    #############################################
    # Optional second trace: entity_annotation_by
    #############################################

    # A separate scatter trace, offset below each entity's icon, built from its
    # own independent `px.scatter` call over the exact same rows (just a
    # different text/y column) - not a per-point style tweaked onto the icon
    # trace above. That's a deliberate response to a genuine Plotly/SVG ceiling:
    # a single `<text>` node gets one `font-family` and one transform, so any
    # text appended into `icon`/`icon_display` itself inherits whatever
    # `flip_entity_icons`/`entity_icon_font` did to the icon glyph it shares a
    # text node with. Only a structurally separate trace is immune to both -
    # this one is never touched by `_style_entity_trace` or the flip-marker
    # logic above, so it can't inherit either. Express backend only, matching
    # `entity_colour_by`/`entity_icon_font` - the `go` backend gets neither.
    if entity_annotation_by is not None and _is_express_backend:
        _annotation_df = full_entity_df_plus_pos_copy.copy()
        # NaN on the synthetic "+ N more" / gauge overflow row - it isn't a real
        # entity, so it gets no annotation, the same exemption the icon trace
        # already gives it from flipping and icon fonts.
        _annotation_df["_entity_annotation_text"] = _annotation_df[
            entity_annotation_by
        ].where(_not_overflow)
        _annotation_df["_entity_annotation_y"] = (
            _annotation_df["y_final"] + entity_annotation_offset_y
        )

        fig_annotation = px.scatter(
            _annotation_df.sort_values("snapshot_time_base"),
            x="x_final",
            y="_entity_annotation_y",
            animation_frame="snapshot_time_display",
            animation_group=entity_col_name,
            text="_entity_annotation_text",
            range_x=[0, x_max],
            range_y=[0, y_max],
            height=plotly_height,
            width=plotly_width,
            opacity=0,
        )

        def _style_annotation_trace(trace):
            trace.name = "_annotation"
            trace.showlegend = False
            trace.hoverinfo = "skip"
            trace.hovertemplate = None
            trace.textfont = dict(
                size=entity_annotation_size, color=entity_annotation_color
            )
            return trace

        fig.add_trace(_style_annotation_trace(fig_annotation.data[0]))

        # Matched by frame name, not position - `fig_annotation` is built from
        # the same underlying rows as the entity trace(s) above (same
        # `snapshot_time_display`/`animation_group` values), so its frames carry
        # the same names, but not necessarily rebuilt in the same order.
        _annotation_frames_by_name = {
            frame.name: frame for frame in (fig_annotation.frames or ())
        }
        for frame in fig.frames or ():
            _matching_frame = _annotation_frames_by_name.get(frame.name)
            if _matching_frame is not None and _matching_frame.data:
                _annotation_trace = _matching_frame.data[0]
            else:
                # Defensive only - every frame is expected to have a match,
                # since both figures are built from the same source rows.
                _annotation_trace = go.Scatter(
                    x=[None], y=[None], text=[None], mode="markers+text"
                )
            frame.data = tuple(frame.data) + (
                _style_annotation_trace(_annotation_trace),
            )

    # Now add labels identifying each stage (optional - can either be used
    # in conjunction with a background image or as a way to see stage names
    # without the need to create a background image)
    if display_stage_labels:
        # A right-building queue would run straight over a label drawn to the
        # right of the anchor, so for those events the label goes to the left
        # instead. Resolved per event, so a mixed layout gets each label on its
        # own clear side.
        label_sign = _resolve_direction_sign(event_position_df, queue_direction)
        label_x = [
            pos - 10 if s > 0 else pos + 10
            for pos, s in zip(event_position_df["x"].to_list(), label_sign)
        ]
        label_pos = [
            "middle left" if s > 0 else "middle right" for s in label_sign
        ]
        fig.add_trace(
            go.Scatter(
                x=label_x,
                y=event_position_df["y"].to_list(),
                mode="text",
                name="",
                text=event_position_df["label"].to_list(),
                textposition=label_pos,
                hoverinfo="none",
            )
        )

        # Update the size of the icons and labels
        # This is what determines the size of the individual emojis that
        # represent our people!
        # Update the text size for the LAST ADDED trace (stage labels)
        fig.data[-1].textfont.size = text_size
        fig.data[-1].textfont.color = stage_label_text_colour

    #############################################
    # Add in icons to indicate the available resources
    #############################################

    # Make an additional dataframe that has one row per resource type
    # Then, starting from the initial position, make that many large circles
    # make them semi-transparent or you won't see the people using them!
    # A scenario can be supplied for a model where no event declares a resource - a
    # purely queue-based model, say. There is nothing to draw in that case, and the
    # explode below would fail on the resulting empty frame. Only the truthy check
    # below is shared with `vidigi.analysis._resolve_resource_capacities`'s route C
    # (via `_resource_map_from_event_position_df`) - the row selection immediately
    # below still re-derives its own filter on the raw `resource` column, rather
    # than consuming the helper's mapping, so this only guarantees the two agree on
    # *whether* a resource exists, not on every detail of *which* rows count.
    resource_attr_map = _resource_map_from_event_position_df(event_position_df)
    events_with_resources = None
    if scenario is not None and resource_attr_map:
        events_with_resources = event_position_df[
            event_position_df["resource"].notnull()
        ].copy()
        events_with_resources["resource_count"] = events_with_resources[
            "resource"
        ].apply(lambda x: getattr(scenario, x))

        # -1 lays the resource dots out leftwards from the anchor (historic
        # behaviour), +1 rightwards - matching the queue direction for that
        # event so a resource emoji faces the same way as its queue.
        events_with_resources["_dir_sign"] = _resolve_direction_sign(
            events_with_resources, queue_direction
        )

        events_with_resources = events_with_resources.join(
            events_with_resources.apply(
                lambda r: pd.Series(
                    {
                        "x_final": [
                            r["x"] + r["_dir_sign"] * (gap_between_resources * (i + 1))
                            for i in range(r["resource_count"])
                        ]
                    }
                ),
                axis=1,
            ).explode("x_final"),
            how="right",
        )

        # events_with_resources = events_with_resources.assign(resource_id=range(len(events_with_resources)))
        # After exploding
        events_with_resources[resource_col_name] = events_with_resources.groupby(
            [event_col_name]
        ).cumcount()

        if wrap_resources_at is not None:
            events_with_resources["row"] = np.floor(
                (events_with_resources[resource_col_name]) / (wrap_resources_at)
            )

            events_with_resources["x_final"] = (
                events_with_resources["x_final"]
                - events_with_resources["_dir_sign"]
                * (
                    wrap_resources_at
                    * events_with_resources["row"]
                    * gap_between_resources
                )
                - events_with_resources["_dir_sign"] * gap_between_resources
            )

            events_with_resources["y_final"] = events_with_resources["y"] + (
                events_with_resources["row"] * gap_between_resource_rows
            )
        else:
            events_with_resources["y_final"] = events_with_resources["y"]

        # `EventPosition.resource_icon` overrides `custom_resource_icon` per event, and
        # - when it names an image (a URL, local path, or `data:` URI with an image
        # extension; anything else is a text glyph, exactly like `custom_resource_icon`)
        # - is drawn as a static `layout.images` entry instead of scatter text. Closes
        # the TODO this replaced: custom icons per resource, for glyphs and images alike.
        if "resource_icon" in events_with_resources.columns:
            _resource_icon_override = events_with_resources["resource_icon"]
            _is_image_icon = _resource_icon_override.apply(
                lambda v: _is_image_source(v) if pd.notna(v) else False
            )
        else:
            _resource_icon_override = pd.Series(None, index=events_with_resources.index)
            _is_image_icon = pd.Series(False, index=events_with_resources.index)

        image_resources = events_with_resources[_is_image_icon]
        events_with_resources = events_with_resources[~_is_image_icon]
        _resource_icon_override = _resource_icon_override[~_is_image_icon]

        for _, row in image_resources.iterrows():
            image_source = process_background_image_path(row["resource_icon"])
            image_size = (
                resource_image_size
                if resource_image_size is not None
                else resource_icon_size
            )
            fig.add_layout_image(
                dict(
                    source=image_source,
                    x=row["x_final"],
                    y=row["y_final"] - 10,
                    xref="x",
                    yref="y",
                    sizex=image_size,
                    sizey=image_size,
                    xanchor="center",
                    yanchor="middle",
                    sizing="contain",
                    layer="above",
                )
            )

        # This just adds an additional scatter trace that creates large dots
        # that represent the individual resources. A row's own `resource_icon`
        # (when a text glyph, not an image - handled above) takes precedence over
        # `custom_resource_icon`, falling back to it where unset.
        _resource_glyph = _resource_icon_override.where(
            _resource_icon_override.notna(), custom_resource_icon
        )
        if custom_resource_icon is not None or _resource_icon_override.notna().any():
            # Follows the same per-event flip resolution as the entity icons above,
            # so a resource icon faces the same way as the entities queuing for it.
            resource_flip = _resolve_icon_flip(events_with_resources, flip_entity_icons)
            resource_icon_text = [
                (ICON_FLIP_MARKER + icon) if flipped else icon
                for icon, flipped in zip(_resource_glyph, resource_flip)
            ]
            if resource_flip.any():
                inject_icon_flip_css()

            fig.add_trace(
                go.Scatter(
                    x=events_with_resources["x_final"].to_list(),
                    # Place these slightly below the y position for each entity
                    # that will be using the resource
                    y=[i - 10 for i in events_with_resources["y_final"].to_list()],
                    mode="markers+text",
                    text=resource_icon_text,
                    # Make the actual marker invisible
                    marker=dict(opacity=0),
                    # Set opacity of the icon
                    opacity=0.8,
                    hoverinfo="none",
                )
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=events_with_resources["x_final"].to_list(),
                    # Place these slightly below the y position for each entity
                    # that will be using the resource
                    y=[i - 10 for i in events_with_resources["y_final"].to_list()],
                    mode="markers",
                    # Define what the marker will look like
                    marker=dict(color="LightSkyBlue", size=15),
                    opacity=resource_opacity,
                    hoverinfo="none",
                )
            )

        # Update the size of the icons and labels
        # This is what determines the size of the individual emojis that
        # represent our people!
        fig.data[-1].textfont.size = resource_icon_size
        # fig.data[-1].opacity = resource_opacity # Set opacity for the resource icon text

    #############################################
    # Optional step to add a background image
    #############################################

    # This can help to better visualise the layout/structure of a pathway
    # Simple FOSS tool for creating these background images is draw.io

    # Ideally your queueing steps should always be ABOVE your resource use steps
    # as this then results in people nicely flowing from the front of the queue
    # to the next stage

    if add_background_image is not None:
        image_path = process_background_image_path(add_background_image)
        fig.add_layout_image(
            dict(
                source=image_path,
                xref="x domain",
                yref="y domain",
                x=1,
                y=1,
                sizex=1,
                sizey=1,
                xanchor="right",
                yanchor="top",
                sizing="stretch",
                opacity=background_image_opacity,
                layer="below",
            )
        )

    # We don't need any gridlines or tickmarks for the final output, so remove
    # However, can be useful for the initial setup phase of the outputs, so give
    # the option to inlcude
    if not setup_mode:
        fig.update_xaxes(
            showticklabels=False,
            showgrid=False,
            zeroline=False,
            # Prevent zoom
            fixedrange=True,
        )
        fig.update_yaxes(
            showticklabels=False,
            showgrid=False,
            zeroline=False,
            # Prevent zoom
            fixedrange=True,
        )

    fig.update_layout(
        yaxis_title=None,
        xaxis_title=None,
        showlegend=False,
        # Increase the size of the play button and animation timeline
        sliders=[dict(currentvalue=dict(font=dict(size=35), prefix=""))],
    )

    # Optional overrides of the figure background colours. Left untouched when
    # None so the active Plotly template keeps control.
    if plot_bgcolor is not None:
        fig.update_layout(plot_bgcolor=plot_bgcolor)
    if paper_bgcolor is not None:
        fig.update_layout(paper_bgcolor=paper_bgcolor)

    # Keep auto-positioned content on the canvas. With no override_x_max /
    # override_y_max the axis range is derived purely from event anchor points,
    # so long stage labels (drawn past the rightmost anchor) and queue/resource
    # icons (drawn left of a low-x anchor) would otherwise be clipped at the
    # axis. Let that content spill into an enlarged margin rather than rescaling
    # the diagram.
    _disable_axis_clipping(fig)
    margin_updates = _overflow_margin_updates(
        event_position_df=event_position_df,
        entity_df=full_entity_df_plus_pos_copy,
        resource_df=events_with_resources,
        x_max=x_max,
        y_max=y_max,
        text_size=text_size,
        plotly_width=plotly_width,
        plotly_height=plotly_height,
        display_stage_labels=display_stage_labels,
        queue_direction=queue_direction,
    )
    if margin_updates:
        fig.update_layout(margin=margin_updates)

    # You can get rid of the play button if desired
    # Was more useful in older versions of the function
    if not include_play_button:
        fig["layout"].pop("updatemenus")

    # Adjust speed of animation
    try:
        fig.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] = (
            frame_duration
        )
    except IndexError:
        print("Error changing frame duration")

    try:
        fig.layout.updatemenus[0].buttons[0].args[1]["transition"]["duration"] = (
            frame_transition_duration
        )
    except IndexError:
        print("Error changing frame transition duration")

    if debug_mode:
        print(
            f"Output animation generation complete at {time.strftime('%H:%M:%S', time.localtime())}"
        )

    return fig


def animate_activity_log(
    event_log: pd.DataFrame,
    event_position_df: pd.DataFrame,
    scenario: Optional[object] = None,
    time_col_name: str = "time",
    entity_col_name: str = "entity_id",
    event_type_col_name: str = "event_type",
    event_col_name: str = "event",
    pathway_col_name: Optional[str] = None,
    resource_col_name: str = "resource_id",
    simulation_time_unit: SimulationTimeUnit = "minutes",
    every_x_time_units: int = 10,
    wrap_queues_at: Optional[int] = 20,
    wrap_resources_at: Optional[int] = 20,
    step_snapshot_max: int = 60,
    limit_duration: Optional[int] = None,
    plotly_height: int = 900,
    plotly_width: Optional[int] = None,
    include_play_button: bool = True,
    add_background_image: Optional[str] = None,
    display_stage_labels: bool = True,
    entity_icon_size: int = 24,
    text_size: int = 24,
    resource_icon_size: int = 24,
    hover_text_entity: Optional[str] = "default",
    custom_hover_data: Optional[list[str]] = None,
    gap_between_entities: int = 10,
    gap_between_queue_rows: int = 30,
    gap_between_resource_rows: int = 30,
    gap_between_resources: int = 10,
    queue_direction: QueueDirection = "left",
    flip_entity_icons: bool = False,
    entity_icon_font: Optional[str] = None,
    entity_icon_font_weight: Optional[int] = None,
    entity_colour_by: Optional[str] = None,
    entity_colour_map: Optional[dict] = None,
    show_entity_legend: bool = True,
    entity_annotation_by: Optional[str] = None,
    entity_annotation_size: int = 14,
    entity_annotation_color: str = "black",
    entity_annotation_offset_y: float = -15,
    resource_image_size: Optional[float] = None,
    resource_opacity: float = 0.8,
    custom_resource_icon: Optional[str] = None,
    override_x_max: Optional[int] = None,
    override_y_max: Optional[int] = None,
    start_date: Optional[str] = None,
    start_time: Optional[str] = None,
    time_display_units: Optional[str] = None,
    setup_mode: bool = False,
    frame_duration: int = 400,  # milliseconds
    frame_transition_duration: int = 600,  # milliseconds
    debug_mode: bool = False,
    custom_entity_icon_list: Optional[list[str]] = None,
    debug_write_intermediate_objects: bool = False,
    background_image_opacity: float = 0.5,
    overflow_text_color: str = "black",
    stage_label_text_colour: str = "black",
    plot_bgcolor: Optional[str] = None,
    paper_bgcolor: Optional[str] = None,
    backend: AnimationBackend = "express",
    step_snapshot_limit_gauges: bool = False,
    gauge_segments: int = 10,
    gauge_max_override: Optional[int | float] = None,
    run_col_name: Optional[str] = "auto",
    warm_up: int = 0,
    snapshot_alignment: SnapshotAlignment = "warm_up",
) -> go.Figure:
    """
    Generate an animated visualization of patient flow through a system.

    This function processes event log data, adds positional information, and
    creates an interactive Plotly animation representing patient movement
    through various stages.

    Parameters
    ----------
    event_log : pd.DataFrame
        The log of events to be animated, containing patient activities.
    event_position_df : pd.DataFrame
        DataFrame specifying the positions of different events, with columns
        'event', 'x', and 'y' (plus optional 'label', 'resource', 'direction' -
        see ``queue_direction`` - 'flip_icons' - see ``flip_entity_icons`` -
        and 'resource_icon', which overrides ``custom_resource_icon`` per event
        and can name an image instead of a text glyph - see ``EventPosition``).
    scenario : object, optional
        Object whose attributes give the number of each resource available at a
        step, e.g. ``scenario.n_nurses`` (default is None). Used for two
        independent things:

        - Drawing the resource-availability icons at each stage. This also needs
          a ``resource`` column on ``event_position_df`` naming the attribute to
          read for that step (e.g. ``resource="n_nurses"``).
        - Appending the resource identifier column (``resource_col_name``,
          "resource_id" by default) to the hover ``customdata``, so a custom
          ``hover_text_entity`` template can display it. This happens only when
          the event log actually contains that column, i.e. the model logged
          resource use via ``log_resource_use_start`` / ``log_resource_use_end``.
          The built-in default template does not reference it, and a scenario
          passed for a model with no resource-use logging is harmless - the
          column is simply not appended.
    time_col_name : str, default="time"
        Name of the column in `event_log` that contains the timestamp of each
        event. Timestamps should represent the number of time units since the
        simulation began.
    entity_col_name : str, default="entity_id"
        Name of the column in `event_log` that contains the unique identifier
        for each entity (e.g., "entity_id",  "entity", "patient", "patient_id",
        "customer", "ID").
    event_type_col_name : str, default="event_type"
        Name of the column in `event_log` that specifies the category of the
        event. Supported event types include 'arrival_departure',
        'resource_use', 'resource_use_end', and 'queue'.
    event_col_name : str, default="event"
        Name of the column in `event_log` that specifies the actual event that
        occurred.
    pathway_col_name : str, optional, default=None
        Name of the column in `event_log` that identifies the specific pathway
        or process flow the entity is following. If `None`, it is assumed that
        pathway information is not present.
    resource_col_name : str, default="resource_id"
        Name of the column for the resource identifier. Used for 'resource_use'
        events.
    simulation_time_unit: string, optional
        Time unit used within the simulation (default is minutes). Possible
        values are 'seconds', 'minutes', 'hours', 'days', 'weeks', 'years'
    every_x_time_units : int, optional
        Time interval between animation frames in minutes (default is 10).
    wrap_queues_at : int, optional
        Maximum number of entities to display in a queue before wrapping to a
        new row (default is 20).
    wrap_resources_at : int, optional
        Number of resources to show before wrapping to a new row (default is
        20).
    step_snapshot_max : int, optional
        Maximum number of patients to show in each snapshot per event (default
        is 60).
    limit_duration : int, optional
        The time at which the animation stops (default is None, which
        auto-adjusts to the maximum time in the provided event log). Together
        with `warm_up` this bounds the animation window.
    plotly_height : int, optional
        Height of the Plotly figure in pixels (default is 900).
    plotly_width : int, optional
        Width of the Plotly figure in pixels (default is None, which
        auto-adjusts).
    include_play_button : bool, optional
        Whether to include a play button in the animation (default is True).
    add_background_image : str, optional
        Path to a background image file to add to the animation (default is
        None).
    display_stage_labels : bool, optional
        Whether to display labels for each stage (default is True).
    entity_icon_size : int, optional
        Size of entity icons in the animation (default is 24).
    text_size : int, optional
        Size of text labels in the animation (default is 24).
    resource_icon_size : int, optional
        Size of resource icons in the animation (default is 24).
    hover_text_entity: str, optional
        String to define the hover text. If None, hover on entity icons will
        be disabled. Default will display the entity ID, their current time in
        the system, etc. Must be provided in the format
        "%{some_column_name} some text" etc.
        See https://plotly.com/python/hover-text-and-formatting/#customizing-hover-text-with-a-hovertemplate
        for full details. All columns present in the initial dataframe are
        available to access by referencing their name in the format
        "%{some_column_name}"
    custom_hover_data: list of str, optional
        A list of column names, which must be defined as strings. If provided,
        becomes a list of additional columns that can be accessed as part of
        the string defined within hover_text_entity. customdata[0] is the first
        column specified, customdata[1] is the second, etc. So e.g. if you pass
        in ["widgets_created_cumulative"] as your custom_hover_data, your
        hover_text_entity may be "Widgets created so far: %{customdata[0]}".
        When ``scenario`` is set and the event log has a ``resource_col_name``
        column, that column is appended to the list automatically, landing at
        ``customdata[len(custom_hover_data)]``.
        Because ``custom_hover_data`` replaces the fixed column list the default
        ``hover_text_entity`` template indexes, you must also pass your own
        ``hover_text_entity`` string - supplying ``custom_hover_data`` while
        leaving ``hover_text_entity`` at its default raises ``ValueError``.
    gap_between_entities : int, optional
        Horizontal spacing between entities in pixels (default is 10).
    gap_between_queue_rows : int, optional
        Vertical spacing between rows in pixels (default is 30).
    gap_between_resource_rows : int, optional
        Vertical spacing between rows in pixels (default is 30).
    gap_between_resources : int, optional
        Horizontal spacing between resources in pixels (default is 10).
    queue_direction : {"left", "right"}, default="left"
        Which way queues (and rows of resources) build out from their anchor.
        "left" (the default, and byte-identical to previous versions) makes the
        anchor the front of the queue, with entities stacking up to its left.
        "right" mirrors this - the anchor becomes the bottom-left corner and the
        queue extends rightwards, which reads better with entity emojis that
        face right. Stage labels move to the opposite side of a right-building
        queue. Set this per event instead with a `direction` column on
        `event_position_df` (or `EventPosition(..., direction=...)`), which
        overrides the animation-wide value.
    flip_entity_icons : bool, default=False
        Mirror entity icons (and a `custom_resource_icon`) horizontally - useful
        when an emoji faces the wrong way for a particular layout, independently
        of `queue_direction`. Set this per event instead with a `flip_icons`
        column on `event_position_df` (or `EventPosition(..., flip_icons=...)`),
        which overrides the animation-wide value. Requires CSS to reach the page
        - this is injected automatically (see `vidigi.utils.inject_icon_flip_css`)
        whenever any icon actually resolves to flipped; embedding the figure a
        different way may need `vidigi.utils.entity_icon_flip_css()` added
        explicitly. Does not affect a static export via `fig.write_image()`.
    entity_icon_font : str, optional
        Render entity icons (and a `custom_resource_icon`) in an icon font
        instead of emoji, so an icon can be any glyph the font provides - one
        of `vidigi.utils.ICON_FONT_PRESETS` (`"font-awesome"`,
        `"bootstrap-icons"`, `"material-symbols"`), or any CSS font-family
        name already available on the page. `custom_entity_icon_list` then
        supplies that font's codepoints instead of emoji. See
        `generate_animation`'s docstring for the overflow-icon exemption and
        `vidigi.utils.entity_icon_font_css` for what reaching the page
        involves; the CSS is injected automatically, as for
        `flip_entity_icons`.
    entity_icon_font_weight : int, optional
        Overrides a preset's default weight. Ignored for a raw custom family.
    entity_colour_by : str, optional
        Name of a column - typically one already on your event log - to
        colour entity icons by. Only visible together with `entity_icon_font`,
        since emoji are colour fonts and ignore `textfont.color` entirely.
    entity_colour_map : dict, optional
        Maps values of `entity_colour_by` to specific colours; an uncovered
        value falls back to Plotly's default qualitative palette.
    show_entity_legend : bool, default=True
        Show a legend for `entity_colour_by`. Ignored when it is not set.
    entity_annotation_by : str, optional
        Name of a column to draw as offset text below each entity's icon -
        e.g. a running length-of-stay figure. Express backend only. See
        `generate_animation`'s docstring for the full trade-off against
        appending text directly onto `icon` yourself: prefer appending when
        `flip_entity_icons`/`entity_icon_font` aren't in play, and reach for
        this only once they are.
    entity_annotation_size : int, default=14
        Font size (in points) of the `entity_annotation_by` text.
    entity_annotation_color : str, default="black"
        Colour of the `entity_annotation_by` text.
    entity_annotation_offset_y : float, default=-15
        Vertical offset, in data units, of `entity_annotation_by` text below
        (negative) or above (positive) each entity's icon.
    resource_image_size : float, optional
        Size, in data units, of an image `resource_icon` (see
        `EventPosition.resource_icon`). Defaults to `resource_icon_size`,
        kept independent of `gap_between_resources` so changing the spacing
        between resources doesn't also change their size.
    resource_opacity : float, optional
        Opacity of resource icons (default is 0.8).
    custom_resource_icon : str, optional
        Custom icon to use for resources (default is None).
    override_x_max : int, optional
        Override the maximum x-coordinate of the plot (default is None). The
        figure margin already auto-expands to fit auto-generated stage labels,
        so this is only needed to reframe a layout the auto-sizing gets wrong.
        The axis then runs exactly ``[0, override_x_max]``; a `UserWarning` is
        raised if any event anchor falls outside that, as its queue / resources
        would be drawn off-canvas.
    override_y_max : int, optional
        Override the maximum y-coordinate of the plot (default is None). Same
        off-canvas `UserWarning` as `override_x_max`.
    start_date : str, optional
        Start date for the animation in 'YYYY-MM-DD' format. Only used when
        time_display_units is 'd' or 'dhm' (default is None).
    start_time : str, optional
        Start time for the animation in 'HH:MM:SS' format. Only used when
        time_display_units is 'd' or 'dhm' (default is None).
    time_display_units : str, optional
        Format for displaying time on the animation timeline. This affects how
        simulation time is converted into human-readable dates or clock
        formats. If `None` (default), the raw simulation time is used.

        Predefined options:

        - 'dhms' : Day Month Year + HH:MM:SS (e.g., "06 June 2025 14:23:45")
        - 'dhms_ampm' : Same as 'dhms', but in 12-hour format with AM/PM
          (e.g., "06 June 2025 02:23:45 PM")
        - 'dhm' : Day Month Year + HH:MM (e.g., "06 June 2025 14:23")
        - 'dhm_ampm' : 12-hour format with AM/PM
        - (e.g., "06 June 2025 02:23 PM")
        - 'dh' : Day Month Year + HH (e.g., "06 June 2025 14")
        - 'dh_ampm' : 12-hour format with AM/PM (e.g., "06 June 2025 02 PM")
        - 'd' : Full weekday and date (e.g., "Friday 06 June 2025")
        - 'm' : Month and year (e.g., "June 2025")
        - 'y' : Year only (e.g., "2025")
        - 'day_clock' or 'simulation_day_clock' : Show simulation-relative day
           and time (e.g., "Simulation Day 3 14:15")
        - 'day_clock_ampm' or 'simulation_day_clock_ampm' : Same as above, but
           time is shown in 12-hour clock with AM/PM
           (e.g., "Simulation Day 3 02:15 PM")

        Alternatively, you can supply a custom strftime (https://strftime.org/)
        format string (e.g., '%Y-%m-%d %H') to control the display manually.
    setup_mode : bool, optional
        If True, display grid and tick marks for initial setup (default is
        False).
    frame_duration : int, optional
        Duration of each frame in milliseconds (default is 400).
    frame_transition_duration : int, optional
        Duration of transition between frames in milliseconds (default is 600).
    debug_mode : bool, optional
        If True, print debug information during processing (default is False).
    custom_entity_icon_list: list, optional
        If given, overrides the default list of emojis used to represent
        entities
    debug_write_intermediate_objects : bool, optional
        If `True`, writes intermediate data objects (for example, the reshaped
        event log and positional dataframe) to CSV files in the current working
        directory.
    background_image_opacity : float, optional
        Opacity (0 is transparent, to 1, completely opaque) of the provided
        background image
    overflow_text_color : str, optional
        Color of the text displayed on top of entity icons in the animation
        (default is black).
    stage_label_text_colour : str, optional
        Color of the stage label text added next to each event position when
        display_stage_labels is True (default is black).
    plot_bgcolor : str, optional
        Background colour of the plotting area (inside the axes), passed
        straight to ``fig.update_layout(plot_bgcolor=...)``. Accepts any CSS
        colour string, e.g. "white" or "#f5f5f5". If None (default), Plotly's
        template default is left untouched.
    paper_bgcolor : str, optional
        Background colour of the area surrounding the plotting area (behind the
        title, play button and timeline), passed straight to
        ``fig.update_layout(paper_bgcolor=...)``. Accepts any CSS colour string.
        If None (default), Plotly's template default is left untouched.
    backend: str, optional
        EXPERIMENTAL. Whether to use the plotly express backend for the
        initial plot (default), or the experimental plotly go backend. The go
        approach is currently unstable and much slower. Use at your own risk.
    step_snapshot_limit_gauges: bool, optional
        If True, replaces the text '+ x more' with a gauge. The upper limit of
        the gauge is set by the maximum queue length observed across the
        simulation.
    gauge_segments : int, optional
        Number of discrete segments used when rendering queue length gauges
        in the animation. Higher values give a finer-grained visual indication
        of queue length, while lower values produce chunkier segments.
    gauge_max_override : int|float, optional
        Manually specified maximum value for queue length gauges. If `None`,
        the upper limit is determined from the maximum queue length observed in
        the simulation when `step_snapshot_limit_gauges` is `True`.
    run_col_name : str or None, optional
        Name of the column identifying which simulation run (replication) each
        row belongs to, used to reject event logs containing more than one
        replication. Default is "auto", which looks for a column named
        (case-insensitively) one of 'run', 'run_number', 'replication', 'rep' or
        'run_id'. Pass an explicit column name to override the search, or `None`
        to disable the check.
    warm_up : int, optional
        The time at which the animation starts, in simulation time units
        (default is 0, the beginning of the run). Not to be confused with
        `start_time` above, which is a time of day used only for labelling
        frames as clock times.

        This is how to discard a warm-up period. Pass the **whole** event log
        and set `warm_up` to the end of your warm-up; do not filter the log by
        time first. Filtering removes the 'arrival' rows of every entity that
        arrived during the warm-up, and since presence is worked out from
        arrival and departure rows, those entities then vanish from every frame
        - including ones still queuing, which is exactly what a steady-state
        animation is meant to show. `warm_up` trims the window while leaving
        that history intact.
    snapshot_alignment : {"warm_up", "run_start"}, optional
        Which point the snapshot grid counts from when `warm_up` is non-zero.
        Ignored when `warm_up` is 0.

        - "warm_up" (default): the first frame lands exactly on the boundary,
          showing the state of the system as the warm-up ends.
        - "run_start": frame times stay on the grid running from time 0 and the
          early ones are dropped, so they remain the same times you would get
          with no warm-up at all.

        The two are identical whenever `warm_up` is a multiple of
        `every_x_time_units`.

    Returns
    -------
    plotly.graph_objs._figure.Figure
        An animated Plotly figure object representing the patient flow.

    Notes
    -----
    - **Pass a single replication only.** An event log containing more than one
      run is rejected with a `ValueError`. Passing several runs does not raise on
      its own - it silently blends them into an animation that represents no run
      of your model - so this is checked before any work is done. Filter first,
      e.g. `event_log[event_log["run"] == 1]`.
    - This function uses helper functions: reshape_for_animations,
      generate_animation_df, and generate_animation.
    - The animation supports customization of icon sizes, resource
      representation, and animation speed.
    - Time can be displayed as actual dates or as model time units.
    - A background image can be added to provide context for the patient flow.
    - The function handles both queuing and resource use events.
    """
    # Check here as well as in reshape_for_animations, deliberately. This is the entry
    # point most users call, so the error should name this function's own arguments
    # rather than an internal one's, and should fire before any work is done.
    _check_single_run(event_log, run_col_name=run_col_name, frame_arg="event_log")
    _check_one_arrival_per_entity(
        event_log,
        entity_col_name=entity_col_name,
        event_type_col_name=event_type_col_name,
        event_col_name=event_col_name,
        pathway_col_name=pathway_col_name,
        frame_arg="event_log",
    )

    if debug_mode:
        start_time_function = time.perf_counter()
        print(
            f"Animation function called at {time.strftime('%H:%M:%S', time.localtime())}"
        )

    if limit_duration is None:
        limit_duration = round(event_log[time_col_name].max())

    full_entity_df = reshape_for_animations(
        event_log,
        every_x_time_units=every_x_time_units,
        limit_duration=limit_duration,
        step_snapshot_max=step_snapshot_max,
        debug_mode=debug_mode,
        time_col_name=time_col_name,
        entity_col_name=entity_col_name,
        event_type_col_name=event_type_col_name,
        event_col_name=event_col_name,
        pathway_col_name=pathway_col_name,
        run_col_name=run_col_name,
        warm_up=warm_up,
        snapshot_alignment=snapshot_alignment,
    )

    if debug_write_intermediate_objects:
        full_entity_df.to_csv("output_reshape_for_animations.csv")

    if debug_mode:
        print(
            f"Reshaped animation dataframe finished construction at {time.strftime('%H:%M:%S', time.localtime())}"
        )

    full_entity_df_plus_pos = generate_animation_df(
        full_entity_df=full_entity_df,
        event_position_df=event_position_df,
        wrap_queues_at=wrap_queues_at,
        wrap_resources_at=wrap_resources_at,
        step_snapshot_max=step_snapshot_max,
        gap_between_entities=gap_between_entities,
        gap_between_resources=gap_between_resources,
        gap_between_resource_rows=gap_between_resource_rows,
        gap_between_queue_rows=gap_between_queue_rows,
        queue_direction=queue_direction,
        debug_mode=debug_mode,
        custom_entity_icon_list=custom_entity_icon_list,
        time_col_name=time_col_name,
        entity_col_name=entity_col_name,
        event_type_col_name=event_type_col_name,
        event_col_name=event_col_name,
        resource_col_name=resource_col_name,
        step_snapshot_limit_gauges=step_snapshot_limit_gauges,
        gauge_max_override=gauge_max_override,
        gauge_segments=gauge_segments,
        run_col_name=run_col_name,
    )

    if debug_write_intermediate_objects:
        full_entity_df_plus_pos.to_csv("output_generate_animation_df.csv")

    animation = generate_animation(
        full_entity_df_plus_pos=full_entity_df_plus_pos,
        event_position_df=event_position_df,
        scenario=scenario,
        simulation_time_unit=simulation_time_unit,
        plotly_height=plotly_height,
        plotly_width=plotly_width,
        include_play_button=include_play_button,
        add_background_image=add_background_image,
        display_stage_labels=display_stage_labels,
        entity_icon_size=entity_icon_size,
        resource_icon_size=resource_icon_size,
        text_size=text_size,
        gap_between_resource_rows=gap_between_resource_rows,
        override_x_max=override_x_max,
        override_y_max=override_y_max,
        start_date=start_date,
        start_time=start_time,
        time_display_units=time_display_units,
        setup_mode=setup_mode,
        resource_opacity=resource_opacity,
        wrap_resources_at=wrap_resources_at,
        gap_between_resources=gap_between_resources,
        queue_direction=queue_direction,
        flip_entity_icons=flip_entity_icons,
        entity_icon_font=entity_icon_font,
        entity_icon_font_weight=entity_icon_font_weight,
        entity_colour_by=entity_colour_by,
        entity_colour_map=entity_colour_map,
        show_entity_legend=show_entity_legend,
        entity_annotation_by=entity_annotation_by,
        entity_annotation_size=entity_annotation_size,
        entity_annotation_color=entity_annotation_color,
        entity_annotation_offset_y=entity_annotation_offset_y,
        resource_image_size=resource_image_size,
        custom_resource_icon=custom_resource_icon,
        frame_duration=frame_duration,  # milliseconds
        frame_transition_duration=frame_transition_duration,  # milliseconds
        debug_mode=debug_mode,
        time_col_name=time_col_name,
        entity_col_name=entity_col_name,
        event_col_name=event_col_name,
        event_type_col_name=event_type_col_name,
        resource_col_name=resource_col_name,
        background_image_opacity=background_image_opacity,
        overflow_text_color=overflow_text_color,
        stage_label_text_colour=stage_label_text_colour,
        plot_bgcolor=plot_bgcolor,
        paper_bgcolor=paper_bgcolor,
        backend=backend,
        hover_text_entity=hover_text_entity,
        custom_hover_data=custom_hover_data,
        run_col_name=run_col_name,
    )

    if debug_mode:
        end_time_function = time.perf_counter()
        print(
            f"Total Time Elapsed: {(end_time_function - start_time_function):.2f} seconds"
        )

    return animation


def add_repeating_overlay(
    fig: go.Figure,
    overlay_text: str,
    first_start_frame: int,
    on_duration_frames: float,
    off_duration_frames: float,
    rect_color: str = "grey",
    rect_opacity: float = 0.5,
    text_size: int = 40,
    text_font_color: str = "white",
    relative_text_position_x: int = 0.5,
    relative_text_position_y: int = 0.5,
) -> go.Figure:
    """
     Add a repeating overlay (rectangle and text) to an animated Plotly figure
     using traces.

     This function adds overlay elements as additional traces rather than
     layout shapes/annotations, which enables the overlay to work without
     requiring redraw=True during animation. The overlay follows a repeating
     on/off pattern starting from a specified frame.

     Parameters
     ----------
     fig : plotly.graph_objects.Figure
         The animated Plotly figure object to modify.
     overlay_text : str
         The text to display in the overlay.
     first_start_frame : int
         The frame index where the overlay first appears. Must be >= 0.
     on_duration_frames : float
         The number of frames the overlay remains visible. Will be converted
         to int.
     off_duration_frames : float
         The number of frames the overlay is hidden between appearances. Will
         be converted to int.
     rect_color : str, default 'grey'
         The background color of the overlay rectangle. Accepts any valid CSS
         color string
         (e.g., 'red', '#FF0000', 'rgba(255,0,0,0.5)').
     rect_opacity : float, default 0.5
         The opacity of the overlay rectangle. Must be between 0 (transparent)
         and 1 (opaque).
     text_size : int, default 40
         The font size of the overlay text in points.
     text_font_color : str, default 'white'
         The color of the overlay text. Accepts any valid CSS color string.
     relative_text_position_x : float, default 0.5
         The horizontal position of the text within the overlay rectangle.
         0.0 = left edge, 0.5 = center, 1.0 = right edge.
     relative_text_position_y : float, default 0.5
         The vertical position of the text within the overlay rectangle.
         0.0 = bottom edge, 0.5 = center, 1.0 = top edge.

     Returns
     -------
     plotly.graph_objects.Figure
         The modified Plotly figure object with the repeating overlay added as
         traces. The original figure is modified in-place and also returned.

     Notes
     -----
     - The overlay uses secondary axes (x2, y2) to position elements in paper
       coordinates (0 to 1 range) independent of the main plot's data
       coordinates.
     - The overlay pattern repeats with a cycle length of (on_duration_frames
       + off_duration_frames).
     - Frame indexing is 0-based, so first_start_frame=0 means the overlay
       starts from the first frame.
     - The condition `i > start_frame` ensures the overlay doesn't appear on
       the initial frame unless explicitly specified.
     - This implementation works without requiring redraw=True in animation
       configurations, making it more efficient for complex animated plots.
    - returns UserWarning
         If the figure has no frames, a warning is printed and the figure is
         returned unchanged.
     - returns UserWarning
         If the sum of on_duration_frames and off_duration_frames is not
         positive, a warning is printed and the figure is returned unchanged.
    """
    on_frames = int(on_duration_frames)
    off_frames = int(off_duration_frames)
    start_frame = int(first_start_frame)

    num_frames = len(fig.frames)
    if num_frames == 0:
        print("⚠️ Warning: Figure has no frames. Overlay will not be animated.")
        return fig

    cycle_length = on_frames + off_frames
    if cycle_length <= 0:
        print(
            "⚠️ Warning: Sum of on/off duration is not positive. Cannot create pattern."
        )
        return fig

    # Create visibility pattern for each frame
    overlay_visibility = []
    for i in range(num_frames):
        is_on = False
        if i > start_frame:
            cycle_pos = (i - start_frame) % cycle_length
            if cycle_pos < on_frames:
                is_on = True
        overlay_visibility.append(is_on)

    # Determine what frame 0 should show
    frame_0_visible = overlay_visibility[0] if overlay_visibility else False

    # Add rectangle trace - match frame 0 visibility
    if frame_0_visible:
        rect_x = [0, 1, 1, 0, 0]
        rect_y = [0, 0, 1, 1, 0]
    else:
        rect_x = []
        rect_y = []

    fig.add_trace(
        go.Scatter(
            x=rect_x,
            y=rect_y,
            mode="lines",
            fill="toself",
            fillcolor=rect_color,
            opacity=rect_opacity,
            line=dict(width=0),
            xaxis="x2",  # Use secondary axis for paper coordinates
            yaxis="y2",
            showlegend=False,
            hoverinfo="skip",
            name="overlay_rect",
        )
    )

    # Add text trace - match frame 0 visibility
    if frame_0_visible:
        text_x = [relative_text_position_x]
        text_y = [relative_text_position_y]
        text_content = [overlay_text]
    else:
        text_x = []
        text_y = []
        text_content = []

    fig.add_trace(
        go.Scatter(
            x=text_x,
            y=text_y,
            mode="text",
            text=text_content,
            textfont=dict(size=text_size, color=text_font_color),
            xaxis="x2",
            yaxis="y2",
            showlegend=False,
            hoverinfo="skip",
            name="overlay_text",
        )
    )

    # Configure secondary axes to match paper coordinates
    fig.update_layout(
        xaxis2=dict(
            overlaying="x",
            range=[0, 1],
            showgrid=False,
            showticklabels=False,
            zeroline=False,
        ),
        yaxis2=dict(
            overlaying="y",
            range=[0, 1],
            showgrid=False,
            showticklabels=False,
            zeroline=False,
        ),
    )

    # Update frame data to include overlay traces
    rect_trace_idx = len(fig.data) - 2  # Rectangle trace index
    text_trace_idx = len(fig.data) - 1  # Text trace index

    for i, frame in enumerate(fig.frames):
        # Add overlay trace data to each frame
        if overlay_visibility[i]:
            # Overlay should be visible
            rect_data = go.Scatter(
                x=[0, 1, 1, 0, 0],
                y=[0, 0, 1, 1, 0],
                mode="lines",
                fill="toself",
                fillcolor=rect_color,
                opacity=rect_opacity,
                line=dict(width=0),
                xaxis="x2",
                yaxis="y2",
            )
            text_data = go.Scatter(
                x=[relative_text_position_x],
                y=[relative_text_position_y],
                mode="text",
                text=[overlay_text],
                textfont=dict(size=text_size, color=text_font_color),
                xaxis="x2",
                yaxis="y2",
            )
        else:
            # Overlay should be hidden (empty data)
            rect_data = go.Scatter(x=[], y=[], xaxis="x2", yaxis="y2")
            text_data = go.Scatter(x=[], y=[], mode="text", xaxis="x2", yaxis="y2")

        # Extend frame data to include overlay traces
        frame_data = list(frame.data) if frame.data else []

        # Ensure we have the right number of traces
        while len(frame_data) <= text_trace_idx:
            frame_data.append(go.Scatter(x=[], y=[]))

        # Update overlay traces
        frame_data[rect_trace_idx] = rect_data
        frame_data[text_trace_idx] = text_data

        # Update frame
        frame.data = frame_data

    if rect_opacity > 0:
        _enable_frame_redraw(fig)

    return fig


def _enable_frame_redraw(fig: go.Figure) -> None:
    """Force ``redraw=True`` on the play button and every slider step.

    Plotly's default animation only re-styles existing traces
    (``redraw=False``); a trace whose *type* changes between frames, or one on a
    secondary axis, needs a full redraw or it renders once and then freezes.
    Shared by :func:`add_repeating_overlay` and :func:`add_synchronised_trace`.
    """
    for updatemenu in fig.layout.updatemenus:
        if "buttons" in updatemenu and updatemenu["type"] == "buttons":
            for button in updatemenu["buttons"]:
                if "args" in button and len(button["args"]) > 1:
                    # args is [None, {frame: {...}, ...}]
                    if "frame" in button["args"][1]:
                        button["args"][1]["frame"]["redraw"] = True

    for slider in fig.layout.sliders:
        for step in slider["steps"]:
            if "args" in step and len(step["args"]) > 1:
                # args is [ [frame_name], {frame: {...}, ...} ]
                if "frame" in step["args"][1]:
                    step["args"][1]["frame"]["redraw"] = True


# A single trace, or several, or nothing - accepted anywhere the synchronised
# trace helpers take trace input. Frame data can also be a bare dict (the `go`
# animation backend stores it that way), so those are tolerated too.
_TraceInput: TypeAlias = Union[
    BaseTraceType, dict, Sequence[Union[BaseTraceType, dict]], None
]


def _as_trace_list(traces: _TraceInput) -> list:
    """Normalise ``None`` / a single trace / a sequence of traces to a list."""
    if traces is None:
        return []
    if isinstance(traces, (list, tuple)):
        return list(traces)
    return [traces]


def _traces_need_redraw(traces: Sequence) -> bool:
    """True if any trace can't be animated by a plain restyle.

    A trace whose *type* is not scatter (a bar, say), or one drawn on a
    secondary axis, needs ``redraw=True`` or it renders on the first frame and
    then freezes.
    """
    for trace in traces:
        if isinstance(trace, dict):
            ttype = trace.get("type")
            xaxis = trace.get("xaxis")
            yaxis = trace.get("yaxis")
        else:
            ttype = getattr(trace, "type", None)
            xaxis = getattr(trace, "xaxis", None)
            yaxis = getattr(trace, "yaxis", None)
        if ttype not in (None, "scatter", "scattergl"):
            return True
        if xaxis not in (None, "x") or yaxis not in (None, "y"):
            return True
    return False


def add_subplot_panels(
    fig: go.Figure,
    *,
    row_heights: Sequence[float],
    vertical_spacing: float = 0.05,
    subplot_titles: Optional[Sequence[str]] = None,
    hide_new_panel_axes: bool = True,
) -> go.Figure:
    """Re-home a vidigi animation into the top row of a stacked subplot grid.

    A vidigi animation is a plain single-axis Plotly figure. To show an extra
    chart beneath it (a running total, a per-frame bar panel, a growing line)
    the figure first needs a subplot grid it can share. This does the
    ``plotly.subplots.make_subplots`` scaffolding - including copying the private
    ``_grid_ref`` attribute, without which later ``fig.add_trace(..., row=2,
    col=1)`` calls cannot resolve the panel - so callers don't have to.

    Call this **before** :func:`add_synchronised_trace` /
    :func:`add_synchronised_trace_from_dataframe`: the target axes must exist
    before traces are placed on them.

    Parameters
    ----------
    fig : plotly.graph_objects.Figure
        The figure from :func:`generate_animation` or
        :func:`animate_activity_log`. Modified in place.
    row_heights : sequence of float
        One entry per row, top to bottom. ``row_heights[0]`` is the animation
        panel; there must be at least one row beneath it. Passed straight to
        ``make_subplots``.
    vertical_spacing : float, default 0.05
        Gap between rows, as a fraction of figure height.
    subplot_titles : sequence of str, optional
        One title per row (use ``""`` for rows with no title).
    hide_new_panel_axes : bool, default True
        Blank the grid lines, zero line, axis line and tick labels on the new
        panels (rows 2 onward). They are usually annotation strips rather than
        full charts; set ``False`` and restyle by hand if you want axes.

    Returns
    -------
    plotly.graph_objects.Figure
        The same figure, now backed by a subplot grid, with the animation in
        row 1 and empty panels below it.
    """
    n_rows = len(row_heights)
    if n_rows < 2:
        raise ValueError(
            "`row_heights` needs at least two entries: the vidigi animation "
            "panel plus at least one panel beneath it."
        )

    sp = make_subplots(
        rows=n_rows,
        cols=1,
        row_heights=list(row_heights),
        vertical_spacing=vertical_spacing,
        subplot_titles=subplot_titles,
    )

    # Shrink the existing animation into the first row's vertical band.
    fig.layout["xaxis"]["domain"] = sp.layout["xaxis"]["domain"]
    fig.layout["yaxis"]["domain"] = sp.layout["yaxis"]["domain"]

    # Bring across the axis for every new row.
    for i in range(2, n_rows + 1):
        fig.layout[f"xaxis{i}"] = sp.layout[f"xaxis{i}"]
        fig.layout[f"yaxis{i}"] = sp.layout[f"yaxis{i}"]

    # `_grid_ref` is what lets Plotly translate `row=`/`col=` on a later
    # `add_trace` into the right axis pair. It is private, but there is no
    # public way to graft a grid onto a figure that did not come from
    # `make_subplots`.
    fig._grid_ref = sp._grid_ref

    if hide_new_panel_axes:
        blank = dict(
            showgrid=False, zeroline=False, showline=False, showticklabels=False
        )
        updates = {}
        for i in range(2, n_rows + 1):
            updates[f"xaxis{i}"] = dict(blank)
            updates[f"yaxis{i}"] = dict(blank)
        fig.update_layout(**updates)

    return fig


def add_synchronised_trace(
    fig: go.Figure,
    frame_traces: Callable[[str, int], _TraceInput],
    *,
    static_traces: _TraceInput = None,
    initial_traces: _TraceInput = None,
    redraw: Optional[bool] = None,
) -> go.Figure:
    """Add extra traces to an animation, kept in step with its frames.

    A vidigi animation figure holds more traces in ``fig.data`` than in each
    ``fig.frames[i].data`` - the per-entity traces are animated, while the
    stage-label and resource-icon traces are static and simply left untouched as
    the animation plays. Adding your own animated trace by hand means
    reproducing that arrangement exactly, and getting it slightly wrong makes
    traces flicker, vanish after the first frame, or blank out the stage labels.

    This helper does it for you:

    - ``static_traces`` are added once and never re-sent per frame, so - like
      vidigi's own label/resource traces - they stay put for the whole
      animation.
    - ``frame_traces`` is called once per frame to build the animated trace(s)
      for that frame. It **must return the same number of traces every time**
      (return an empty trace such as ``go.Scatter(x=[], y=[])`` for frames with
      nothing to show); a mismatch raises ``ValueError`` naming the frame.
    - The existing frames' trace mapping is preserved, so the stage labels and
      resource icons keep rendering throughout.

    Parameters
    ----------
    fig : plotly.graph_objects.Figure
        An animated figure from :func:`generate_animation` /
        :func:`animate_activity_log`. Modified in place. If it has no frames a
        ``UserWarning`` is issued and it is returned unchanged.
    frame_traces : callable
        ``frame_traces(frame_name, frame_index) -> trace | list[trace]``. Called
        for every frame, in order. ``frame_name`` is ``fig.frames[i].name`` (the
        formatted time shown on the slider); ``frame_index`` is ``i``. Prefer
        ``frame_index`` for lookups - ``frame_name`` is reformatted by
        ``time_display_units`` and may not match your data.
    static_traces : trace or list of traces, optional
        Trace(s) shown identically on every frame - a target line, a fixed
        annotation, a reference band. Added to ``fig.data`` only.
    initial_traces : trace or list of traces, optional
        What to seed ``fig.data`` with for the animated slots (the state shown
        before Play is pressed). Defaults to ``frame_traces(frames[0].name, 0)``.
        Must have the same length as ``frame_traces`` returns.
    redraw : bool, optional
        Whether to force ``redraw=True`` on the play button and slider. ``None``
        (default) decides automatically: needed for non-scatter traces (bars) or
        traces on a secondary axis, not otherwise. Pass a bool to override.

    Returns
    -------
    plotly.graph_objects.Figure
        The same figure, with the extra traces added and every frame updated.

    See Also
    --------
    add_synchronised_trace_from_dataframe : convenience wrapper for the common
        case of a long-form DataFrame with one row per entity per time step.
    add_subplot_panels : make room for an extra chart panel first.
    """
    if not fig.frames:
        warnings.warn(
            "The figure has no animation frames, so there is nothing to keep a "
            "synchronised trace in step with. Returning the figure unchanged.",
            UserWarning,
            stacklevel=2,
        )
        return fig

    static_list = _as_trace_list(static_traces)

    # Build every frame's traces up front, so a ragged return aborts before the
    # figure has been touched.
    per_frame = [
        _as_trace_list(frame_traces(frame.name, i))
        for i, frame in enumerate(fig.frames)
    ]

    n_animated = len(per_frame[0])
    if n_animated == 0:
        raise ValueError(
            "`frame_traces` returned nothing for the first frame. It must "
            "return at least one trace per frame - use an empty trace such as "
            "go.Scatter(x=[], y=[]) for a frame with nothing to show."
        )
    for i, new in enumerate(per_frame):
        if len(new) != n_animated:
            raise ValueError(
                f"`frame_traces` returned {len(new)} trace(s) for frame {i} "
                f"({fig.frames[i].name!r}) but {n_animated} for the first "
                f"frame. It must return the same number of traces for every "
                f"frame."
            )

    seed = (
        _as_trace_list(initial_traces) if initial_traces is not None else per_frame[0]
    )
    if len(seed) != n_animated:
        raise ValueError(
            f"`initial_traces` has {len(seed)} trace(s) but `frame_traces` "
            f"returns {n_animated} per frame; they must match."
        )

    # Static traces first, then the animated ones, so the animated traces take
    # the final contiguous block of indices in `fig.data`.
    for trace in static_list:
        fig.add_trace(trace)
    for trace in seed:
        fig.add_trace(trace)

    animated_indices = list(range(len(fig.data) - n_animated, len(fig.data)))

    redraw_needed = _traces_need_redraw(static_list)

    for i, frame in enumerate(fig.frames):
        new = per_frame[i]
        base_data = list(frame.data)
        if frame.traces is not None:
            base_indices = list(frame.traces)
        else:
            # Plotly's default: frame trace k maps to fig.data[k]. vidigi's
            # frames carry only the per-entity traces, so this is [0 .. E-1] and
            # the trailing static traces are never disturbed.
            base_indices = list(range(len(base_data)))

        frame.data = tuple(base_data) + tuple(new)
        frame.traces = base_indices + animated_indices

        if _traces_need_redraw(new):
            redraw_needed = True

    if redraw is True or (redraw is None and redraw_needed):
        _enable_frame_redraw(fig)

    return fig


def add_synchronised_trace_from_dataframe(
    fig: go.Figure,
    data: pd.DataFrame,
    make_trace: Callable[[pd.DataFrame], _TraceInput],
    *,
    frame_time_col: str,
    match: Literal["index", "value"] = "index",
    accumulate: bool = False,
    static_traces: _TraceInput = None,
    redraw: Optional[bool] = None,
) -> go.Figure:
    """Add a synchronised trace built from a long-form DataFrame.

    A convenience wrapper over :func:`add_synchronised_trace` for the usual
    shape: a DataFrame with a time column, from which one (or more) trace is
    built per animation frame.

    Parameters
    ----------
    fig : plotly.graph_objects.Figure
        An animated figure from :func:`generate_animation` /
        :func:`animate_activity_log`. Modified in place.
    data : pandas.DataFrame
        Long-form data. The distinct values of ``frame_time_col``, sorted
        ascending, are the time steps.
    make_trace : callable
        ``make_trace(rows) -> trace | list[trace]``, where ``rows`` is the slice
        of ``data`` for the current frame (see ``accumulate``). Must return the
        same number of traces every call - return an empty trace (e.g.
        ``go.Bar(x=[], y=[])``) for a frame with no rows.
    frame_time_col : str
        Column of ``data`` identifying the time step of each row.
    match : {"index", "value"}, default "index"
        How data times line up with animation frames. ``"index"`` pairs the
        i-th distinct time with ``fig.frames[i]`` regardless of how the frame is
        labelled - robust to ``time_display_units`` - and raises ``ValueError``
        if the counts differ. ``"value"`` matches ``str(time) == str(frame.name)``
        instead, for when only some frames have data.
    accumulate : bool, default False
        ``False`` passes ``make_trace`` only the current time step's rows (a
        snapshot - e.g. a bar chart of the current state). ``True`` passes every
        row up to and including the current time (a cumulative view - e.g. a
        line that grows as the animation plays).
    static_traces, redraw
        Passed through to :func:`add_synchronised_trace`.

    Returns
    -------
    plotly.graph_objects.Figure
        The same figure, with the extra trace(s) added and every frame updated.
    """
    if frame_time_col not in data.columns:
        raise ValueError(
            f"`frame_time_col='{frame_time_col}'` is not a column of `data`. "
            f"Available columns: {sorted(str(c) for c in data.columns)}."
        )
    if match not in ("index", "value"):
        raise ValueError(f"`match` must be 'index' or 'value', not {match!r}.")

    ordered_times = sorted(data[frame_time_col].dropna().unique())

    if match == "index" and len(ordered_times) != len(fig.frames):
        raise ValueError(
            f"`match='index'` needs one distinct value of '{frame_time_col}' "
            f"per animation frame, but `data` has {len(ordered_times)} and the "
            f"figure has {len(fig.frames)}. Filter `data` down to the "
            f"animation's snapshot times, or pass `match='value'` to align on "
            f"frame name instead."
        )

    def _frame_traces(frame_name: str, frame_index: int) -> _TraceInput:
        if match == "index":
            current = ordered_times[frame_index]
        else:
            current = next(
                (t for t in ordered_times if str(t) == str(frame_name)), None
            )

        if current is None:
            rows = data.iloc[0:0]
        elif accumulate:
            rows = data[data[frame_time_col] <= current]
        else:
            rows = data[data[frame_time_col] == current]

        return make_trace(rows)

    return add_synchronised_trace(
        fig,
        _frame_traces,
        static_traces=static_traces,
        redraw=redraw,
    )
