import pandas as pd
from pydantic import BaseModel, ValidationError
from typing import List, Optional

class EventPosition(BaseModel):
    """
    Pydantic model for a single event position.

    Attributes:
        event (str): The name of the event. These must match the event names as they appear in your event log.
        x (int): The x-coordinate for the event. This coordinate represents the bottom-right hand corner of the queue or resources.
        y (int): The y-coordinate. This coordinate represents the bottom-right hand corner of the queue or resources.
        label (str): The display label for the event. Used if display_stage_labels = True. This allows you to set a more display-friendly version of your event name (e.g. you might want to display start_queue_till as 'Queuing for Till').
        resource (Optional[str]): The optional resource associated with the event. This must match one of the resource names provided in your scenario object.
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
    with Plotly animation controls (specifically the ▶ buttons) in a Streamlit app. It searches the parent document
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
