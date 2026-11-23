"""The pose RBF in numpy: the numbers the Bifrost graph reproduces.

The RBF compares its drivers with N poses and gives each pose a weight; the weights
blend M driven values and J driven transforms. Rotation, swing and twist distances
are in degrees, translation in scene units and a number by its difference. Factors
scale each one, and the distance to a pose is the root of their sum of squares. The
falloff of the distance over the radius is each pose's influence; interpolative
mode solves the poses against each other, so each weighs 1 at itself. Driven values
blend from rest and driven transforms from the identity, so both return to rest far
from every pose. Matrices follow Maya's row-vector convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, TypeAlias

import numpy as np
import numpy.typing as npt

FloatArray: TypeAlias = npt.NDArray[np.float64]
MeasureKind: TypeAlias = Literal["rotation", "swing", "twist", "translation", "number"]
Axis: TypeAlias = Literal["x", "y", "z"]
Kernel: TypeAlias = Literal["gaussian", "exponential", "linear", "cubic", "quintic"]
Mode: TypeAlias = Literal["additive", "interpolative"]
Normalize: TypeAlias = Literal["none", "always", "above_one"]

AXES: Final[tuple[Axis, ...]] = ("x", "y", "z")
KERNELS: Final[tuple[Kernel, ...]] = (
    "gaussian",
    "exponential",
    "linear",
    "cubic",
    "quintic",
)
NORMALIZE_MODES: Final[tuple[Normalize, ...]] = ("none", "always", "above_one")
MATRIX_KINDS: Final[tuple[MeasureKind, ...]] = (
    "rotation",
    "swing",
    "twist",
    "translation",
)
AUTO_RADIUS_SCALE: Final[float] = 1.5
"""The automatic radius over the mean distance from each pose to its nearest one."""
NORMALIZE_EPSILON: Final[float] = 1e-12
QUATERNION_EPSILON: Final[float] = 1e-12
IDENTITY_QUATERNION: Final[FloatArray] = np.array([0.0, 0.0, 0.0, 1.0])
SAME_POSE_DISTANCE: Final[float] = 1e-9
"""Two poses closer than this, as a fraction of the radius, cannot be told apart."""


class SamePosesError(ValueError):
    """Two poses that the drivers cannot tell apart."""

    def __init__(self, first: int, second: int) -> None:
        """Names the two poses by index."""
        super().__init__(f"poses {first} and {second} have the same driver values")
        self.pair = (first, second)


@dataclass(frozen=True, slots=True, eq=False)
class TransformSamples:
    """Rotation and position of one matrix driver, one row per sample.

    Attributes:
        quaternions: (N, 4) rotations as x, y, z, w; the sign of each row is free.
        translations: (N, 3) positions.
    """

    quaternions: FloatArray
    translations: FloatArray


Samples: TypeAlias = TransformSamples | FloatArray
"""One driver at N samples: TransformSamples for a matrix, (N,) for a number."""


@dataclass(frozen=True, slots=True)
class Measure:
    """One way of comparing a driver with the poses.

    Attributes:
        kind: What is compared.
        port: The driver compared; matrix kinds and ``number`` cannot share one.
        axis: Local axis for ``swing`` and ``twist``.
        factor: Multiplies the distance, to mix units or give a driver more say.
    """

    kind: MeasureKind
    port: str = "driver"
    axis: Axis = "x"
    factor: float = 1.0

    @property
    def uses_matrix(self) -> bool:
        """Whether the driver is a matrix rather than a number."""
        return self.kind != "number"


@dataclass(frozen=True, slots=True, eq=False)
class Offsets:
    """Per pose and driven transform, the move from the transform's rest.

    Attributes:
        translations: (N, J, 3) translation of the move.
        quaternions: (N, J, 4) rotation of the move as x, y, z, w; any sign.
        scales: (N, J, 3) scale of the move.
    """

    translations: FloatArray
    quaternions: FloatArray
    scales: FloatArray


@dataclass(frozen=True, slots=True, eq=False)
class Spec:
    """Everything that defines one RBF.

    Attributes:
        measures: How the drivers are compared with the poses; at least one.
        poses: Per driver, its value at each pose.
        kernel: Falloff curve.
        radius: Falloff radius; None computes it from the poses.
        mode: ``additive`` uses the falloffs as weights; ``interpolative`` gives each
            pose exactly 1 at itself and 0 at the other poses.
        margin: Regularization of interpolative mode; 0 is exact at every pose.
        normalize: ``always`` divides the weights by their sum (unless the sum is
            about 0); ``above_one`` only when the sum exceeds 1.
        clamp_negative: Whether negative weights become 0.
        values: (N, M) value of each driven attribute at each pose; None for M = 0.
        rest_values: (M,) values far from every pose; None means zeros.
        offsets: Driven transforms; None for J = 0.
    """

    measures: tuple[Measure, ...]
    poses: dict[str, Samples]
    kernel: Kernel = "gaussian"
    radius: float | None = None
    mode: Mode = "interpolative"
    margin: float = 0.0
    normalize: Normalize = "none"
    clamp_negative: bool = False
    values: FloatArray | None = None
    rest_values: FloatArray | None = None
    offsets: Offsets | None = None

    @property
    def pose_count(self) -> int:
        """N, the number of poses."""
        first = next(iter(self.poses.values()))
        if isinstance(first, TransformSamples):
            return len(first.quaternions)
        return len(first)

    @property
    def value_count(self) -> int:
        """M, the number of driven values."""
        return 0 if self.values is None else int(self.values.shape[1])

    @property
    def transform_count(self) -> int:
        """J, the number of driven transforms."""
        return 0 if self.offsets is None else int(self.offsets.translations.shape[1])

    @property
    def ports(self) -> dict[str, bool]:
        """Drivers in order of first use, mapped to whether they are matrices."""
        ports: dict[str, bool] = {}
        for measure in self.measures:
            ports.setdefault(measure.port, measure.uses_matrix)
        return ports

    def rest(self) -> FloatArray:
        """(M,) rest values."""
        if self.rest_values is not None:
            return self.rest_values
        return np.zeros(self.value_count)

    def validate(self) -> None:
        """Raises when the RBF cannot be built.

        Raises:
            ValueError: When it cannot, with the reason.
        """
        if not self.measures:
            raise ValueError("at least one measure is needed")
        for port, is_matrix in self.ports.items():
            kinds = {m.uses_matrix for m in self.measures if m.port == port}
            if len(kinds) > 1:
                raise ValueError(f"driver {port!r} mixes matrix and number measures")
            samples = self.poses.get(port)
            if samples is None or isinstance(samples, TransformSamples) != is_matrix:
                raise ValueError(
                    f"poses of driver {port!r} are missing or of the wrong kind"
                )
        n = self.pose_count
        if n < 1 or (self.radius is None and n < 2):
            raise ValueError("the automatic radius needs at least two poses")
        if self.radius is not None and self.radius <= 0:
            raise ValueError("the radius must be positive")
        if self.values is not None and self.values.shape[0] != n:
            raise ValueError("the values need one row per pose")
        if self.rest_values is not None and self.rest_values.shape != (
            self.value_count,
        ):
            raise ValueError("the rest values need one entry per driven value")
        if self.offsets is not None and self.offsets.translations.shape[0] != n:
            raise ValueError("the driven transforms need one move per pose")


@dataclass(frozen=True, slots=True, eq=False)
class Solved:
    """What the setup computes once, when the poses or options change.

    Attributes:
        radius: Falloff radius in use.
        cardinal: (N, N) maps falloffs to weights: weights = falloffs @ cardinal.
    """

    radius: float
    cardinal: FloatArray


@dataclass(frozen=True, slots=True, eq=False)
class Result:
    """Outputs of the RBF for one state of its drivers.

    Attributes:
        weights: (N,) weight of each pose.
        values: (M,) driven values.
        matrices: (J, 4, 4) matrices for the driven transforms' offsetParentMatrix.
    """

    weights: FloatArray
    values: FloatArray
    matrices: FloatArray


# ---------------------------------------------------------------------------
# Distances
# ---------------------------------------------------------------------------


def axis_vector(axis: Axis) -> FloatArray:
    """Returns the unit vector of a local axis."""
    unit = np.zeros(3)
    unit[AXES.index(axis)] = 1.0
    return unit


def swing_directions(quaternions: FloatArray, axis: Axis) -> FloatArray:
    """Returns the (N, 3) direction the local *axis* points to after each rotation."""
    unit = axis_vector(axis)
    u, w = quaternions[:, :3], quaternions[:, 3:4]
    twice_cross = 2.0 * np.cross(u, unit)
    return unit + w * twice_cross + np.cross(u, twice_cross)


def twist_angles(quaternions: FloatArray, axis: Axis) -> FloatArray:
    """Returns the (N,) twist about the local *axis* of each rotation, in degrees."""
    along = quaternions[:, AXES.index(axis)]
    return 2.0 * np.degrees(np.arctan2(along, quaternions[:, 3]))


def _gaps(a: FloatArray, b: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Returns the norms of a - b and of a + b for every pair of unit vectors."""
    # Trap: the angle is 2 atan2 of these two norms; acos of the dot product loses
    # Trap: its precision near 0.
    minus = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2))
    plus = np.sqrt(((a[:, None, :] + b[None, :, :]) ** 2).sum(axis=2))
    return minus, plus


def measure_distances(measure: Measure, a: Samples, b: Samples) -> FloatArray:
    """Returns the (len(a), len(b)) distances from each sample of *a* to each of *b*.

    Raises:
        ValueError: When the samples do not match the measure.
    """
    if isinstance(a, TransformSamples) and isinstance(b, TransformSamples):
        if measure.kind == "rotation":
            minus, plus = _gaps(a.quaternions, b.quaternions)
            small, large = np.minimum(minus, plus), np.maximum(minus, plus)
            return 4.0 * np.degrees(np.arctan2(small, large))
        if measure.kind == "swing":
            minus, plus = _gaps(
                swing_directions(a.quaternions, measure.axis),
                swing_directions(b.quaternions, measure.axis),
            )
            return 2.0 * np.degrees(np.arctan2(minus, plus))
        if measure.kind == "twist":
            ta = twist_angles(a.quaternions, measure.axis)
            tb = twist_angles(b.quaternions, measure.axis)
            return np.abs(np.mod(ta[:, None] - tb[None, :] + 900.0, 360.0) - 180.0)
        if measure.kind == "translation":
            diff = a.translations[:, None, :] - b.translations[None, :, :]
            return np.sqrt((diff**2).sum(axis=2))
    if (
        isinstance(a, np.ndarray)
        and isinstance(b, np.ndarray)
        and measure.kind == "number"
    ):
        return np.abs(a[:, None] - b[None, :])
    raise ValueError(f"measure {measure.kind!r} does not match its samples")


def distances(
    spec: Spec, current: dict[str, Samples], poses: dict[str, Samples]
) -> FloatArray:
    """Returns the distance from each current sample to each pose, over all measures."""
    squared = sum(
        (m.factor * measure_distances(m, current[m.port], poses[m.port])) ** 2
        for m in spec.measures
    )
    return np.sqrt(np.asarray(squared, dtype=np.float64))


def falloff(kernel: Kernel, x: FloatArray) -> FloatArray:
    """Returns the falloff curve at *x*, the distance over the radius."""
    if kernel == "gaussian":
        return np.exp(-(x**2))
    if kernel == "exponential":
        return np.exp(-x)
    u = np.minimum(x, 1.0)
    if kernel == "linear":
        return 1.0 - u
    if kernel == "cubic":
        return (1.0 - u) ** 2 * (1.0 + 2.0 * u)
    return (1.0 - u) ** 3 * (1.0 + 3.0 * u + 6.0 * u**2)


def radius_of(spec: Spec, table: FloatArray) -> float:
    """Returns the radius set, or the automatic radius from the pose table.

    Raises:
        ValueError: When the drivers are the same at every pose.
    """
    if spec.radius is not None:
        return spec.radius
    nearest = np.sort(table, axis=1)[:, 1]
    radius = AUTO_RADIUS_SCALE * float(nearest.mean())
    if not radius > 0:
        raise ValueError(
            "the drivers are the same at every pose, so the poses cannot be told apart"
        )
    return radius


# ---------------------------------------------------------------------------
# Setup and evaluation
# ---------------------------------------------------------------------------


def setup(spec: Spec) -> Solved:
    """Solves the RBF for its poses.

    Raises:
        ValueError: When the spec is not valid.
        SamePosesError: When two poses share their driver values, without margin.
        numpy.linalg.LinAlgError: When the pose table has no solution otherwise.
    """
    spec.validate()
    table = distances(spec, spec.poses, spec.poses)
    radius = radius_of(spec, table)
    n = spec.pose_count
    if spec.mode == "additive":
        return Solved(radius, np.eye(n))
    a = falloff(spec.kernel, table / radius)
    if spec.margin > 0:
        cardinal = np.linalg.solve(a @ a + spec.margin**2 * np.eye(n), a)
        return Solved(radius, cardinal.astype(np.float64))
    apart = table + np.diag(np.full(n, np.inf))
    first, second = np.unravel_index(int(np.argmin(apart)), apart.shape)
    if apart[first, second] <= SAME_POSE_DISTANCE * radius:
        raise SamePosesError(int(min(first, second)), int(max(first, second)))
    return Solved(radius, np.linalg.solve(a, np.eye(n)).astype(np.float64))


def pose_weights(spec: Spec, solved: Solved, phi: FloatArray) -> FloatArray:
    """Returns the (N,) weights of the poses from their falloffs."""
    weights = phi @ solved.cardinal
    if spec.clamp_negative:
        weights = np.maximum(weights, 0.0)
    if spec.normalize != "none":
        total = float(weights.sum())
        if spec.normalize == "above_one":
            weights = weights / max(total, 1.0)
        elif abs(total) > NORMALIZE_EPSILON:
            weights = weights / total
    return weights


def aligned_quaternions(quaternions: FloatArray) -> FloatArray:
    """Returns the same rotations with w >= 0, on the identity's side."""
    signs = np.where(quaternions[..., 3:4] < 0.0, -1.0, 1.0)
    return quaternions * signs


def quaternion_matrix(quaternions: FloatArray) -> FloatArray:
    """Returns the (..., 3, 3) rotation matrices of unit quaternions, Maya's rows."""
    x, y, z, w = (quaternions[..., k] for k in range(4))
    rows = [
        [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
        [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
        [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)],
    ]
    return np.stack([np.stack(row, axis=-1) for row in rows], axis=-2)


def compose(
    translations: FloatArray, quaternions: FloatArray, scales: FloatArray
) -> FloatArray:
    """Returns the (..., 4, 4) matrices that scale, rotate, then translate."""
    shape = translations.shape[:-1]
    matrices = np.zeros((*shape, 4, 4))
    matrices[..., :3, :3] = scales[..., :, None] * quaternion_matrix(quaternions)
    matrices[..., 3, :3] = translations
    matrices[..., 3, 3] = 1.0
    return matrices


def blend_transforms(weights: FloatArray, offsets: Offsets) -> FloatArray:
    """Returns the (J, 4, 4) offset matrices, each blended from the identity."""
    translations = np.einsum("i,ijk->jk", weights, offsets.translations)
    scales = 1.0 + np.einsum("i,ijk->jk", weights, offsets.scales - 1.0)
    quaternions = aligned_quaternions(offsets.quaternions) - IDENTITY_QUATERNION
    blended = IDENTITY_QUATERNION + np.einsum("i,ijk->jk", weights, quaternions)
    length = np.linalg.norm(blended, axis=1, keepdims=True)
    blended = np.where(
        length > QUATERNION_EPSILON,
        blended / np.maximum(length, QUATERNION_EPSILON),
        IDENTITY_QUATERNION,
    )
    return compose(translations, blended, scales)


def evaluate(spec: Spec, solved: Solved, current: dict[str, Samples]) -> Result:
    """Returns the outputs of the RBF for one state of its drivers."""
    phi = falloff(spec.kernel, distances(spec, current, spec.poses)[0] / solved.radius)
    weights = pose_weights(spec, solved, phi)
    values = np.zeros(0)
    if spec.values is not None:
        rest = spec.rest()
        values = rest + weights @ (spec.values - rest)
    matrices = np.zeros((0, 4, 4))
    if spec.offsets is not None:
        matrices = blend_transforms(weights, spec.offsets)
    return Result(weights, values, matrices)
