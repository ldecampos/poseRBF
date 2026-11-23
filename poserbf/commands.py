"""Pose RBFs in the Maya scene: create, edit and delete them.

An RBF is a ``bifrostBoard`` named as the RBF and a ``network`` node, ``<name>_setup``,
that holds its definition as JSON. The drivers connect in order to the board's inputs;
its outputs drive the values and the transforms' ``offsetParentMatrix``, and every
pose weight reaches the network node. Creating an RBF stays out of the undo queue.
Every later edit is one step of Maya's own undo: it stores the new definition,
rewrites the board's constants and makes the connections match. An edit raises
``ValueError`` and changes nothing when its result cannot be built or would close a
cycle. A pose is edited with the RBF connected, the driven moved by their channels.
"""

from __future__ import annotations

import contextlib
import dataclasses
import math
import re
from collections.abc import Generator, Iterable, Sequence
from typing import Final

import maya.api.OpenMaya as om
import numpy as np
from maya import cmds

from . import board
from . import reference as ref
from .definition import (
    IDENTITY_MATRIX,
    IDENTITY_MOVE,
    Definition,
    DrivenTransform,
    DrivenValue,
    Driver,
    Options,
    Pose,
)

NETWORK_SUFFIX: Final[str] = "_setup"
DEFINITION_ATTR: Final[str] = "poseRBFDefinition"
BOARD_LINK: Final[str] = "poseRBFBoard"
OFFSET_SUFFIX: Final[str] = "_poseRBFOffset"
WEIGHTS_ATTR: Final[str] = "poseRBFWeights"
"""The network node's multi that reads every weight of the board."""


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def undo_step(name: str) -> Generator[None, None, None]:
    """Groups the commands run inside into one undo step called *name*."""
    cmds.undoInfo(openChunk=True, chunkName=name)
    try:
        yield
    finally:
        cmds.undoInfo(closeChunk=True)


@contextlib.contextmanager
def unrecorded() -> Generator[None, None, None]:
    """Keeps the commands run inside out of the undo queue, without emptying it."""
    recording = cmds.undoInfo(query=True, state=True)
    if recording:
        cmds.undoInfo(stateWithoutFlush=False)
    try:
        yield
    finally:
        if recording:
            cmds.undoInfo(stateWithoutFlush=True)


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


def all_rbfs() -> list[str]:
    """Returns the names of the pose RBFs in the scene."""
    found: list[str] = []
    for network in cmds.ls(type="network") or []:
        if not cmds.attributeQuery(DEFINITION_ATTR, node=network, exists=True):
            continue
        boards = cmds.listConnections(f"{network}.{BOARD_LINK}", source=True) or []
        found.extend(str(b) for b in boards)
    return sorted(found)


def network_of(rbf: str) -> str | None:
    """Returns the network node that holds the definition of *rbf*, or None."""
    if not cmds.objExists(rbf):
        return None
    for plug in (
        cmds.listConnections(f"{rbf}.message", destination=True, plugs=True) or []
    ):
        node, _, attribute = plug.partition(".")
        if attribute == BOARD_LINK:
            return node
    return None


def definition_of(rbf: str) -> Definition:
    """Returns the definition stored for *rbf*.

    Raises:
        ValueError: When *rbf* is not a pose RBF.
    """
    network = network_of(rbf)
    if network is None:
        raise ValueError(f"{rbf!r} is not a pose RBF")
    return Definition.from_json(str(cmds.getAttr(f"{network}.{DEFINITION_ATTR}")))


# ---------------------------------------------------------------------------
# Reading the scene
# ---------------------------------------------------------------------------


def _matrix(values: Sequence[float]) -> om.MMatrix:
    """Returns the matrix of 16 *values*."""
    return om.MMatrix(list(values))


def _local(node: str) -> om.MMatrix:
    """Returns the local matrix of *node*."""
    return om.MMatrix(cmds.getAttr(f"{node}.matrix"))


def _flat(matrix: om.MMatrix) -> tuple[float, ...]:
    """Returns the 16 numbers of *matrix*."""
    return tuple(float(v) for v in matrix)


def _move(matrix: om.MMatrix) -> tuple[float, ...]:
    """Returns the translation, quaternion (x, y, z, w) and scale of *matrix*."""
    tm = om.MTransformationMatrix(matrix)
    t = tm.translation(om.MSpace.kTransform)
    q = tm.rotation(asQuaternion=True)
    s = tm.scale(om.MSpace.kTransform)
    return (t.x, t.y, t.z, q.x, q.y, q.z, q.w, s[0], s[1], s[2])


def driver_state(driver: Driver) -> tuple[float, ...]:
    """Returns the driver now: quaternion and translation, or the number."""
    if not driver.is_matrix:
        return (float(cmds.getAttr(driver.plug)),)
    move = _move(_local(driver.plug))
    return move[3:7] + move[0:3]


def driver_channels(driver: Driver) -> tuple[float, ...]:
    """Returns the translate and rotate of a transform driver now."""
    return tuple(cmds.getAttr(f"{driver.plug}.translate")[0]) + tuple(
        cmds.getAttr(f"{driver.plug}.rotate")[0]
    )


def _indices(multi: str) -> list[int]:
    """Returns the indices of the elements of the plug *multi*."""
    found: list[int] = cmds.getAttr(multi, multiIndices=True) or []
    return found


def _output(rbf: str, port: str, index: int) -> str | None:
    """Returns the plug of element *index* of the output *port*, or None without it."""
    if not cmds.objExists(rbf) or index not in _indices(f"{rbf}.{port}"):
        return None
    return f"{rbf}.{port}[{index}]"


def current_move(rbf: str, transform: DrivenTransform, index: int) -> tuple[float, ...]:
    """Returns the move from rest that puts *transform* where it shows now.

    What shows is its channels' matrix times the RBF's output: rest⁻¹ · that.
    """
    output = _output(rbf, board.MATRICES, index)
    shown = _local(transform.node)
    if output is not None:
        shown = shown * om.MMatrix(cmds.getAttr(output))
    return _move(_matrix(transform.rest).inverse() * shown)


def current_values(rbf: str, definition: Definition) -> tuple[float, ...]:
    """Returns the driven values the RBF outputs now, their rest before it outputs."""
    values: list[float] = []
    for index, value in enumerate(definition.values):
        output = _output(rbf, board.VALUES, index)
        values.append(value.rest if output is None else float(cmds.getAttr(output)))
    return tuple(values)


def weights(rbf: str) -> tuple[float, ...]:
    """Returns the weight of each pose now; empty when the board cannot be read."""
    try:
        raw = cmds.getAttr(f"{rbf}.{board.WEIGHTS}")
    except (RuntimeError, ValueError):
        return ()
    # Format: Maya returns the numbers bare, or inside one tuple in a list.
    numbers = raw[0] if raw and isinstance(raw[0], tuple) else raw or ()
    return tuple(float(number) for number in numbers)


def capture_pose(rbf: str, definition: Definition, name: str) -> Pose:
    """Returns a pose at the drivers' current state, with what the driven show now."""
    matrices = [d for d in definition.drivers if d.is_matrix]
    return Pose(
        name=name,
        drivers={d.name: driver_state(d) for d in definition.drivers},
        values=current_values(rbf, definition),
        moves=tuple(
            current_move(rbf, t, j) for j, t in enumerate(definition.transforms)
        ),
        channels={d.name: driver_channels(d) for d in matrices},
    )


def _rest_channels(node: str) -> tuple[float, ...]:
    """Returns the translate, rotate and scale of *node*, nine numbers."""
    return tuple(
        float(v)
        for attribute in ("translate", "rotate", "scale")
        for v in cmds.getAttr(f"{node}.{attribute}")[0]
    )


def _restore_channels(transform: DrivenTransform) -> None:
    """Puts the settable channels of *transform* back at rest."""
    values = transform.rest_channels
    for k, attribute in enumerate(("translate", "rotate", "scale")):
        plug = f"{transform.node}.{attribute}"
        if cmds.getAttr(plug, settable=True):
            cmds.setAttr(plug, *values[3 * k : 3 * k + 3])


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


def _offset_node(transform: DrivenTransform) -> str:
    """Returns the multMatrix that keeps the former offset of *transform*."""
    return f"{transform.node.split('|')[-1]}{OFFSET_SUFFIX}"


def _source(destination: str) -> str | None:
    """Returns the plug connected into *destination*, or None."""
    sources = cmds.listConnections(
        destination, source=True, destination=False, plugs=True
    )
    return str(sources[0]) if sources else None


def _connect_once(source: str, destination: str) -> None:
    """Connects *source* into *destination* unless it is connected already."""
    if _source(destination) != source:
        cmds.connectAttr(source, destination, force=True)


def _disconnect(destination: str) -> None:
    """Disconnects whatever is connected into *destination*."""
    source = _source(destination)
    if source is not None:
        cmds.disconnectAttr(source, destination)


def _fill_inputs(rbf: str, port: str, sources: list[str]) -> None:
    """Connects *sources* to ``rbf.port[0..]`` in order; removes the elements past."""
    for index, source in enumerate(sources):
        _connect_once(source, f"{rbf}.{port}[{index}]")
    for index in _indices(f"{rbf}.{port}"):
        if index >= len(sources):
            cmds.removeMultiInstance(f"{rbf}.{port}[{index}]", b=True)


def _connect(rbf: str, definition: Definition) -> None:
    """Makes the board's connections match *definition*."""
    _fill_inputs(
        rbf,
        board.DRIVERS,
        [f"{d.plug}.matrix" for d in definition.drivers if d.is_matrix],
    )
    _fill_inputs(
        rbf, board.NUMBERS, [d.plug for d in definition.drivers if not d.is_matrix]
    )
    for index, value in enumerate(definition.values):
        _connect_once(f"{rbf}.{board.VALUES}[{index}]", value.plug)
    for index, transform in enumerate(definition.transforms):
        output = f"{rbf}.{board.MATRICES}[{index}]"
        target = f"{transform.node}.offsetParentMatrix"
        if transform.parent_offset == IDENTITY_MATRIX:
            _connect_once(output, target)
            continue
        offset = _offset_node(transform)
        if not cmds.objExists(offset):
            cmds.createNode("multMatrix", name=offset)
            cmds.setAttr(
                f"{offset}.matrixIn[1]", list(transform.parent_offset), type="matrix"
            )
        _connect_once(output, f"{offset}.matrixIn[0]")
        _connect_once(f"{offset}.matrixSum", target)
    _connect_weights(rbf, len(definition.poses))


def _connect_weights(rbf: str, poses: int) -> None:
    """Connects ``rbf.weights[0..poses)`` to the network node; removes those past."""
    # Bifrost: in parallel, a sparse array output updates only its first indices.
    network = network_of(rbf)
    if network is None:
        return
    if not cmds.attributeQuery(WEIGHTS_ATTR, node=network, exists=True):
        cmds.addAttr(network, longName=WEIGHTS_ATTR, attributeType="double", multi=True)
    for index in range(poses):
        _connect_once(
            f"{rbf}.{board.WEIGHTS}[{index}]", f"{network}.{WEIGHTS_ATTR}[{index}]"
        )
    for index in _indices(f"{network}.{WEIGHTS_ATTR}"):
        if index >= poses:
            cmds.removeMultiInstance(f"{network}.{WEIGHTS_ATTR}[{index}]", b=True)


def _release(old: Definition, new: Definition | None) -> None:
    """Gives back what *old* drove and *new* does not: rest values and offsets."""
    plugs: set[str] = {v.plug for v in new.values} if new else set()
    nodes: set[str] = {t.node for t in new.transforms} if new else set()
    for value in old.values:
        if value.plug in plugs or not cmds.objExists(value.plug):
            continue
        _disconnect(value.plug)
        if cmds.getAttr(value.plug, settable=True):
            cmds.setAttr(value.plug, value.rest)
    for transform in old.transforms:
        if transform.node in nodes or not cmds.objExists(transform.node):
            continue
        plug = f"{transform.node}.offsetParentMatrix"
        _disconnect(plug)
        offset = _offset_node(transform)
        if cmds.objExists(offset):
            cmds.delete(offset)
        cmds.setAttr(plug, list(transform.parent_offset), type="matrix")


def _store(rbf: str, definition: Definition) -> None:
    """Writes *definition* on the network node of *rbf*, created when missing."""
    network = network_of(rbf)
    if network is None:
        network = str(cmds.createNode("network", name=f"{rbf}{NETWORK_SUFFIX}"))
        cmds.addAttr(network, longName=DEFINITION_ATTR, dataType="string")
        cmds.addAttr(network, longName=BOARD_LINK, attributeType="message")
        cmds.connectAttr(f"{rbf}.message", f"{network}.{BOARD_LINK}")
    cmds.setAttr(f"{network}.{DEFINITION_ATTR}", definition.to_json(), type="string")


def _cycle(rbf: str) -> list[str]:
    """Returns the plugs of a cycle through *rbf*, in order; empty without one."""
    found = cmds.cycleCheck(rbf, list=True, firstCycleOnly=True)
    return found if isinstance(found, list) else []


def _cycle_error(cycle: Sequence[str]) -> ValueError:
    """Returns the error that names the plugs of *cycle*."""
    return ValueError(f"that makes a cycle: {' -> '.join(cycle)}")


def _refuse_cycle(rbf: str, old: Definition, new: Definition) -> None:
    """Checks, outside undo, that the connections of *new* close no cycle via *rbf*.

    Raises:
        ValueError: When they would, naming the plugs of the cycle.
    """
    with unrecorded():
        _connect(rbf, new)
        try:
            cycle = _cycle(rbf)
        finally:
            _release(new, old)
            _connect(rbf, old)
    if cycle:
        raise _cycle_error(cycle)


def apply(rbf: str, definition: Definition, name: str = "poseRBF edit") -> None:
    """Makes *rbf* match *definition*, as one undo step.

    Raises:
        ValueError: When the definition cannot be built, two poses have the same
            driver values or the pose table has no solution (nothing changes then).
    """
    old = definition_of(rbf)
    try:
        texts = board.constants(definition)
    except ref.SamePosesError as same:
        first, second = (definition.poses[k].name for k in same.pair)
        raise ValueError(
            f"poses {first!r} and {second!r} have the same driver values"
        ) from None
    except np.linalg.LinAlgError:
        raise ValueError(
            "the poses have no solution: raise the Regularization"
        ) from None
    with undo_step(name):
        _release(old, definition)
        board.write(rbf, texts)
        _connect(rbf, definition)
        _store(rbf, definition)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def _driver_name(plug: str, taken: Iterable[str]) -> str:
    """Returns a name for a driver on *plug*: an identifier not in *taken*."""
    base = re.sub(r"\W", "_", plug.split("|")[-1].replace(".", "_"))
    if base[0].isdigit():
        base = f"d_{base}"
    used = set(taken)
    name, number = base, 1
    while name in used:
        number += 1
        name = f"{base}{number}"
    return name


def _single_number(plug: str) -> float:
    """Returns the value of *plug*.

    Raises:
        ValueError: When it is not one number (a compound, a matrix, a text...).
    """
    try:
        value = cmds.getAttr(plug)
    except (RuntimeError, ValueError):
        value = None
    if not isinstance(value, (int, float)):
        raise ValueError(f"{plug!r} is not a single number")
    return float(value)


def _with_pose(definition: Definition, pose: str, **changes: object) -> Definition:
    """Returns *definition* with some fields of *pose* changed."""
    index = definition.pose_index(pose)
    poses = list(definition.poses)
    poses[index] = dataclasses.replace(poses[index], **changes)
    return definition.replace(poses=tuple(poses))


def make_driver(plug: str, taken: Iterable[str] = ()) -> Driver:
    """Returns a driver for a transform, a node name, or a number, ``node.attribute``.

    Raises:
        ValueError: When *plug* does not exist or is not a transform or one number.
    """
    if not cmds.objExists(plug):
        raise ValueError(f"{plug!r} does not exist")
    name = _driver_name(plug, taken)
    if "." in plug:
        _single_number(plug)
        return Driver(name=name, plug=plug, is_matrix=False)
    if not cmds.objectType(plug, isAType="transform"):
        raise ValueError(f"{plug!r} is not a transform")
    return Driver(name=name, plug=str(cmds.ls(plug, long=False)[0]))


def make_transform(node: str) -> DrivenTransform:
    """Returns a driven transform with its current state as rest.

    Raises:
        ValueError: When *node* is not a transform, or its offsetParentMatrix is
            already connected.
    """
    if not cmds.objExists(node) or not cmds.objectType(node, isAType="transform"):
        raise ValueError(f"{node!r} is not a transform")
    if cmds.listConnections(f"{node}.offsetParentMatrix", source=True):
        raise ValueError(f"the offsetParentMatrix of {node!r} is already connected")
    return DrivenTransform(
        node=node,
        rest=_flat(_local(node)),
        rest_channels=_rest_channels(node),
        parent_offset=tuple(
            float(v) for v in cmds.getAttr(f"{node}.offsetParentMatrix")
        ),
    )


def make_value(plug: str) -> DrivenValue:
    """Returns a driven value with its current value as rest.

    Raises:
        ValueError: When *plug* does not exist, is not one number or is already
            connected.
    """
    if not cmds.objExists(plug):
        raise ValueError(f"{plug!r} does not exist")
    rest = _single_number(plug)
    if cmds.listConnections(plug, source=True, destination=False):
        raise ValueError(f"{plug!r} is already connected")
    return DrivenValue(plug=plug, rest=rest)


# ---------------------------------------------------------------------------
# Public commands
# ---------------------------------------------------------------------------


def create(
    name: str,
    drivers: Sequence[str],
    transforms: Sequence[str] = (),
    values: Sequence[str] = (),
    options: Options | None = None,
) -> str:
    """Creates an RBF whose first pose, ``rest``, is the scene as it is now.

    Creating is not recorded for undo; :func:`delete` removes the RBF.

    Args:
        name: Name of the board; made unique if taken.
        drivers: Transforms (node names) and numbers (``node.attribute``).
        transforms: Transforms it drives.
        values: Numbers it drives (``node.attribute``).
        options: How it interpolates; defaults otherwise.

    Returns:
        The RBF's name.

    Raises:
        ValueError: When a plug cannot drive or be driven, or the connections would
            close a cycle (nothing is left in the scene then).
    """
    rbf = name
    number = 1
    while cmds.objExists(rbf) or cmds.objExists(f"{rbf}{NETWORK_SUFFIX}"):
        number += 1
        rbf = f"{name}{number}"
    made: list[Driver] = []
    for plug in drivers:
        made.append(make_driver(plug, (d.name for d in made)))
    definition = Definition(
        drivers=tuple(made),
        poses=(),
        values=tuple(make_value(p) for p in values),
        transforms=tuple(make_transform(t) for t in transforms),
        options=options or Options(),
    )
    definition = definition.replace(poses=(capture_pose(rbf, definition, "rest"),))
    texts = board.constants(definition)
    existing = all_rbfs()
    with unrecorded():
        node = board.load(rbf, existing[0] if existing else None)
        board.write(node, texts)
        _store(node, definition)
        _connect(node, definition)
        cycle = _cycle(node)
        if cycle:
            _release(definition, None)
            cmds.delete([n for n in (node, network_of(node)) if n])
    if cycle:
        raise _cycle_error(cycle)
    return node


def add_pose(rbf: str, name: str | None = None) -> str:
    """Adds a pose at the drivers' current state; returns its name.

    The driven keep what they show now; move them and :func:`update_driven` to change
    it.
    """
    definition = definition_of(rbf)
    pose_name = name or definition.unique_pose_name()
    if pose_name in {p.name for p in definition.poses}:
        raise ValueError(f"there is already a pose named {pose_name!r}")
    pose = capture_pose(rbf, definition, pose_name)
    apply(rbf, definition.replace(poses=(*definition.poses, pose)), "poseRBF add pose")
    return pose_name


def update_pose(rbf: str, pose: str) -> None:
    """Moves *pose* to the drivers' current state; what it asks for is kept."""
    definition = definition_of(rbf)
    captured = capture_pose(rbf, definition, pose)
    new = _with_pose(
        definition, pose, drivers=captured.drivers, channels=captured.channels
    )
    apply(rbf, new, "poseRBF update pose")


def update_driven(rbf: str, pose: str) -> None:
    """Stores what the driven transforms show now as the moves of *pose*.

    The transforms' channels go back to rest afterwards, so they show the same thing
    through the RBF.
    """
    definition = definition_of(rbf)
    captured = capture_pose(rbf, definition, pose)
    new = _with_pose(definition, pose, moves=captured.moves)
    with undo_step("poseRBF update driven"):
        for transform in definition.transforms:
            _restore_channels(transform)
        apply(rbf, new)


def move_channels(move: Sequence[float]) -> tuple[float, ...]:
    """Returns a move as nine channels: translate, rotate in XYZ degrees, scale.

    :func:`set_pose_move` takes them back.
    """
    rotation = om.MQuaternion(*move[3:7]).asEulerRotation()
    angles = (
        math.degrees(rotation.x),
        math.degrees(rotation.y),
        math.degrees(rotation.z),
    )
    return (*map(float, move[0:3]), *angles, *map(float, move[7:10]))


def set_pose_values(rbf: str, pose: str, values: Sequence[float]) -> None:
    """Sets the driven values of *pose*, one per driven value."""
    definition = definition_of(rbf)
    if len(values) != len(definition.values):
        raise ValueError(f"{len(definition.values)} values expected, got {len(values)}")
    new = _with_pose(definition, pose, values=tuple(float(v) for v in values))
    apply(rbf, new, "poseRBF set pose values")


def set_pose_move(
    rbf: str,
    pose: str,
    node: str,
    translate: Sequence[float] = (0.0, 0.0, 0.0),
    rotate: Sequence[float] = (0.0, 0.0, 0.0),
    scale: Sequence[float] = (1.0, 1.0, 1.0),
) -> None:
    """Sets, by numbers, the move of a driven transform at *pose*, from its rest.

    *rotate* is an XYZ rotation in degrees. :func:`update_driven` stores instead what
    the transform shows; this is for scripts that know the move they want.
    """
    definition = definition_of(rbf)
    index = definition.pose_index(pose)
    nodes = [t.node for t in definition.transforms]
    if node not in nodes:
        raise ValueError(f"{node!r} is not driven by {rbf!r}")
    q = om.MEulerRotation(*(math.radians(a) for a in rotate)).asQuaternion()
    move = (*map(float, translate), q.x, q.y, q.z, q.w, *map(float, scale))
    moves = list(definition.poses[index].moves)
    moves[nodes.index(node)] = move
    new = _with_pose(definition, pose, moves=tuple(moves))
    apply(rbf, new, "poseRBF set pose move")


def go_to_pose(rbf: str, pose: str) -> None:
    """Puts the drivers back where they were when *pose* was taken."""
    definition = definition_of(rbf)
    stored = definition.poses[definition.pose_index(pose)]
    with undo_step("poseRBF go to pose"):
        for driver in definition.drivers:
            if driver.is_matrix:
                channels = stored.channels.get(driver.name)
                if channels is None:
                    continue
                cmds.setAttr(f"{driver.plug}.translate", *channels[:3])
                cmds.setAttr(f"{driver.plug}.rotate", *channels[3:6])
            else:
                cmds.setAttr(driver.plug, stored.drivers[driver.name][0])


def remove_pose(rbf: str, pose: str) -> None:
    """Removes *pose*.

    Raises:
        ValueError: When it is the last pose.
    """
    definition = definition_of(rbf)
    if len(definition.poses) == 1:
        raise ValueError("an RBF keeps at least one pose")
    index = definition.pose_index(pose)
    poses = definition.poses[:index] + definition.poses[index + 1 :]
    apply(rbf, definition.replace(poses=poses), "poseRBF remove pose")


def rename_pose(rbf: str, pose: str, name: str) -> None:
    """Renames *pose*."""
    definition = definition_of(rbf)
    if name in {p.name for p in definition.poses}:
        raise ValueError(f"there is already a pose named {name!r}")
    new = _with_pose(definition, pose, name=name)
    apply(rbf, new, "poseRBF rename pose")


def set_options(rbf: str, **changes: object) -> None:
    """Changes options; see :class:`~poserbf.definition.Options`.

    ``kernel``, ``radius``, ``mode``, ``margin``, ``normalize``, ``clamp_negative``.
    """
    definition = definition_of(rbf)
    options = dataclasses.replace(definition.options, **changes)
    apply(rbf, definition.replace(options=options), "poseRBF set options")


def set_driver(rbf: str, driver: str, **changes: object) -> None:
    """Changes how a driver is measured; see :class:`~poserbf.definition.Driver`.

    ``rotation``, ``swing``, ``twist``, ``translation``, ``axis``, ``number``.
    """
    definition = definition_of(rbf)
    if driver not in {d.name for d in definition.drivers}:
        raise ValueError(f"no driver named {driver!r}")
    drivers = tuple(
        dataclasses.replace(d, **changes) if d.name == driver else d
        for d in definition.drivers
    )
    apply(rbf, definition.replace(drivers=drivers), "poseRBF set driver")


def add_driver(rbf: str, plug: str) -> str:
    """Adds a driver; every existing pose takes its current state. Returns its name.

    Raises:
        ValueError: When *plug* already drives *rbf*, cannot drive, or would close a
            cycle (nothing changes then).
    """
    definition = definition_of(rbf)
    if plug in {d.plug for d in definition.drivers}:
        raise ValueError(f"{plug!r} already drives {rbf!r}")
    driver = make_driver(plug, (d.name for d in definition.drivers))
    state = driver_state(driver)
    channels = driver_channels(driver) if driver.is_matrix else None
    poses = tuple(
        Pose(
            p.name,
            {**p.drivers, driver.name: state},
            p.values,
            p.moves,
            {**p.channels, driver.name: channels} if channels else p.channels,
        )
        for p in definition.poses
    )
    new = definition.replace(drivers=(*definition.drivers, driver), poses=poses)
    _refuse_cycle(rbf, definition, new)
    apply(rbf, new, "poseRBF add driver")
    return driver.name


def remove_driver(rbf: str, driver: str) -> None:
    """Removes a driver and its state from every pose."""
    definition = definition_of(rbf)
    drivers = tuple(d for d in definition.drivers if d.name != driver)
    if len(drivers) == len(definition.drivers):
        raise ValueError(f"no driver named {driver!r}")
    poses = tuple(
        Pose(
            p.name,
            {k: v for k, v in p.drivers.items() if k != driver},
            p.values,
            p.moves,
            {k: v for k, v in p.channels.items() if k != driver},
        )
        for p in definition.poses
    )
    apply(
        rbf, definition.replace(drivers=drivers, poses=poses), "poseRBF remove driver"
    )


def add_driven(
    rbf: str, transforms: Sequence[str] = (), values: Sequence[str] = ()
) -> None:
    """Adds driven transforms and values; every pose keeps them at rest.

    Raises:
        ValueError: When one cannot be driven or would close a cycle (nothing changes
            then).
    """
    definition = definition_of(rbf)
    new_transforms = tuple(make_transform(t) for t in transforms)
    new_values = tuple(make_value(p) for p in values)
    poses = tuple(
        dataclasses.replace(
            p,
            values=p.values + tuple(v.rest for v in new_values),
            moves=p.moves + tuple(IDENTITY_MOVE for _ in new_transforms),
        )
        for p in definition.poses
    )
    new = definition.replace(
        transforms=definition.transforms + new_transforms,
        values=definition.values + new_values,
        poses=poses,
    )
    _refuse_cycle(rbf, definition, new)
    apply(rbf, new, "poseRBF add driven")


def remove_driven(rbf: str, items: Sequence[str]) -> None:
    """Stops driving the given transforms (node names) and values (plugs)."""
    definition = definition_of(rbf)
    keep_t = [j for j, t in enumerate(definition.transforms) if t.node not in items]
    keep_v = [k for k, v in enumerate(definition.values) if v.plug not in items]
    poses = tuple(
        dataclasses.replace(
            p,
            values=tuple(p.values[k] for k in keep_v),
            moves=tuple(p.moves[j] for j in keep_t),
        )
        for p in definition.poses
    )
    apply(
        rbf,
        definition.replace(
            transforms=tuple(definition.transforms[j] for j in keep_t),
            values=tuple(definition.values[k] for k in keep_v),
            poses=poses,
        ),
        "poseRBF remove driven",
    )


def delete(rbf: str) -> None:
    """Deletes the RBF and gives back what it drove (rest values and offsets)."""
    definition = definition_of(rbf)
    network = network_of(rbf)
    with undo_step("poseRBF delete"):
        _release(definition, None)
        cmds.delete([n for n in (rbf, network) if n and cmds.objExists(n)])
