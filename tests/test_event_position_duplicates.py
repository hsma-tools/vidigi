"""Tests for the duplicate / colliding event-position warnings (issue #219).

`event_position_df` must map each event name to exactly one ``(x, y)`` anchor.
Two mistakes are easy to make and invisible in the finished animation except as
an entity flickering between two spots:

- the same event name on more than one row - the left-merge in
  ``generate_animation_df`` then fans every snapshot of that event out to all of
  its positions;
- two *different* events sharing an identical ``x``/``y``.

Both now raise a ``UserWarning`` - at ``create_event_position_df`` (where the
frame is built from the typed helper) and at ``generate_animation_df`` (where a
hand-built frame, list of dicts or dict of columns is first consumed).
"""

import warnings

import pandas as pd
import pytest

from vidigi.prep import generate_animation_df, reshape_for_animations
from vidigi.utils import (
    EventPosition,
    _warn_on_duplicate_event_positions,
    create_event_position_df,
)


# --------------------------------------------------------------------------- #
# create_event_position_df
# --------------------------------------------------------------------------- #


def test_create_event_position_df_warns_on_a_duplicate_event():
    with pytest.warns(UserWarning, match=r"same event on more than one row"):
        create_event_position_df(
            [
                EventPosition(event="waiting", x=100, y=200, label="Waiting"),
                EventPosition(event="waiting", x=300, y=200, label="Waiting more"),
                EventPosition(event="depart", x=270, y=70, label="Exit"),
            ]
        )


def test_duplicate_warning_names_every_offending_event_with_its_count():
    with pytest.warns(UserWarning) as record:
        create_event_position_df(
            [
                EventPosition(event="waiting", x=1, y=1, label="a"),
                EventPosition(event="waiting", x=2, y=2, label="b"),
                EventPosition(event="waiting", x=3, y=3, label="c"),
                EventPosition(event="treatment", x=4, y=4, label="d"),
                EventPosition(event="treatment", x=5, y=5, label="e"),
            ]
        )
    messages = [str(w.message) for w in record]
    dup_message = next(m for m in messages if "same event on more than one row" in m)
    # The whole set, with counts - not a sampled entry.
    assert "'waiting' (x3)" in dup_message
    assert "'treatment' (x2)" in dup_message


def test_create_event_position_df_warns_on_identical_coordinates():
    with pytest.warns(UserWarning, match=r"identical coordinates"):
        create_event_position_df(
            [
                EventPosition(event="waiting", x=300, y=200, label="Waiting"),
                EventPosition(event="treatment", x=300, y=200, label="Treatment"),
                EventPosition(event="depart", x=270, y=70, label="Exit"),
            ]
        )


def test_coordinate_warning_names_the_full_colliding_group():
    with pytest.warns(UserWarning) as record:
        create_event_position_df(
            [
                EventPosition(event="a", x=10, y=20, label="a"),
                EventPosition(event="b", x=10, y=20, label="b"),
                EventPosition(event="c", x=10, y=20, label="c"),
                EventPosition(event="d", x=99, y=99, label="d"),
            ]
        )
    coord_message = next(
        str(w.message) for w in record if "identical coordinates" in str(w.message)
    )
    assert "(10, 20)" in coord_message
    for name in ("'a'", "'b'", "'c'"):
        assert name in coord_message
    # The non-colliding event is not dragged into the message.
    assert "'d'" not in coord_message


def test_create_event_position_df_clean_input_is_silent():
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        create_event_position_df(
            [
                EventPosition(event="arrival", x=50, y=300, label="Arrival"),
                EventPosition(event="waiting", x=400, y=275, label="Waiting"),
                EventPosition(event="depart", x=270, y=70, label="Exit"),
            ]
        )
    assert [str(w.message) for w in record] == []


def test_same_event_at_the_same_coordinates_warns_once_not_twice():
    # A pure duplicate (identical name *and* coordinates) is the duplicate-event
    # problem, not a distinct-events collision - it must not be double-reported.
    with pytest.warns(UserWarning) as record:
        create_event_position_df(
            [
                EventPosition(event="waiting", x=100, y=200, label="Waiting"),
                EventPosition(event="waiting", x=100, y=200, label="Waiting"),
            ]
        )
    messages = [str(w.message) for w in record]
    assert sum("same event on more than one row" in m for m in messages) == 1
    assert not any("identical coordinates" in m for m in messages)


# --------------------------------------------------------------------------- #
# _warn_on_duplicate_event_positions directly - non-DataFrame inputs
# --------------------------------------------------------------------------- #


def test_helper_handles_a_list_of_dicts():
    with pytest.warns(UserWarning, match="same event on more than one row"):
        _warn_on_duplicate_event_positions(
            [
                {"event": "a", "x": 1, "y": 2},
                {"event": "a", "x": 3, "y": 4},
            ]
        )


def test_helper_handles_a_dict_of_columns():
    with pytest.warns(UserWarning, match="same event on more than one row"):
        _warn_on_duplicate_event_positions(
            {"event": ["a", "a"], "x": [1, 1], "y": [2, 2]}
        )


def test_helper_does_not_raise_on_uncoercible_input():
    # Neither warns nor raises - the real error surfaces downstream.
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        _warn_on_duplicate_event_positions(object())
    assert [str(w.message) for w in record] == []


def test_helper_respects_a_custom_event_column_name():
    with pytest.warns(UserWarning, match="same event on more than one row"):
        _warn_on_duplicate_event_positions(
            pd.DataFrame({"step": ["a", "a"], "x": [1, 2], "y": [3, 4]}),
            event_col_name="step",
        )


def test_helper_missing_event_column_is_silent():
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        _warn_on_duplicate_event_positions(pd.DataFrame({"x": [1, 1], "y": [2, 2]}))
    assert [str(w.message) for w in record] == []


# --------------------------------------------------------------------------- #
# generate_animation_df - point of use
# --------------------------------------------------------------------------- #


def test_generate_animation_df_warns_on_a_hand_built_duplicate(simple_queue_log):
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    event_position_df = pd.DataFrame(
        [
            {"event": "arrival", "x": 50, "y": 300, "label": "Arrival"},
            {"event": "waiting", "x": 400, "y": 275, "label": "Waiting"},
            {"event": "waiting", "x": 200, "y": 275, "label": "Waiting again"},
            {"event": "depart", "x": 270, "y": 70, "label": "Exit"},
        ]
    )
    with pytest.warns(UserWarning, match="same event on more than one row"):
        generate_animation_df(reshaped, event_position_df)


def test_generate_animation_df_clean_positions_do_not_warn(
    simple_queue_log, basic_event_position_df
):
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        generate_animation_df(reshaped, basic_event_position_df)
    dupe_warnings = [
        str(w.message)
        for w in record
        if "event on more than one row" in str(w.message)
        or "identical coordinates" in str(w.message)
    ]
    assert dupe_warnings == []
