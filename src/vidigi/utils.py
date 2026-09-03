import pandas as pd
from pydantic import BaseModel, ValidationError
from typing import List, Literal, Optional
import webcolors
import warnings
import numbers
import inspect
import re
from functools import wraps


# Which way a queue (or row of resources) builds out from its anchor point.
# ``"left"`` is the historic behaviour - the anchor is the front of the queue and
# entities stack up to its left. ``"right"`` mirrors it, so the anchor becomes the
# bottom-left corner and the queue extends rightwards (which suits entity emojis
# that face right). Shared between prep.py and animation.py so the signatures
# cannot drift; the value is still validated at runtime, since annotations are not
# enforced.
QueueDirection = Literal["left", "right"]


def _validate_queue_direction(value: str) -> str:
    """Normalise and check a queue-direction string, raising on anything else."""
    norm = str(value).strip().lower()
    if norm not in ("left", "right"):
        raise ValueError(
            f"`queue_direction` must be 'left' or 'right', got {value!r}."
        )
    return norm


def _resolve_direction_sign(df: pd.DataFrame, default: str) -> pd.Series:
    """``-1`` for a 'left'-building queue, ``+1`` for 'right' - one value per row.

    Uses the per-row ``direction`` column where present and non-null, falling back
    to ``default`` (the animation-wide ``queue_direction``). A frame with no
    ``direction`` column at all - the normal case for a CSV-built
    ``event_position_df`` - takes ``default`` throughout.
    """
    default = _validate_queue_direction(default)
    if "direction" in df.columns:
        raw = df["direction"].where(df["direction"].notna(), default)
    else:
        raw = pd.Series(default, index=df.index)
    raw = raw.map(_validate_queue_direction)
    return raw.map({"left": -1, "right": 1}).astype(int)


def _validate_icon_flip(value) -> bool:
    """Normalise and check a flip-icons value, raising on anything but a bool."""
    if isinstance(value, bool):
        return value
    raise ValueError(
        f"`flip_entity_icons` / `flip_icons` must be a bool, got {value!r}."
    )


def _resolve_icon_flip(df: pd.DataFrame, default: bool) -> pd.Series:
    """``True``/``False`` per row - whether that row's entity icon is mirrored.

    Uses the per-row ``flip_icons`` column where present and non-null, falling
    back to ``default`` (the animation-wide ``flip_entity_icons``). A frame with
    no ``flip_icons`` column at all - the normal case for a CSV-built
    ``event_position_df``, or any event that never sets it - takes ``default``
    throughout.
    """
    default = _validate_icon_flip(default)
    if "flip_icons" in df.columns:
        raw = df["flip_icons"].where(df["flip_icons"].notna(), default)
    else:
        raw = pd.Series(default, index=df.index)
    return raw.map(_validate_icon_flip).astype(bool)


class EventPosition(BaseModel):
    """
    Pydantic model for a single event position.

    This model defines the position and label of an event within a visual layout.
    Coordinates represent one corner of a queue or resource - the bottom-right by
    default, or the bottom-left when ``direction="right"`` - and an optional label,
    resource, or build direction can be associated with the event.

    Attributes
    ----------
    event : str
        The name of the event. Must match the event names as they appear in your event log.
    x : int
        The x-coordinate for the event. With the default ``direction="left"`` this
        is the bottom-right corner of the queue or resource (the front of the
        queue); with ``direction="right"`` it is the bottom-left corner instead.
    y : int
        The y-coordinate for the event. Represents the lowest row of the queue or
        the central point of the resources.
    label : str
        The display label for the event. Used if `display_stage_labels=True`.
        Allows for a more user-friendly version of the event name (e.g., 'Queuing for Till').
    resource : Optional[str]
        The optional resource associated with the event. Must match a resource name
        provided in your scenario object.
    direction : Optional[str]
        Which way this queue builds out from its anchor: ``"left"`` (entities stack
        up to the left of ``x``; the anchor is the bottom-right corner) or
        ``"right"`` (entities extend to the right; the anchor is the bottom-left
        corner - useful when entity emojis face right). ``None`` (the default)
        inherits the animation-wide ``queue_direction`` passed to
        ``animate_activity_log`` / ``generate_animation``.
    flip_icons : Optional[bool]
        Whether entity icons (and a ``custom_resource_icon``) at this event are
        mirrored horizontally - useful when an emoji faces the wrong way for this
        stage's layout. ``None`` (the default) inherits the animation-wide
        ``flip_entity_icons`` passed to ``animate_activity_log`` / ``generate_animation``.
        Requires the CSS from ``vidigi.utils.inject_icon_flip_css`` /
        ``entity_icon_flip_css`` to reach the page - see their docstrings.
    resource_icon : Optional[str]
        Overrides ``custom_resource_icon`` for this event's resources. A URL, a
        local file path, or a ``data:`` URI (judged by an image file extension
        or URL scheme - anything else is treated as a text glyph, exactly like
        ``custom_resource_icon``) is drawn as a static image instead of text.
        Unlike the entity icon flip, an image resource icon cannot be mirrored
        by ``flip_entity_icons`` - supply it pre-mirrored if needed.
    """

    event: str
    x: int
    y: int
    label: str
    resource: Optional[str] = None
    direction: Optional[QueueDirection] = None
    flip_icons: Optional[bool] = None
    resource_icon: Optional[str] = None


def create_event_position_df(
    event_positions: List[EventPosition],
) -> pd.DataFrame:
    """
    Creates a DataFrame for event positions from a list of EventPosition objects.

    Args:
        event_positions (List[EventPosition]): A list of EventPoisitions.

    Returns:
        pd.DataFrame: A DataFrame with the specified columns and data types.

    Raises:
        ValidationError: If the input data does not match the EventPosition model.
    """
    try:
        # Convert the list of Pydantic models to a list of dictionaries
        validated_data = [event.model_dump() for event in event_positions]

        # Create the DataFrame
        df = pd.DataFrame(validated_data)

        # Reorder columns to match the desired output
        df = df[
            ["event", "x", "y", "label", "resource", "direction", "flip_icons", "resource_icon"]
        ]

        _warn_on_duplicate_event_positions(
            df, source="create_event_position_df", stacklevel=2
        )

        return df
    except ValidationError as e:
        print(f"Error validating event position data: {e}")
        raise


#'''''''''''''''''''''''''''''''''''''#
# Webdev + visualisation helpers
#'''''''''''''''''''''''''''''''''''''#

# Zero-width space, prefixed onto an icon's text to mark it for mirroring. Plotly
# writes each trace's raw text onto its <text> element as a `data-unformatted`
# attribute (untouched by markup handling, so it is safe to match on) - this
# marker gives `ENTITY_ICON_FLIP_CSS` an attribute-prefix selector to hook onto,
# with no visible or layout effect of its own (it has no glyph and no advance
# width, so `text-anchor: middle` centring is unaffected).
#
# Built from the actual character rather than a "​"-style escape sequence
# in a CSS string, deliberately - CSS unicode escapes and Python string escapes
# both use a leading backslash, and it is easy to end up with the wrong one
# (`\200b` alone is a Python *octal* escape, not this character) without
# actually catching the mistake anywhere until a browser is involved.
ICON_FLIP_MARKER = "​"

ENTITY_ICON_FLIP_CSS = (
    "<style>\n"
    ".js-plotly-plot text[data-unformatted^=\"" + ICON_FLIP_MARKER + "\"] {\n"
    "  transform-box: fill-box;\n"
    "  transform-origin: center;\n"
    "  transform: scaleX(-1);\n"
    "}\n"
    "</style>"
)


def entity_icon_flip_css() -> str:
    """
    Return the ``<style>`` block that mirrors any entity icon marked with
    `ICON_FLIP_MARKER` - i.e. any icon vidigi has prefixed because
    `flip_entity_icons=True` or a per-event ``flip_icons=True`` resolved for it.

    A ``go.Figure`` cannot carry CSS itself, so this has to reach the page some
    other way. `inject_icon_flip_css` does that automatically for a notebook or
    Streamlit app; call this directly instead when embedding a figure some other
    way; for example, prepended to the output of ``fig.write_html()``, or via
    ``st.markdown(entity_icon_flip_css(), unsafe_allow_html=True)``.

    Note this only affects the interactive HTML/JS rendering - a static export
    via ``fig.write_image()`` renders in its own page and will not show the flip.

    Returns
    -------
    str
        A ``<style>...</style>`` block, safe to concatenate directly into HTML.
    """
    return ENTITY_ICON_FLIP_CSS


def _display_html(html: str) -> None:
    """Show an HTML string in whichever rich environment is actually active.

    Tries, in order: displaying it via IPython (notebooks, JupyterLab,
    Quarto/nbconvert execution), then `streamlit.markdown` (a Streamlit app). If
    neither is actually active, this is a silent no-op - the caller's own
    `*_css()` function returns the same HTML directly for that case (a plain
    script, or writing a figure out with ``fig.write_html()``).

    Shared by `inject_icon_flip_css` and `inject_icon_font_css`, so the two
    features reach the page the same way and cannot drift apart.
    """
    try:
        from IPython import get_ipython
        from IPython.display import display, HTML

        # IPython is a transitive dependency (via ipywidgets) even in a plain
        # script, where there is no rich frontend to display anything - checking
        # for an active shell avoids a stray "<IPython.core.display.HTML object>"
        # landing in that script's stdout.
        if get_ipython() is not None:
            display(HTML(html))
            return
    except ImportError:
        pass

    try:
        import streamlit as st

        st.markdown(html, unsafe_allow_html=True)
    except ImportError:
        pass


def inject_icon_flip_css() -> None:
    """
    Display the CSS that mirrors flipped entity icons, in whichever environment
    this is called from - see `_display_html`. If neither is actually active,
    this is a silent no-op - use `entity_icon_flip_css` directly instead (see
    its docstring for where to put the result) in a plain script, or when
    writing a figure out with ``fig.write_html()``.

    Called automatically by `generate_animation` / `animate_activity_log`
    whenever any entity icon actually resolves to flipped, so this normally
    does not need to be called directly.
    """
    _display_html(ENTITY_ICON_FLIP_CSS)


# Icon-font presets: a name -> the CSS needed to load it, all pre-aliased under a
# vidigi-chosen family name.
#
# This aliasing is not cosmetic - it works around a confirmed Plotly bug (plotly.js
# 6.7 and 5.12 both reproduce it): a `textfont.family` value containing a standalone
# number - exactly the shape of "Font Awesome 6 Free", the vendor's own official
# family name - is silently dropped with no error and no visible effect, verified by
# inspecting the written SVG `style` attribute directly (no `font-family` at all is
# present; every other property i.e. `font-weight` still is). "Font Awesome 6",
# "Font Awesome 5 Free", and made-up strings like "Test 6 Test" all reproduce it;
# "FontAwesome6Free" (no standalone digit token) does not, which is why the aliases
# below strip spaces around the model number, or drop it, rather than quoting it.
#
# Every preset also carries its own `@font-face` (or, for Material Symbols' Google
# Fonts hosting, a `<link>`) rather than trusting the vendor's stylesheet wholesale -
# both existing CDN stylesheets ship `font-display: block`, which combines badly with
# the second issue `entity_icon_font_css` works around (SVG text not triggering an
# automatic font fetch): once a browser commits to the fallback font for a `block`
# request, confirmed (Chromium) NOT to swap back for that already-painted text even
# after the real font finishes loading. Re-declaring under `font-display: swap` avoids
# relying on that swap ever happening in the first place.
ICON_FONT_PRESETS = {
    "font-awesome": {
        "family": "VidigiFontAwesomeSolid",
        "weight": 900,
        "src": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-solid-900.woff2",
    },
    "bootstrap-icons": {
        "family": "VidigiBootstrapIcons",
        "weight": 400,
        "src": "https://cdnjs.cloudflare.com/ajax/libs/bootstrap-icons/1.11.3/font/fonts/bootstrap-icons.woff2",
    },
    "material-symbols": {
        # Google's own family name - no standalone digit, so no alias is needed here.
        # A ligature font: the *text* "home" renders as the house glyph directly, so
        # unlike the other two presets this needs no codepoint lookup at all.
        "family": "Material Symbols Outlined",
        "weight": 400,
        "css_import": "https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined",
    },
}

# Matches a number that is its own token (surrounded by whitespace, or the string
# boundary once padded - see `_resolve_icon_font`), not a digit embedded in a word.
_STANDALONE_DIGIT_RE = re.compile(r"(?:^|\s)\d+(?:\s|$)")


def _resolve_icon_font(font: str, weight: Optional[int] = None):
    """Resolve a preset name or a raw CSS family string to ``(family, weight)``.

    A preset name (one of `ICON_FONT_PRESETS`) resolves to its pre-aliased family,
    with `weight` overriding the preset's default when given. Anything else is
    treated as a family string for a webfont already loaded some other way (a
    system font, or the caller's own `<link>`/`@font-face`) - checked for the
    same standalone-digit shape Plotly silently drops (see `ICON_FONT_PRESETS`),
    and raised on rather than left to fail invisibly.
    """
    if font in ICON_FONT_PRESETS:
        preset = ICON_FONT_PRESETS[font]
        return preset["family"], (weight if weight is not None else preset["weight"])

    if _STANDALONE_DIGIT_RE.search(f" {font} "):
        raise ValueError(
            f"`entity_icon_font={font!r}` contains a standalone number. Plotly silently "
            f"drops a `textfont.family` value shaped like that (confirmed on plotly.js "
            f"6.7 and 5.12) - which is exactly why the vendor's own family name, "
            f"'Font Awesome 6 Free', does not work directly, and why the built-in "
            f"presets ({', '.join(sorted(ICON_FONT_PRESETS))}) exist: they alias around "
            f"it. If you need a font whose real name has a number in it, declare your "
            f"own `@font-face` under a digit-free alias and pass that alias name here."
        )
    return font, weight


def entity_icon_font_css(font: str, weight: Optional[int] = None) -> str:
    """
    Return the HTML needed to render entity icons in `font`.

    This is more than a stylesheet link. Plotly draws icon text inside an SVG
    `<text>` element, and a browser's "does the page actually need this webfont"
    detection does not reliably notice SVG text - confirmed in Chromium, where a
    font can sit undownloaded indefinitely even though text asking for it never
    stops being on the page. The returned HTML therefore also includes a small
    hidden element set in the target font, which reliably forces the fetch
    regardless of that limitation.

    Also works around a second, unrelated Plotly bug where a `textfont.family`
    value shaped like the vendor's own name for several popular icon fonts is
    silently dropped - see the module-level comment on `ICON_FONT_PRESETS` for
    the detail, and `_resolve_icon_font` for what happens with a raw custom
    family string.

    Parameters
    ----------
    font : str
        One of `ICON_FONT_PRESETS` (currently `"font-awesome"`,
        `"bootstrap-icons"`, `"material-symbols"`), or any CSS font-family name
        already available on the page - a system font, or one loaded by your
        own `<link>` / `@font-face`.
    weight : int, optional
        Overrides a preset's default weight (Font Awesome ships Solid at 900
        and Regular at 400, say). Ignored for a raw custom family - pass the
        weight to `entity_icon_font_weight` instead, which is applied directly
        as `textfont.weight`.

    Returns
    -------
    str
        HTML - a `<link>` or `<style>` block, plus a hidden trigger element -
        safe to concatenate directly into a page, or pass to
        `inject_icon_font_css` to display it automatically. Requires network
        access to the relevant CDN at view time; nothing is bundled with vidigi.

    Notes
    -----
    Icon fonts are static glyphs, not colour fonts, so - unlike emoji -
    `textfont.color` (and so `entity_colour_by`) works on them.
    """
    family, resolved_weight = _resolve_icon_font(font, weight)
    preset = ICON_FONT_PRESETS.get(font)

    if preset is None:
        head = ""  # raw custom family - caller supplies their own @font-face/<link>
    elif "css_import" in preset:
        head = f'<link rel="stylesheet" href="{preset["css_import"]}">'
    else:
        head = (
            "<style>\n"
            "@font-face {\n"
            f'  font-family: "{family}";\n'
            "  font-style: normal;\n"
            f"  font-weight: {preset['weight']};\n"
            "  font-display: swap;\n"
            f'  src: url("{preset["src"]}") format("woff2");\n'
            "}\n"
            "</style>"
        )

    trigger_weight = resolved_weight if resolved_weight is not None else "normal"
    trigger = (
        f"<span style=\"font-family: '{family}'; font-weight: {trigger_weight}; "
        'position: absolute; visibility: hidden;">x</span>'
    )
    return head + "\n" + trigger


def inject_icon_font_css(font: str, weight: Optional[int] = None) -> None:
    """
    Display the HTML from `entity_icon_font_css` in whichever environment this
    is called from - see `_display_html` for the dispatch, and
    `entity_icon_font_css` for what it contains and why. If neither is
    actually active, this is a silent no-op - use `entity_icon_font_css`
    directly instead in a plain script, or when writing a figure out with
    ``fig.write_html()``.

    Called automatically by `generate_animation` / `animate_activity_log`
    whenever `entity_icon_font` is set, so this normally does not need to be
    called directly.
    """
    _display_html(entity_icon_font_css(font, weight))


# Recognised image sources for `resource_icon` / `EventPosition.resource_icon` - a
# value with one of these extensions or schemes is drawn as a static `layout.images`
# entry instead of scatter text. Kept narrow and explicit rather than "anything that
# isn't obviously an emoji", so a plain glyph is never misread as a broken file path.
_IMAGE_URL_SCHEMES = ("http://", "https://", "data:")
_IMAGE_FILE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp")


def _is_image_source(value: str) -> bool:
    """Whether `value` (a `resource_icon`) names an image rather than a text glyph."""
    if not isinstance(value, str):
        return False
    if value.startswith(_IMAGE_URL_SCHEMES):
        return True
    return value.lower().endswith(_IMAGE_FILE_SUFFIXES)


def streamlit_play_all():
    """
    Programmatically triggers all 'Play' buttons in Plotly animations embedded in Streamlit using JavaScript.

    This function uses the `streamlit_javascript` package to inject JavaScript that simulates user interaction
    with Plotly animation controls (specifically the play buttons) in a Streamlit app. It searches the parent document
    for all elements that resemble play buttons and simulates click events on them.

    The function is useful when you have Plotly charts with animation frames and want to automatically start all
    animations without requiring manual user clicks.

    Raises
    ------
    ImportError
        If the `streamlit_javascript` package is not installed. The package is required to run JavaScript within
        the Streamlit environment. It can be installed with: `pip install vidigi[helper]`

    Notes
    -----
    - There is often some small lag in triggering multiple buttons. At present, there seems to be no way to avoid this!
    - The JavaScript is injected as a promise that logs progress to the browser console.
    - If no play buttons are found, an error is logged to the console.
    - This function assumes the presence of Plotly figures with updatemenu buttons in the DOM.
    """
    try:
        from streamlit_javascript import st_javascript

        st_javascript(
            """new Promise((resolve, reject) => {
    console.log('You pressed the play button');

    const parentDocument = window.parent.document;

    // Define playButtons at the beginning
    const playButtons = parentDocument.querySelectorAll('g.updatemenu-button text');

    let buttonFound = false;

    // Create an array to hold the click events to dispatch later
    let clickEvents = [];

    // Loop through all found play buttons
    playButtons.forEach(button => {
        if (button.textContent.trim() === '▶') {
        console.log("Queueing click on button");
        const clickEvent = new MouseEvent('click', {
            view: window,
            bubbles: true,
            cancelable: true
        });

        // Store the click event in the array
        clickEvents.push(button.parentElement);
        buttonFound = true;
        }
    });

    // If at least one button is found, dispatch all events
    if (buttonFound) {
        console.log('Dispatching click events');
        clickEvents.forEach(element => {
        element.dispatchEvent(new MouseEvent('click', {
            view: window,
            bubbles: true,
            cancelable: true
        }));
        });

        resolve('All buttons clicked successfully');
    } else {
        reject('No play buttons found');
    }
    })
    .then((message) => {
    console.log(message);
    return 'Play clicks completed';
    })
    .catch((error) => {
    console.log(error);
    return 'Operation failed';
    })
    .then((finalMessage) => {
    console.log(finalMessage);
    });

    """
        )

    except ImportError:
        raise ImportError(
            "This function requires the dependency 'st_javascript', but this is not installed with vidigi by default. "
            "Install it with: pip install vidigi[helper]"
        )


def html_color_to_rgba(color_str, opacity):
    """
    Convert an HTML color name or hex code to an rgba string with specified opacity.
    """
    try:
        rgb = webcolors.name_to_rgb(color_str)
    except ValueError:
        try:
            rgb = webcolors.hex_to_rgb(color_str)
        except ValueError:
            raise ValueError(f"Unknown color: {color_str}")
    return f"rgba({rgb.red}, {rgb.green}, {rgb.blue}, {opacity})"


#'''''''''''''''''''''''''''''''''''''#
# Single-replication guards
#'''''''''''''''''''''''''''''''''''''#

# Column names commonly used to identify which replication a row belongs to.
# Matched case-insensitively when `run_col_name="auto"`.
RUN_COLUMN_CANDIDATES = ("run", "run_number", "replication", "rep", "run_id")

# Shared tail for both guards, so the two messages give the same routes out.
_SINGLE_RUN_GUIDANCE = (
    "vidigi animates a single replication at a time. Passing several does not raise "
    "on its own - it silently blends them into an animation that represents no run of "
    "your model - so this is rejected instead.\n"
    "\n"
    "  Filter to one replication first, e.g.:\n"
    "      {filter_example}\n"
    "\n"
    "  Using vidigi's TrialLogger? Get a single run with:\n"
    "      trial_logger.get_log_by_run(<run>, as_df=True)\n"
    "\n"
    "  If this column does not identify a replication, pass `run_col_name=None` to "
    "disable this check, or `run_col_name=\"<your column>\"` to point it at the right one."
)


def _resolve_run_column(df: pd.DataFrame, run_col_name="auto") -> Optional[str]:
    """Work out which column - if any - identifies the replication.

    Parameters
    ----------
    df : pd.DataFrame
        The frame being checked.
    run_col_name : str or None, default "auto"
        ``"auto"`` matches column names case-insensitively against
        `RUN_COLUMN_CANDIDATES`. ``None`` disables detection. Any other string
        names the column explicitly and must exist.

    Returns
    -------
    str or None
        The resolved column name, or None if detection is disabled or nothing matched.
    """
    if run_col_name is None:
        return None

    if run_col_name != "auto":
        if run_col_name not in df.columns:
            raise ValueError(
                f"`run_col_name` was given as '{run_col_name}', but that column is not "
                f"present. Available columns: {sorted(str(c) for c in df.columns)}. "
                f"Pass `run_col_name=None` to disable the single-replication check."
            )
        return run_col_name

    lowered = {str(col).lower(): col for col in df.columns}
    for candidate in RUN_COLUMN_CANDIDATES:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _check_single_run(
    df: pd.DataFrame,
    run_col_name="auto",
    frame_arg: str = "event_log",
) -> None:
    """Raise if `df` spans more than one replication.

    The run column survives `reshape_for_animations` and `generate_animation_df`
    unchanged, so this same check guards every stage of the pipeline.

    Parameters
    ----------
    df : pd.DataFrame
        Event log, reshaped frame, or positioned frame.
    run_col_name : str or None, default "auto"
        See `_resolve_run_column`.
    frame_arg : str
        Name of the calling function's parameter holding `df`, so the error can
        show a filter example using the caller's own argument name.
    """
    column = _resolve_run_column(df, run_col_name)
    if column is None:
        return

    values = pd.unique(df[column].dropna())
    if len(values) <= 1:
        return

    try:
        preview_values = sorted(values.tolist())
    except TypeError:
        # Mixed or unorderable types - show them in the order encountered.
        preview_values = list(values)

    shown = ", ".join(repr(v) for v in preview_values[:5])
    if len(preview_values) > 5:
        shown += ", ..."

    filter_example = (
        f'{frame_arg}[{frame_arg}["{column}"] == {preview_values[0]!r}]'
    )

    raise ValueError(
        f"`{frame_arg}` spans {len(preview_values)} replications: column '{column}' "
        f"holds {len(preview_values)} distinct values ({shown}).\n"
        "\n" + _SINGLE_RUN_GUIDANCE.format(filter_example=filter_example)
    )


def _check_one_arrival_per_entity(
    event_log: pd.DataFrame,
    entity_col_name: str = "entity_id",
    event_type_col_name: str = "event_type",
    event_col_name: str = "event",
    pathway_col_name: Optional[str] = None,
    frame_arg: str = "event_log",
) -> None:
    """Raise if any entity arrives or departs more than once.

    `reshape_for_animations` pivots the arrival/departure rows to work out when each
    entity was present. That pivot aggregates duplicates with a *mean*, so an entity
    with two arrivals is silently given a time it never arrived at.

    The grouping keys here deliberately mirror the pivot's index, so this predicts
    exactly when that aggregation would happen - no false positives, no gaps.

    The usual cause is several replications concatenated together, but reused entity
    IDs within a single run produce the same corruption and are caught too.
    """
    if event_type_col_name not in event_log.columns:
        return

    arrival_departure = event_log[
        event_log[event_type_col_name] == "arrival_departure"
    ]
    if arrival_departure.empty:
        return

    keys = [entity_col_name]
    if pathway_col_name is not None and pathway_col_name in event_log.columns:
        keys.append(pathway_col_name)

    for event_name in ("arrival", "depart"):
        subset = arrival_departure[arrival_departure[event_col_name] == event_name]
        if subset.empty:
            continue

        counts = subset.groupby(keys, dropna=False).size()
        offenders = counts[counts > 1]
        if offenders.empty:
            continue

        worst_key = offenders.idxmax()
        worst_count = int(offenders.max())
        filter_example = (
            f'{frame_arg}[{frame_arg}["run"] == 1]  # or whichever column identifies '
            f"your replication"
        )

        raise ValueError(
            f"`{frame_arg}` contains {len(offenders)} entities with more than one "
            f"'{event_name}' event (for example {entity_col_name}={worst_key!r} has "
            f"{worst_count}).\n"
            "\n"
            "vidigi assumes each entity arrives and departs once. Duplicates are "
            "averaged together when working out when an entity was present, which "
            "produces times it was never at.\n"
            "\n"
            "This usually means several replications have been concatenated into one "
            "log. It can also mean entity IDs are reused within a run - check that "
            "your model assigns each entity a unique ID.\n"
            "\n"
            f"  Filter to one replication first, e.g.:\n"
            f"      {filter_example}\n"
            "\n"
            "  Using vidigi's TrialLogger? Get a single run with:\n"
            "      trial_logger.get_log_by_run(<run>, as_df=True)"
        )


def _resource_map_from_event_position_df(
    event_position_df: pd.DataFrame, event_col_name: str = "event"
) -> dict:
    """Map each event with a declared resource to its scenario attribute name.

    `EventPosition.resource` holds the *name* of an attribute on a scenario
    object, not a capacity count - resolving `getattr(scenario, name)` is left
    to the caller, since `animation.py` wants one icon per resource unit and
    `vidigi.analysis._resolve_resource_capacities` wants a capacity per step,
    and the two fail differently when the named attribute is missing.

    Shared by both, so the definition of "this event has a resource" - a
    non-null `resource` column - cannot drift between them.

    Parameters
    ----------
    event_position_df : pandas.DataFrame
        E.g. the output of `create_event_position_df`. Must have `resource`
        and `event_col_name` columns for anything to be returned; a frame
        missing `resource` entirely (a purely queue-based model) is not an
        error, just empty.
    event_col_name : str, default="event"
        Column holding the event name.

    Returns
    -------
    dict
        `{event_name: resource_attribute_name}`, one entry per row where
        `resource` is not null.
    """
    if "resource" not in event_position_df.columns:
        return {}
    with_resource = event_position_df[event_position_df["resource"].notnull()]
    return dict(zip(with_resource[event_col_name], with_resource["resource"]))


def _warn_on_duplicate_event_positions(
    event_position_df,
    event_col_name: str = "event",
    *,
    source: str = "event_position_df",
    stacklevel: int = 3,
) -> None:
    """Warn about an event-position frame that makes entities appear to teleport.

    Two distinct problems share the same on-screen symptom - an entity flickering
    between positions from one frame to the next:

    - **The same event name on more than one row.**
      `generate_animation_df` does ``full_entity_df.merge(event_position_df,
      on=event, how="left")``, so every snapshot of a duplicated event fans out to
      *all* of its positions and the entity is drawn in several places at once.
    - **Two different events sharing an identical x/y.** Not corrupting, but almost
      always a copy-paste slip, and invisible in the finished animation except as
      two stages drawn on top of one another.

    Both are warnings, never errors: a duplicate does not stop an animation being
    produced, just makes it wrong, and this is the kind of thing worth flagging
    loudly rather than refusing outright.

    Parameters
    ----------
    event_position_df : pandas.DataFrame or anything ``pd.DataFrame`` accepts
        Usually the output of `create_event_position_df`, or a hand-built frame /
        list of dicts / dict of columns passed straight to `generate_animation_df`.
        Anything that cannot be coerced to a DataFrame is left alone - the real
        error will surface downstream.
    event_col_name : str, default "event"
        Column holding the event name.
    source : str
        Named in the warning so the reader knows which call produced it.
    stacklevel : int
        Passed through to `warnings.warn` so the warning points at the caller's
        code rather than into vidigi.
    """
    if not isinstance(event_position_df, pd.DataFrame):
        try:
            event_position_df = pd.DataFrame(event_position_df)
        except Exception:
            return

    if event_col_name not in event_position_df.columns:
        return

    events = event_position_df[event_col_name]

    duplicated = events[events.duplicated(keep=False)]
    if not duplicated.empty:
        counts = duplicated.value_counts()
        listed = ", ".join(
            f"{name!r} (x{int(count)})" for name, count in counts.items()
        )
        warnings.warn(
            f"`{source}` has the same event on more than one row: {listed}.\n"
            "\n"
            "Each event must map to exactly one position. vidigi joins entity "
            "snapshots to their position on the event name, so a duplicated event "
            "places every entity at that step in all of its positions at once - in "
            "the animation they appear to jump between the positions at random.\n"
            "\n"
            "Remove the extra rows so each event appears once.",
            UserWarning,
            stacklevel=stacklevel,
        )

    if "x" in event_position_df.columns and "y" in event_position_df.columns:
        distinct_events_here = event_position_df.groupby(
            ["x", "y"], dropna=False
        )[event_col_name].agg(lambda names: sorted(pd.unique(names).tolist()))
        collisions = distinct_events_here[
            distinct_events_here.map(len) > 1
        ]
        if not collisions.empty:
            listed = "; ".join(
                f"({x}, {y}): {', '.join(repr(n) for n in names)}"
                for (x, y), names in collisions.items()
            )
            warnings.warn(
                f"`{source}` places different events at identical coordinates: "
                f"{listed}.\n"
                "\n"
                "This is usually a copy-paste slip - the events will be drawn "
                "directly on top of each other, so entities at those steps look "
                "like they share a position. Give each event its own x/y if that "
                "was not intended.",
                UserWarning,
                stacklevel=stacklevel,
            )


def _ensure_int(value, name: str) -> int:
    if isinstance(value, numbers.Real):
        if not isinstance(value, int):
            rounded = round(value)
            warnings.warn(
                f"`{name}` was provided as {type(value).__name__} ({value}); "
                f"rounding to nearest integer ({rounded}).",
                UserWarning,
                stacklevel=3,
            )
            return rounded
        return int(value)
    raise TypeError(
        f"`{name}` must be an integer-like number, not {type(value).__name__}"
    )


def _enforce_int_params(param_names, allow_none=()):
    """Decorator to auto-check certain parameters are integer-like.

    Parameters
    ----------
    param_names : iterable of str
        Names of the parameters to coerce to integers.
    allow_none : iterable of str, optional
        Subset of `param_names` for which `None` is a documented, meaningful
        value. These are passed through untouched so the decorated function can
        apply its own handling, rather than being rejected here.
    """
    allow_none = set(allow_none)

    def decorator(func):
        sig = inspect.signature(func)

        @wraps(func)
        def wrapper(*args, **kwargs):
            # bind args+kwargs to parameter names
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()

            # validate the chosen parameters
            for name in param_names:
                if name in bound.arguments:
                    if bound.arguments[name] is None and name in allow_none:
                        continue
                    bound.arguments[name] = _ensure_int(
                        bound.arguments[name], name
                    )

            # call original function with validated arguments
            return func(*bound.args, **bound.kwargs)

        return wrapper

    return decorator
