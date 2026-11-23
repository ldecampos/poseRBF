"""The numpy reference keeps its own promises, with no Maya."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
import pytest

from poserbf import reference as ref

TOLERANCE = 1e-8
POSES, VALUES, TRANSFORMS = 7, 3, 2
MEASURES = (
    ref.Measure("rotation", factor=1.0),
    ref.Measure("swing", axis="y", factor=0.5),
    ref.Measure("twist", axis="y", factor=0.5),
    ref.Measure("translation", factor=10.0),
    ref.Measure("number", port="slider", factor=90.0),
)


def random_quaternions(rng: np.random.Generator, n: int) -> np.ndarray:
    """(n, 4) random unit quaternions with random signs."""
    q = rng.normal(size=(n, 4))
    return q / np.linalg.norm(q, axis=1, keepdims=True)


@dataclass(frozen=True, slots=True, eq=False)
class Rig:
    """Random poses of one transform driver and one number, and what they drive."""

    poses: ref.TransformSamples
    numbers: np.ndarray
    offsets: ref.Offsets
    values: np.ndarray
    rest: np.ndarray

    def spec(self, **options: object) -> ref.Spec:
        """The reference's spec of this rig with *options*."""
        return ref.Spec(
            MEASURES,
            {"driver": self.poses, "slider": self.numbers},
            values=self.values,
            offsets=self.offsets,
            **options,  # pyright: ignore[reportArgumentType]
        )

    def at_pose(self, index: int) -> dict[str, ref.Samples]:
        """The drivers exactly at pose *index*."""
        return {
            "driver": ref.TransformSamples(
                self.poses.quaternions[index : index + 1],
                self.poses.translations[index : index + 1],
            ),
            "slider": self.numbers[index : index + 1],
        }


FAR: dict[str, ref.Samples] = {
    "driver": ref.TransformSamples(
        np.array([[0.0, 0.0, 0.0, 1.0]]), np.array([[1e4, 0.0, 0.0]])
    ),
    "slider": np.array([0.5]),
}


@pytest.fixture
def rig() -> Rig:
    """The same random rig for every test."""
    rng = np.random.default_rng(7)
    return Rig(
        poses=ref.TransformSamples(
            random_quaternions(rng, POSES), rng.normal(size=(POSES, 3))
        ),
        numbers=rng.uniform(0.0, 1.0, size=POSES),
        offsets=ref.Offsets(
            rng.normal(size=(POSES, TRANSFORMS, 3)),
            random_quaternions(rng, POSES * TRANSFORMS).reshape(POSES, TRANSFORMS, 4),
            rng.uniform(0.5, 1.5, size=(POSES, TRANSFORMS, 3)),
        ),
        values=rng.normal(size=(POSES, VALUES)),
        rest=rng.normal(size=VALUES),
    )


@pytest.mark.parametrize("kernel", ref.KERNELS)
def test_interpolative_is_exact_at_every_pose(rig: Rig, kernel: ref.Kernel) -> None:
    spec = rig.spec(kernel=kernel, rest_values=rig.rest)
    solved = ref.setup(spec)
    for index in range(POSES):
        result = ref.evaluate(spec, solved, rig.at_pose(index))
        expected = ref.compose(
            rig.offsets.translations[index],
            ref.aligned_quaternions(rig.offsets.quaternions[index]),
            rig.offsets.scales[index],
        )
        np.testing.assert_allclose(result.weights, np.eye(POSES)[index], atol=TOLERANCE)
        np.testing.assert_allclose(result.values, rig.values[index], atol=TOLERANCE)
        np.testing.assert_allclose(result.matrices, expected, atol=TOLERANCE)


@pytest.mark.parametrize("kernel", ref.KERNELS)
def test_margin_stays_finite_at_the_poses(rig: Rig, kernel: ref.Kernel) -> None:
    spec = rig.spec(kernel=kernel, margin=0.01, rest_values=rig.rest)
    solved = ref.setup(spec)
    for index in range(POSES):
        result = ref.evaluate(spec, solved, rig.at_pose(index))
        assert np.isfinite(result.matrices).all()


def test_far_from_every_pose_returns_to_rest(rig: Rig) -> None:
    spec = rig.spec(kernel="cubic", rest_values=rig.rest)
    result = ref.evaluate(spec, ref.setup(spec), FAR)
    np.testing.assert_allclose(result.values, rig.rest, atol=1e-9)
    np.testing.assert_allclose(
        result.matrices, np.broadcast_to(np.eye(4), result.matrices.shape), atol=1e-9
    )


def test_additive_far_away_gives_one_matrix_per_transform(rig: Rig) -> None:
    spec = rig.spec(mode="additive")
    result = ref.evaluate(spec, ref.setup(spec), FAR)
    assert result.matrices.shape == (TRANSFORMS, 4, 4)


def copy_drivers(rig: Rig, source: int, target: int) -> Rig:
    """*rig* with pose *target* at the driver values of pose *source*."""
    quaternions = rig.poses.quaternions.copy()
    translations = rig.poses.translations.copy()
    numbers = rig.numbers.copy()
    quaternions[target] = quaternions[source]
    translations[target] = translations[source]
    numbers[target] = numbers[source]
    return dataclasses.replace(
        rig, poses=ref.TransformSamples(quaternions, translations), numbers=numbers
    )


def test_two_poses_at_the_same_driver_values_are_named(rig: Rig) -> None:
    spec = copy_drivers(rig, 5, 2).spec(rest_values=rig.rest)
    with pytest.raises(ref.SamePosesError) as raised:
        ref.setup(spec)
    assert raised.value.pair == (2, 5)


def test_a_margin_solves_two_poses_at_the_same_driver_values(rig: Rig) -> None:
    spec = copy_drivers(rig, 5, 2).spec(margin=0.01, rest_values=rig.rest)
    assert np.isfinite(ref.setup(spec).cardinal).all()
