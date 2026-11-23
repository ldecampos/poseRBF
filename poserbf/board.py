"""The Bifrost board of one pose RBF: one fixed graph, loaded from text, and its data.

Every RBF loads the same graph and differs only in the constants written into it and
in what is connected to its array ports. Both are ordinary Maya edits, which Maya's
own undo takes back. Maya restores a constant from its text, so every number is
written with the digits undo keeps, and no constant is nested. Pose data are laid
out flat, one element per pose and driver, with one constant per vector component.

Board ports, as attributes of the Maya node:
    drivers   array<Math::double4x4>  the transform drivers' ``.matrix``, in order
    numbers   array<double>           the number drivers, in order
    weights   array<double>           the weight of each pose
    values    array<double>           the driven values
    matrices  array<Math::double4x4>  one ``offsetParentMatrix`` per driven transform
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Final

import numpy as np
from maya import cmds

from . import reference as ref
from .definition import Definition

TEMPLATE: Final[Path] = Path(__file__).with_name("board.json")
GRAPH_ATTRIBUTE: Final[str] = "saveContainerToJSON"
PLUGINS: Final[tuple[str, ...]] = ("bifrostGraph", "mayaVnnPlugin")

DRIVERS: Final[str] = "drivers"
NUMBERS: Final[str] = "numbers"
WEIGHTS: Final[str] = "weights"
VALUES: Final[str] = "values"
MATRICES: Final[str] = "matrices"

MATRIX: Final[str] = "/matrix_distances"
NUMBER: Final[str] = "/number_distances"
FALLOFF: Final[str] = "/pose_falloff"
POSE_WEIGHTS: Final[str] = "/pose_weights"
DRIVEN_VALUES: Final[str] = "/driven_values"
DRIVEN_TRANSFORMS: Final[str] = "/driven_transforms"

AL: Final[str] = "array<long>"
AD: Final[str] = "array<double>"
SIGNIFICANT_DIGITS: Final[int] = 12
"""Digits Maya's undo keeps of a constant; more would not come back exactly."""

ROTATION: Final[str] = f"{MATRIX}/rotation_distance"
SWING: Final[str] = f"{MATRIX}/swing_distance"
TWIST: Final[str] = f"{MATRIX}/twist_distance"
TRANSLATION: Final[str] = f"{MATRIX}/translation_distance"

CONSTANTS: Final[dict[str, str]] = {
    f"{MATRIX}/driver_index": AL,
    f"{MATRIX}/axis_x": AD,
    f"{MATRIX}/axis_y": AD,
    f"{MATRIX}/axis_z": AD,
    f"{MATRIX}/starts": AL,
    f"{MATRIX}/ends": AL,
    f"{ROTATION}/pose_qx": AD,
    f"{ROTATION}/pose_qy": AD,
    f"{ROTATION}/pose_qz": AD,
    f"{ROTATION}/pose_qw": AD,
    f"{ROTATION}/factors": AD,
    f"{SWING}/pose_dx": AD,
    f"{SWING}/pose_dy": AD,
    f"{SWING}/pose_dz": AD,
    f"{SWING}/factors": AD,
    f"{TWIST}/pose_twists": AD,
    f"{TWIST}/factors": AD,
    f"{TRANSLATION}/pose_tx": AD,
    f"{TRANSLATION}/pose_ty": AD,
    f"{TRANSLATION}/pose_tz": AD,
    f"{TRANSLATION}/factors": AD,
    f"{NUMBER}/number_index": AL,
    f"{NUMBER}/pose_numbers": AD,
    f"{NUMBER}/factors": AD,
    f"{NUMBER}/starts": AL,
    f"{NUMBER}/ends": AL,
    f"{FALLOFF}/radius": "double",
    f"{FALLOFF}/curve": "long",
    f"{POSE_WEIGHTS}/table_rows": AD,
    f"{POSE_WEIGHTS}/table_tile": AL,
    f"{POSE_WEIGHTS}/table_starts": AL,
    f"{POSE_WEIGHTS}/table_ends": AL,
    f"{POSE_WEIGHTS}/additive": "bool",
    f"{POSE_WEIGHTS}/clamp_negative": "bool",
    f"{POSE_WEIGHTS}/normalize": "long",
    f"{DRIVEN_VALUES}/rest": AD,
    f"{DRIVEN_VALUES}/rows": AD,
    f"{DRIVEN_VALUES}/tile": AL,
    f"{DRIVEN_VALUES}/starts": AL,
    f"{DRIVEN_VALUES}/ends": AL,
    f"{DRIVEN_TRANSFORMS}/rows": AD,
    f"{DRIVEN_TRANSFORMS}/tile": AL,
    f"{DRIVEN_TRANSFORMS}/starts": AL,
    f"{DRIVEN_TRANSFORMS}/ends": AL,
}
"""Every constant node the tool writes, by path in the graph, with its type."""

TRANSFORM_COMPONENTS: Final[tuple[str, ...]] = (
    "tx", "ty", "tz", "sx", "sy", "sz", "qx", "qy", "qz", "qw",
)  # fmt: skip
"""The ten blended numbers per driven transform, in order."""


# ---------------------------------------------------------------------------
# Text of constants
# ---------------------------------------------------------------------------


def number_text(value: float) -> str:
    """Returns a number with the digits undo keeps, ``SIGNIFICANT_DIGITS``."""
    return format(float(value), f".{SIGNIFICANT_DIGITS}g")


def array_text(values: Iterable[float]) -> str:
    """Returns an ``array<double>`` constant, each number as :func:`number_text`."""
    return "{" + ", ".join(number_text(v) for v in values) + "}"


def component_texts(prefix: str, names: str, vectors: ref.FloatArray) -> dict[str, str]:
    """Returns one ``array<double>`` per component of the (K, len(names)) *vectors*."""
    return {
        f"{prefix}{name}": array_text(vectors[:, k]) for k, name in enumerate(names)
    }


def long_text(values: Iterable[int]) -> str:
    """Returns an ``array<long>`` constant."""
    return "{" + ", ".join(str(int(v)) for v in values) + "}"


def group_texts(prefix: str, groups: int, width: int) -> dict[str, str]:
    """Returns the bounds of *groups* runs of *width* elements in a running sum.

    The sum of run ``g`` is ``running[ends[g]] - running[starts[g]]``; index -1 reads
    0, and with *width* 0 every run sums to 0.
    """
    return {
        f"{prefix}starts": long_text(g * width - 1 for g in range(groups)),
        f"{prefix}ends": long_text((g + 1) * width - 1 for g in range(groups)),
    }


def weighted_sum_texts(prefix: str, rows: ref.FloatArray) -> dict[str, str]:
    """Returns the constants of a flat weighted sum of the (R, N) *rows*.

    The sum of row r is ``rows[r] · v``; the rows go flat, and ``tile[k] = k mod N``
    spreads the vector over them.
    """
    count, width = rows.shape
    return {
        f"{prefix}rows": array_text(rows.ravel()),
        f"{prefix}tile": long_text(k % width for k in range(count * width)),
        **group_texts(prefix, count, width),
    }


def _rotate(quaternions: ref.FloatArray, vectors: ref.FloatArray) -> ref.FloatArray:
    """Returns each vector rotated by the quaternion of the same row."""
    u, w = quaternions[:, :3], quaternions[:, 3:4]
    twice_cross = 2.0 * np.cross(u, vectors)
    return vectors + w * twice_cross + np.cross(u, twice_cross)


def matrix_texts(definition: Definition) -> dict[str, str]:
    """Returns the constants of the transform drivers, every pose by every driver.

    A factor of 0 (or below) leaves that measure out, as in the reference.
    """
    drivers = [d for d in definition.drivers if d.is_matrix]
    n, d = len(definition.poses), len(drivers)
    states = np.array(
        [[pose.drivers[x.name] for x in drivers] for pose in definition.poses], float
    ).reshape(n * d, 7)
    q, t = states[:, :4], states[:, 4:7]
    axes = np.tile(
        np.array([ref.axis_vector(x.axis) for x in drivers]).reshape(d, 3), (n, 1)
    )
    directions = _rotate(q, axes)
    twists = 2.0 * np.degrees(np.arctan2((q[:, :3] * axes).sum(axis=1), q[:, 3]))

    def factors(kind: str) -> str:
        """Returns the factors of one measure, every pose by every driver."""
        per_driver = [max(float(getattr(x, kind)), 0.0) for x in drivers]
        return array_text(np.tile(per_driver, n))

    return {
        f"{MATRIX}/driver_index": long_text(k % d for k in range(n * d)),
        **component_texts(f"{MATRIX}/axis_", "xyz", axes),
        **group_texts(f"{MATRIX}/", n, d),
        **component_texts(f"{ROTATION}/pose_q", "xyzw", q),
        f"{ROTATION}/factors": factors("rotation"),
        **component_texts(f"{SWING}/pose_d", "xyz", directions),
        f"{SWING}/factors": factors("swing"),
        f"{TWIST}/pose_twists": array_text(twists),
        f"{TWIST}/factors": factors("twist"),
        **component_texts(f"{TRANSLATION}/pose_t", "xyz", t),
        f"{TRANSLATION}/factors": factors("translation"),
    }


def number_texts(definition: Definition) -> dict[str, str]:
    """Returns the constants of the number drivers, every pose by every driver."""
    drivers = [d for d in definition.drivers if not d.is_matrix]
    n, m = len(definition.poses), len(drivers)
    values = [pose.drivers[x.name][0] for pose in definition.poses for x in drivers]
    factors = [max(float(x.number), 0.0) for x in drivers]
    return {
        f"{NUMBER}/number_index": long_text(k % m for k in range(n * m)),
        f"{NUMBER}/pose_numbers": array_text(values),
        f"{NUMBER}/factors": array_text(np.tile(factors, n)),
        **group_texts(f"{NUMBER}/", n, m),
    }


def transform_rows(spec: ref.Spec) -> ref.FloatArray:
    """Returns the (10·J, N) moves, per component and transform, one column per pose.

    The components are translation, scale - 1 and quaternion - identity, with each
    quaternion on the identity's side.
    """
    if spec.offsets is None:
        return np.zeros((0, spec.pose_count))
    offsets = spec.offsets
    moves = np.concatenate(
        [
            offsets.translations,
            offsets.scales - 1.0,
            ref.aligned_quaternions(offsets.quaternions) - ref.IDENTITY_QUATERNION,
        ],
        axis=2,
    )  # Format: (N, J, 10), in the order of TRANSFORM_COMPONENTS
    return moves.transpose(2, 1, 0).reshape(
        len(TRANSFORM_COMPONENTS) * moves.shape[1], -1
    )


def constants(definition: Definition) -> dict[str, str]:
    """Returns the text of every constant of the board for *definition*, by path.

    Raises:
        ValueError: When the definition has no pose or no measure.
        SamePosesError: When two poses have the same driver values.
        LinAlgError: When the pose table has no solution otherwise.
    """
    spec = definition.to_spec()
    solved = ref.setup(spec)
    value_rows = np.zeros((0, spec.pose_count))
    if spec.values is not None:
        value_rows = (spec.values - spec.rest()).T
    texts = {
        **matrix_texts(definition),
        **number_texts(definition),
        f"{FALLOFF}/radius": number_text(solved.radius),
        f"{FALLOFF}/curve": str(ref.KERNELS.index(spec.kernel)),
        **weighted_sum_texts(f"{POSE_WEIGHTS}/table_", solved.cardinal.T),
        # Bifrost: a bool constant ignores "true" and "false"; it reads 1 and 0.
        f"{POSE_WEIGHTS}/additive": "1" if spec.mode == "additive" else "0",
        f"{POSE_WEIGHTS}/clamp_negative": "1" if spec.clamp_negative else "0",
        f"{POSE_WEIGHTS}/normalize": str(ref.NORMALIZE_MODES.index(spec.normalize)),
        f"{DRIVEN_VALUES}/rest": array_text(spec.rest()),
        **weighted_sum_texts(f"{DRIVEN_VALUES}/", value_rows),
        **weighted_sum_texts(f"{DRIVEN_TRANSFORMS}/", transform_rows(spec)),
    }
    assert texts.keys() == CONSTANTS.keys()
    return texts


# ---------------------------------------------------------------------------
# The Maya node
# ---------------------------------------------------------------------------


def plugin_command(name: str) -> Callable[..., object]:
    """Returns a command a plug-in, Bifrost among them, adds to ``maya.cmds``."""
    # Maya: a plug-in's commands join maya.cmds at load time; its stubs lack them.
    return getattr(cmds, name)


def load_plugins() -> None:
    """Loads Bifrost and its scripting commands, if they are not loaded."""
    for plugin in PLUGINS:
        if not cmds.pluginInfo(plugin, query=True, loaded=True):
            cmds.loadPlugin(plugin, quiet=True)


def load(name: str, like: str | None = None) -> str:
    """Creates a board named *name*, or the name Maya makes unique, with the graph.

    Args:
        name: Name for the new board.
        like: An RBF board in the scene, duplicated to make the new one.

    Returns:
        The board's name.
    """
    load_plugins()
    # Bifrost: 2.14 crashes when a second board takes the same graph from text.
    if like is not None:
        return str(cmds.duplicate(like, name=name)[0])
    # Maya: importing the graph from a file would empty the undo queue.
    node = str(cmds.createNode("bifrostBoard", name=name))
    text = TEMPLATE.read_text(encoding="utf-8")
    cmds.setAttr(f"{node}.{GRAPH_ATTRIBUTE}", text, type="string")
    return node


def write(node: str, texts: dict[str, str]) -> None:
    """Writes constants (from :func:`constants`) into the board *node*.

    Each changed constant recompiles the graph; the change bracket compiles it once at
    the end. The bracket is recorded with the writes, so undo compiles once too.
    """
    bracket = plugin_command("vnnChangeBracket")
    set_value = plugin_command("vnnNode")
    bracket(node, open=True)
    try:
        for path, text in texts.items():
            set_value(node, path, setPortDefaultValues=("value", text))
    finally:
        bracket(node, close=True)
