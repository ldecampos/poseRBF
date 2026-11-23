"""One pose RBF as data: drivers, poses, driven attributes and options.

The definition is what the scene stores, as JSON, and what every edit changes; the
board's constants are derived from it. Nothing here needs Maya.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import Final

import numpy as np

from . import reference as ref

FORMAT: Final[int] = 1
SINGLE_POSE_RADIUS: Final[float] = 1.0
"""Radius used while there is a single pose, when the radius is automatic.

The automatic radius needs a nearest pose; with one pose any radius gives the same
outputs at that pose.
"""


@dataclass(frozen=True, slots=True)
class Driver:
    """One input of the RBF.

    Attributes:
        name: Name of the board port.
        plug: The transform (a node) or the number (``node.attribute``) it reads.
        is_matrix: Whether it is a transform, read through its ``.matrix``.
        rotation: Factor of the rotation distance (transforms; 0 turns it off).
        swing: Factor of the swing distance.
        twist: Factor of the twist distance.
        translation: Factor of the translation distance.
        axis: Local axis of swing and twist.
        number: Factor of the number distance (numbers).
    """

    name: str
    plug: str
    is_matrix: bool = True
    rotation: float = 1.0
    swing: float = 0.0
    twist: float = 0.0
    translation: float = 0.0
    axis: ref.Axis = "x"
    number: float = 1.0

    def measures(self) -> tuple[ref.Measure, ...]:
        """Returns the measures this driver contributes: those with a factor."""
        if not self.is_matrix:
            return (ref.Measure("number", self.name, factor=self.number),)
        factors: tuple[tuple[ref.MeasureKind, float], ...] = (
            ("rotation", self.rotation),
            ("swing", self.swing),
            ("twist", self.twist),
            ("translation", self.translation),
        )
        return tuple(
            ref.Measure(kind, self.name, self.axis, factor)
            for kind, factor in factors
            if factor > 0
        )


@dataclass(frozen=True, slots=True)
class DrivenValue:
    """A number the RBF drives.

    Attributes:
        plug: ``node.attribute`` it drives.
        rest: Its value far from every pose.
    """

    plug: str
    rest: float = 0.0


IDENTITY_MATRIX: Final[tuple[float, ...]] = tuple(float(v) for v in np.eye(4).ravel())


@dataclass(frozen=True, slots=True)
class DrivenTransform:
    """A transform the RBF drives through its ``offsetParentMatrix``.

    Attributes:
        node: The transform.
        rest: Its local ``.matrix`` at rest (16 numbers, row by row).
        rest_channels: Its translate, rotate and scale at rest (9 numbers), restored
            after each edit of a pose.
        parent_offset: Its ``offsetParentMatrix`` before the RBF; the RBF's matrix is
            multiplied by it.
    """

    node: str
    rest: tuple[float, ...] = IDENTITY_MATRIX
    rest_channels: tuple[float, ...] = (0, 0, 0, 0, 0, 0, 1, 1, 1)
    parent_offset: tuple[float, ...] = IDENTITY_MATRIX


IDENTITY_MOVE: Final[tuple[float, ...]] = (0, 0, 0, 0, 0, 0, 1, 1, 1, 1)
"""A move that changes nothing: translation, quaternion (x, y, z, w), scale."""


def _no_channels() -> dict[str, tuple[float, ...]]:
    """Returns an empty channel table."""
    return {}


@dataclass(frozen=True, slots=True)
class Pose:
    """One example the RBF interpolates.

    Attributes:
        name: Shown in the tool.
        drivers: Per driver name, its state: a transform as quaternion (x, y, z, w) and
            translation (7 numbers), a number as one.
        values: One per driven value.
        moves: One per driven transform: translation, quaternion (x, y, z, w) and scale
            of its move from rest (10 numbers).
        channels: Per transform driver, its translate and rotate when the pose was
            taken (6 numbers), to put it back in the pose.
    """

    name: str
    drivers: dict[str, tuple[float, ...]]
    values: tuple[float, ...] = ()
    moves: tuple[tuple[float, ...], ...] = ()
    channels: dict[str, tuple[float, ...]] = dataclasses.field(
        default_factory=_no_channels
    )


@dataclass(frozen=True, slots=True)
class Options:
    """The options that set how an RBF interpolates.

    Attributes:
        kernel: Falloff curve.
        radius: Falloff radius; None computes it from the poses.
        mode: ``interpolative`` or ``additive``.
        margin: Regularization; 0 is exact at every pose.
        normalize: ``none``, ``always`` or ``above_one``.
        clamp_negative: Whether negative weights become 0.
    """

    kernel: ref.Kernel = "gaussian"
    radius: float | None = None
    mode: ref.Mode = "interpolative"
    margin: float = 0.0
    normalize: ref.Normalize = "above_one"
    clamp_negative: bool = False


@dataclass(frozen=True, slots=True)
class Definition:
    """Everything the tool knows about one RBF.

    Attributes:
        drivers: Inputs, in port order.
        poses: Examples, in order.
        values: Driven numbers.
        transforms: Driven transforms.
        options: How it interpolates.
    """

    drivers: tuple[Driver, ...]
    poses: tuple[Pose, ...]
    values: tuple[DrivenValue, ...] = ()
    transforms: tuple[DrivenTransform, ...] = ()
    options: Options = Options()

    def replace(self, **changes: object) -> Definition:
        """Returns a copy with some fields changed."""
        return dataclasses.replace(self, **changes)

    def pose_index(self, name: str) -> int:
        """Returns the index of the pose *name*.

        Raises:
            KeyError: When there is no such pose.
        """
        for index, pose in enumerate(self.poses):
            if pose.name == name:
                return index
        raise KeyError(f"no pose named {name!r}")

    def unique_pose_name(self, base: str = "pose") -> str:
        """Returns a pose name not in use: *base* followed by a number."""
        used = {pose.name for pose in self.poses}
        number = len(self.poses)
        while f"{base}{number}" in used:
            number += 1
        return f"{base}{number}"

    def to_spec(self) -> ref.Spec:
        """Returns the RBF as the reference and the board read it.

        Raises:
            ValueError: When there is no pose or no driver with a measure.
        """
        if not self.poses:
            raise ValueError("the RBF needs at least one pose")
        measures = tuple(m for driver in self.drivers for m in driver.measures())
        if not measures:
            raise ValueError("the RBF needs a driver with a measure")
        used = {m.port for m in measures}
        samples: dict[str, ref.Samples] = {}
        for driver in self.drivers:
            if driver.name not in used:
                continue
            rows = np.array([pose.drivers[driver.name] for pose in self.poses], float)
            if driver.is_matrix:
                samples[driver.name] = ref.TransformSamples(rows[:, :4], rows[:, 4:7])
            else:
                samples[driver.name] = rows[:, 0]
        options = self.options
        radius = options.radius
        if radius is None and len(self.poses) < 2:
            radius = SINGLE_POSE_RADIUS
        values = rest = None
        if self.values:
            values = np.array([pose.values for pose in self.poses], float)
            rest = np.array([value.rest for value in self.values], float)
        offsets = None
        if self.transforms:
            moves = np.array([pose.moves for pose in self.poses], float)
            offsets = ref.Offsets(moves[:, :, 0:3], moves[:, :, 3:7], moves[:, :, 7:10])
        return ref.Spec(
            measures,
            samples,
            kernel=options.kernel,
            radius=radius,
            mode=options.mode,
            margin=options.margin,
            normalize=options.normalize,
            clamp_negative=options.clamp_negative,
            values=values,
            rest_values=rest,
            offsets=offsets,
        )

    def to_json(self) -> str:
        """Returns the definition as JSON text."""
        data = dataclasses.asdict(self)
        data["format"] = FORMAT
        return json.dumps(data, separators=(",", ":"))

    @staticmethod
    def from_json(text: str) -> Definition:
        """Reads a definition written by :meth:`to_json`.

        Raises:
            ValueError: When the text is not a definition of a known format.
        """
        data = json.loads(text)
        if data.get("format") != FORMAT:
            raise ValueError(f"unknown definition format {data.get('format')!r}")
        return Definition(
            drivers=tuple(Driver(**d) for d in data["drivers"]),
            poses=tuple(
                Pose(
                    name=p["name"],
                    drivers={k: tuple(v) for k, v in p["drivers"].items()},
                    values=tuple(p["values"]),
                    moves=tuple(tuple(m) for m in p["moves"]),
                    channels={k: tuple(v) for k, v in p["channels"].items()},
                )
                for p in data["poses"]
            ),
            values=tuple(DrivenValue(**v) for v in data["values"]),
            transforms=tuple(
                DrivenTransform(
                    t["node"],
                    tuple(t["rest"]),
                    tuple(t["rest_channels"]),
                    tuple(t["parent_offset"]),
                )
                for t in data["transforms"]
            ),
            options=Options(**data["options"]),
        )
