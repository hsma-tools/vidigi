import pandas as pd
from pydantic import BaseModel, ValidationError
from typing import List, Literal, Optional
import webcolors
import warnings
import numbers
import inspect
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
    """

    event: str
    x: int
    y: int
    label: str
    resource: Optional[str] = None
    direction: Optional[QueueDirection] = None
    flip_icons: Optional[bool] = None


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
        df = df[["event", "x", "y", "label", "resource", "direction", "flip_icons"]]

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


def inject_icon_flip_css() -> None:
    """
    Display the CSS that mirrors flipped entity icons, in whichever environment
    this is called from.

    Tries, in order: displaying it as HTML via IPython (notebooks, JupyterLab,
    Quarto/nbconvert execution), then `streamlit.markdown` (a Streamlit app). If
    neither is actually active, this is a silent no-op - use
    `entity_icon_flip_css` directly instead (see its docstring for where to put
    the result) in a plain script, or when writing a figure out with
    ``fig.write_html()``.

    Called automatically by `generate_animation` / `animate_activity_log`
    whenever any entity icon actually resolves to flipped, so this normally
    does not need to be called directly.
    """
    try:
        from IPython import get_ipython
        from IPython.display import display, HTML

        # IPython is a transitive dependency (via ipywidgets) even in a plain
        # script, where there is no rich frontend to display anything - checking
        # for an active shell avoids a stray "<IPython.core.display.HTML object>"
        # landing in that script's stdout.
        if get_ipython() is not None:
            display(HTML(ENTITY_ICON_FLIP_CSS))
            return
    except ImportError:
        pass

    try:
        import streamlit as st

        st.markdown(ENTITY_ICON_FLIP_CSS, unsafe_allow_html=True)
    except ImportError:
        pass


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
