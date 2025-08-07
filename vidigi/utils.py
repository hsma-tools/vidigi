import pandas as pd
from pydantic import BaseModel, ValidationError
from typing import List, Optional
import webcolors

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

def create_event_position_df(event_positions: List[EventPosition]) -> pd.DataFrame:
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
        df = df[['event', 'x', 'y', 'label', 'resource']]

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

        st_javascript("""new Promise((resolve, reject) => {
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

    """)

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
