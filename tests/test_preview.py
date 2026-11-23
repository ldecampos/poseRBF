"""The Options tab's previews show what each option does to the RBF's own poses."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pytest

from poserbf import preview
from poserbf import reference as ref
from poserbf.definition import Definition, Driver, Options, Pose

AT_FIRST = int(np.argmin(np.abs(preview.PATH_T)))
AT_SECOND = int(np.argmin(np.abs(preview.PATH_T - 1.0)))
HALFWAY = int(np.argmin(np.abs(preview.PATH_T - 0.5)))


def test_every_curve_starts_at_one() -> None:
    for kernel, y in preview.curves().items():
        assert y[0] == pytest.approx(1.0), kernel


@pytest.mark.parametrize("kernel", ["linear", "cubic", "quintic"])
def test_bounded_curves_reach_zero_at_the_radius(kernel: ref.Kernel) -> None:
    y = preview.curves()[kernel]
    assert np.all(y[preview.CURVE_X >= 1.0] == 0.0)


def number_rbf(
    inputs: tuple[float, ...] = (0.0, 4.0, 10.0), **options: object
) -> Definition:
    """An RBF of one number driver with a pose at each input."""
    return Definition(
        (Driver("slider", "loc.slider", False),),
        tuple(Pose(f"pose{k}", {"slider": (x,)}) for k, x in enumerate(inputs)),
        options=Options(**options),  # pyright: ignore[reportArgumentType]
    )


def turn(degrees: float) -> tuple[float, ...]:
    """A transform driver's state: a turn about Z, at the origin."""
    half = math.radians(degrees) / 2
    return (0.0, 0.0, math.sin(half), math.cos(half), 0.0, 0.0, 0.0)


def rotation_rbf(**options: object) -> Definition:
    """An RBF of one joint turning about Z, with poses at 0, 90 and -60 degrees."""
    return Definition(
        (Driver("joint", "joint"),),
        tuple(
            Pose(name, {"joint": turn(angle)})
            for name, angle in (("rest", 0.0), ("up", 90.0), ("down", -60.0))
        ),
        options=Options(**options),  # pyright: ignore[reportArgumentType]
    )


def test_radius_is_the_automatic_one_unless_given() -> None:
    assert preview.radius(number_rbf((0.0, 2.0, 10.0))) == pytest.approx(1.5 * 4.0)
    assert preview.radius(number_rbf((0.0, 2.0, 10.0), radius=3.0)) == 3.0


@pytest.mark.parametrize("make", [number_rbf, rotation_rbf])
def test_interpolative_path_passes_through_both_poses(
    make: Callable[[], Definition],
) -> None:
    shown = preview.path(make(), 0, 1)
    np.testing.assert_allclose(shown.weights[AT_FIRST], [1.0, 0.0, 0.0], atol=1e-9)
    np.testing.assert_allclose(shown.weights[AT_SECOND], [0.0, 1.0, 0.0], atol=1e-9)


def test_rotation_path_is_halfway_between_the_poses() -> None:
    shown = preview.path(rotation_rbf(mode="additive", kernel="linear"), 0, 1)
    first, second, _ = shown.weights[HALFWAY]
    assert first == pytest.approx(second)
    assert first > 0.0


def test_additive_path_misses_the_poses() -> None:
    shown = preview.path(number_rbf(mode="additive"), 0, 1)
    assert shown.weights[AT_SECOND, 0] > 0.05


def test_a_margin_moves_the_path_off_the_poses() -> None:
    shown = preview.path(number_rbf(margin=0.5), 0, 1)
    assert shown.weights[AT_FIRST, 0] < 0.99


def test_normalize_always_makes_the_weights_add_up_to_one() -> None:
    shown = preview.path(number_rbf(normalize="always"), 0, 1)
    np.testing.assert_allclose(shown.total, 1.0, atol=1e-9)


def test_normalize_above_one_caps_the_total() -> None:
    free = preview.path(number_rbf(normalize="none"), 0, 2)
    capped = preview.path(number_rbf(normalize="above_one"), 0, 2)
    assert free.total.max() > 1.0
    assert capped.total.max() <= 1.0 + 1e-9


def test_clamp_leaves_no_negative_weight() -> None:
    free = preview.path(number_rbf(), 0, 1)
    clamped = preview.path(number_rbf(clamp_negative=True), 0, 1)
    assert free.weights.min() < 0.0
    assert clamped.weights.min() >= 0.0


def test_a_path_needs_two_poses() -> None:
    with pytest.raises(ValueError, match="two different poses"):
        preview.path(number_rbf(), 1, 1)


def number_state(x: float) -> dict[str, tuple[float, ...]]:
    """Returns the state of the number driver at *x*."""
    return {"slider": (x,)}


@pytest.mark.parametrize(("x", "expected"), [(0.0, 0.0), (4.0, 1.0), (2.0, 0.5)])
def test_a_number_driver_is_located_on_the_path(x: float, expected: float) -> None:
    assert preview.locate(number_rbf(), 0, 1, number_state(x)) == pytest.approx(
        expected
    )


def test_a_rotation_halfway_is_located_halfway() -> None:
    located = preview.locate(rotation_rbf(), 0, 1, {"joint": turn(45.0)})
    assert located == pytest.approx(0.5)


def test_drivers_off_the_path_are_not_located() -> None:
    plane = Definition(
        (Driver("a", "loc.a", False), Driver("b", "loc.b", False)),
        (
            Pose("rest", {"a": (0.0,), "b": (0.0,)}),
            Pose("right", {"a": (4.0,), "b": (0.0,)}),
        ),
    )
    assert preview.locate(plane, 0, 1, {"a": (2.0,), "b": (0.0,)}) == pytest.approx(0.5)
    assert preview.locate(plane, 0, 1, {"a": (2.0,), "b": (1.0,)}) is None


def test_drivers_past_the_drawn_path_are_not_located() -> None:
    assert preview.locate(number_rbf(), 0, 1, number_state(-4.0)) is None


def test_distance_between_two_poses() -> None:
    assert preview.distance(number_rbf(), 0, 1) == pytest.approx(4.0)
    assert preview.distance(rotation_rbf(), 0, 1) == pytest.approx(90.0)
