"""Tests for the ``EventPosition`` model and ``create_event_position_df``.

These cover the ``direction`` field added for per-event queue build direction:
it must validate against the same closed set as the animation-wide
``queue_direction``, default to ``None``, and always surface as a column on the
DataFrame produced by ``create_event_position_df``. Also covers the ``flip_icons``
field, added for per-event entity/resource icon mirroring, which follows the same
"default None, always a column, per-row override with NaN fallback" shape.
"""

import pandas as pd
import pytest
from pydantic import ValidationError

from vidigi.utils import (
    EventPosition,
    _resolve_direction_sign,
    _resolve_icon_flip,
    create_event_position_df,
)


def test_direction_defaults_to_none():
    pos = EventPosition(event="waiting", x=100, y=200, label="Waiting")
    assert pos.direction is None


@pytest.mark.parametrize("value", ["left", "right"])
def test_direction_accepts_left_and_right(value):
    pos = EventPosition(event="waiting", x=1, y=2, label="W", direction=value)
    assert pos.direction == value


def test_direction_rejects_anything_else():
    with pytest.raises(ValidationError):
        EventPosition(event="waiting", x=1, y=2, label="W", direction="sideways")


def test_create_event_position_df_always_has_a_direction_column():
    df = create_event_position_df(
        [
            EventPosition(event="arrival", x=50, y=300, label="Arrival"),
            EventPosition(
                event="waiting", x=400, y=275, label="Waiting", direction="right"
            ),
        ]
    )
    assert list(df.columns) == [
        "event",
        "x",
        "y",
        "label",
        "resource",
        "direction",
        "flip_icons",
    ]
    assert df.loc[df["event"] == "arrival", "direction"].isna().all()
    assert df.loc[df["event"] == "waiting", "direction"].iloc[0] == "right"


# --------------------------------------------------------------------------- #
# flip_icons
# --------------------------------------------------------------------------- #


def test_flip_icons_defaults_to_none():
    pos = EventPosition(event="waiting", x=100, y=200, label="Waiting")
    assert pos.flip_icons is None


@pytest.mark.parametrize("value", [True, False])
def test_flip_icons_accepts_bools(value):
    pos = EventPosition(event="waiting", x=1, y=2, label="W", flip_icons=value)
    assert pos.flip_icons is value


def test_flip_icons_rejects_anything_else():
    # Not "yes"/"true"/2/etc - pydantic's lax bool coercion accepts those. This
    # needs a value with no sensible bool reading at all.
    with pytest.raises(ValidationError):
        EventPosition(event="waiting", x=1, y=2, label="W", flip_icons="sideways")


def test_create_event_position_df_always_has_a_flip_icons_column():
    df = create_event_position_df(
        [
            EventPosition(event="arrival", x=50, y=300, label="Arrival"),
            EventPosition(
                event="waiting", x=400, y=275, label="Waiting", flip_icons=True
            ),
        ]
    )
    assert df.loc[df["event"] == "arrival", "flip_icons"].isna().all()
    assert df.loc[df["event"] == "waiting", "flip_icons"].iloc[0] is True


# --------------------------------------------------------------------------- #
# _resolve_direction_sign
# --------------------------------------------------------------------------- #


def test_resolve_direction_sign_uses_the_default_when_no_column():
    df = pd.DataFrame({"x": [1, 2, 3]})
    assert _resolve_direction_sign(df, "left").tolist() == [-1, -1, -1]
    assert _resolve_direction_sign(df, "right").tolist() == [1, 1, 1]


def test_resolve_direction_sign_column_overrides_per_row_and_nan_falls_back():
    df = pd.DataFrame({"direction": ["right", None, "left"]})
    assert _resolve_direction_sign(df, "left").tolist() == [1, -1, -1]
    assert _resolve_direction_sign(df, "right").tolist() == [1, 1, -1]


def test_resolve_direction_sign_rejects_a_bad_default():
    with pytest.raises(ValueError, match="queue_direction"):
        _resolve_direction_sign(pd.DataFrame({"x": [1]}), "up")


def test_resolve_direction_sign_rejects_a_bad_column_value():
    with pytest.raises(ValueError, match="queue_direction"):
        _resolve_direction_sign(pd.DataFrame({"direction": ["diagonal"]}), "left")


# --------------------------------------------------------------------------- #
# _resolve_icon_flip
# --------------------------------------------------------------------------- #


def test_resolve_icon_flip_uses_the_default_when_no_column():
    df = pd.DataFrame({"x": [1, 2, 3]})
    assert _resolve_icon_flip(df, False).tolist() == [False, False, False]
    assert _resolve_icon_flip(df, True).tolist() == [True, True, True]


def test_resolve_icon_flip_column_overrides_per_row_and_nan_falls_back():
    df = pd.DataFrame({"flip_icons": [True, None, False]})
    assert _resolve_icon_flip(df, False).tolist() == [True, False, False]
    assert _resolve_icon_flip(df, True).tolist() == [True, True, False]


def test_resolve_icon_flip_rejects_a_bad_default():
    with pytest.raises(ValueError, match="flip_entity_icons"):
        _resolve_icon_flip(pd.DataFrame({"x": [1]}), "sideways")


def test_resolve_icon_flip_rejects_a_bad_column_value():
    with pytest.raises(ValueError, match="flip_entity_icons"):
        _resolve_icon_flip(pd.DataFrame({"flip_icons": ["yes"]}), False)
