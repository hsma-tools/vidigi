import pandas as pd
from pydantic import BaseModel, ValidationError
from typing import List, Optional
import webcolors
import warnings
import numbers
import inspect
from functools import wraps


class EventPosition(BaseModel):
    """
    Pydantic model for a single event position.

    This model defines the position and label of an event within a visual layout.
    Coordinates represent the bottom-right corner of a queue or resource, and an
    optional label or resource can be associated with the event.

    Attributes
    ----------
    event : str
        The name of the event. Must match the event names as they appear in your event log.
    x : int
        The x-coordinate for the event. Represents the bottom-right corner of the queue or resource.
    y : int
        The y-coordinate for the event. Represents the bottom-right corner of the queue or resource.
    label : str
        The display label for the event. Used if `display_stage_labels=True`.
        Allows for a more user-friendly version of the event name (e.g., 'Queuing for Till').
    resource : Optional[str]
        The optional resource associated with the event. Must match a resource name
        provided in your scenario object.
    """

    event: str
    x: int
    y: int
    label: str
    resource: Optional[str] = None


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
        df = df[["event", "x", "y", "label", "resource"]]

        return df
    except ValidationError as e:
        print(f"Error validating event position data: {e}")
        raise


#'''''''''''''''''''''''''''''''''''''#
# Webdev + visualisation helpers
#'''''''''''''''''''''''''''''''''''''#
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
