"""What the Options tab draws, computed with the reference.

The curves are the falloff curves themselves. The path is the weight of every pose
while the drivers move straight from one pose to another, rotations along the
shorter arc, and half as far again past each. Nothing here needs Maya or Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

from . import reference as ref
from .definition import Definition, Pose

CURVE_X: Final[ref.FloatArray] = np.linspace(0.0, 2.0, 201)
"""Distance over radius, for the curves."""
PATH_T: Final[ref.FloatArray] = np.linspace(-0.5, 1.5, 201)
"""Positions along the path: the first pose at 0, the second at 1."""
ON_PATH: Final[float] = 0.02
"""How far off the path the drivers are still on it, over the distance between poses."""
_SAME_ROTATION: Final[float] = 1e-12
"""Below this, the rotation between two poses is none."""


def curves() -> dict[ref.Kernel, ref.FloatArray]:
    """Returns each falloff curve at ``CURVE_X``."""
    return {kernel: ref.falloff(kernel, CURVE_X) for kernel in ref.KERNELS}


def radius(definition: Definition) -> float:
    """Returns the radius *definition* uses, the automatic one when none is set.

    Raises:
        ValueError: When the RBF cannot be set up (no pose, no measure, or poses that
            cannot be told apart).
    """
    spec = definition.to_spec()
    return ref.radius_of(spec, ref.distances(spec, spec.poses, spec.poses))


@dataclass(frozen=True, slots=True, eq=False)
class Path:
    """The weights of every pose along the path through two poses.

    Attributes:
        weights: (len(PATH_T), N) each pose's weight at each position.
        total: (len(PATH_T),) the sum of the weights at each position.
    """

    weights: ref.FloatArray
    total: ref.FloatArray


def _multiply(a: ref.FloatArray, b: ref.FloatArray) -> ref.FloatArray:
    """Returns the quaternion products, row by row; either side may be one row."""
    av, aw = a[..., :3], a[..., 3:]
    bv, bw = b[..., :3], b[..., 3:]
    vector = aw * bv + bw * av + np.cross(av, bv)
    scalar = aw * bw - np.sum(av * bv, axis=-1, keepdims=True)
    return np.concatenate([vector, scalar], axis=-1)


def _arc(a: ref.FloatArray, b: ref.FloatArray, t: ref.FloatArray) -> ref.FloatArray:
    """Returns the rotations from *a* at 0 to *b* at 1 on the shorter arc, and past."""
    if float(a @ b) < 0.0:
        b = -b
    between = _multiply(a * np.array([-1.0, -1.0, -1.0, 1.0]), b)
    sine = float(np.linalg.norm(between[:3]))
    if sine < _SAME_ROTATION:
        return np.tile(a, (len(t), 1))
    half = np.arctan2(sine, between[3]) * t[:, None]
    steps = np.concatenate([between[:3] / sine * np.sin(half), np.cos(half)], axis=1)
    return _multiply(a, steps)


def _along(samples: ref.Samples, first: int, second: int) -> ref.Samples:
    """Returns one driver at each position of ``PATH_T``, from *first* to *second*."""
    t = PATH_T
    if isinstance(samples, ref.TransformSamples):
        q, p = samples.quaternions, samples.translations
        return ref.TransformSamples(
            _arc(q[first], q[second], t), p[first] + t[:, None] * (p[second] - p[first])
        )
    return samples[first] + t * (samples[second] - samples[first])


def path(definition: Definition, first: int, second: int) -> Path:
    """Returns every pose's weight while the drivers go from *first* to *second*.

    Raises:
        ValueError: When the two poses are the same, or the RBF cannot be set up.
        numpy.linalg.LinAlgError: When the pose table has no solution.
    """
    if first == second:
        raise ValueError("the path needs two different poses")
    spec = definition.to_spec()
    solved = ref.setup(spec)
    current = {
        port: _along(samples, first, second) for port, samples in spec.poses.items()
    }
    falloffs = ref.falloff(
        spec.kernel, ref.distances(spec, current, spec.poses) / solved.radius
    )
    weights = np.array([ref.pose_weights(spec, solved, row) for row in falloffs])
    return Path(weights, weights.sum(axis=1))


def distance(definition: Definition, first: int, second: int) -> float:
    """Returns how far pose *second* is from pose *first*, by the RBF's measures.

    Raises:
        ValueError: When the RBF has no pose or no driver with a measure.
    """
    spec = definition.to_spec()
    return float(ref.distances(spec, spec.poses, spec.poses)[first, second])


def locate(
    definition: Definition,
    first: int,
    second: int,
    drivers: dict[str, tuple[float, ...]],
) -> float | None:
    """Returns where the drivers are on the path from *first* to *second*, or None.

    Args:
        definition: The RBF.
        first: The pose at 0.
        second: The pose at 1.
        drivers: Each driver's state now, as a pose keeps it.

    Returns:
        The position on ``PATH_T`` nearest the drivers; None when it is farther than
        ``ON_PATH`` times the distance between the poses.

    Raises:
        ValueError: When the RBF has no pose or no driver with a measure.
    """
    spec = definition.to_spec()
    now = definition.replace(
        poses=(Pose("now", drivers),), values=(), transforms=()
    ).to_spec()
    along = {
        port: _along(samples, first, second) for port, samples in spec.poses.items()
    }
    gaps = ref.distances(spec, now.poses, along)[0]
    nearest = int(np.argmin(gaps))
    if gaps[nearest] > ON_PATH * distance(definition, first, second):
        return None
    return float(PATH_T[nearest])
