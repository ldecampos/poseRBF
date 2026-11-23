"""The Maya session the window works in: its selection, its events and its dock.

Every function translates one request of the window into ``maya.cmds``; the window
makes no other call to Maya.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Final, cast

from maya import cmds

CHANNEL_BOX: Final[str] = "mainChannelBox"
"""The Channel Box of Maya's main window."""
EVENTS: Final[tuple[str, ...]] = ("Undo", "Redo", "SceneOpened", "NewSceneOpened")
"""The scene events :func:`watch` follows."""
_jobs: list[int] = []
"""The scriptJobs :func:`watch` started."""


def _keep(job: object) -> None:
    """Keeps the number of a scriptJob, to end it later."""
    if isinstance(job, int):
        _jobs.append(job)


def watch(refresh: Callable[[], object], control: str) -> None:
    """Calls *refresh* after undo, redo and scene changes until *control* is deleted."""
    for event in EVENTS:
        _keep(cmds.scriptJob(event=(event, refresh)))
    _keep(cmds.scriptJob(uiDeleted=(control, stop_watching), runOnce=True))


def stop_watching() -> None:
    """Ends the scriptJobs :func:`watch` started; one that is running ends itself."""
    while _jobs:
        job = _jobs.pop()
        # Maya: a job cannot be killed while it runs; the runOnce one ends itself.
        with contextlib.suppress(RuntimeError):
            if cmds.scriptJob(exists=job):
                cmds.scriptJob(kill=job, force=True)


def stop_watching_later() -> None:
    """Ends the scriptJobs :func:`watch` started once Maya is idle."""
    cmds.evalDeferred(stop_watching)


def delete_control(control: str) -> None:
    """Deletes the workspaceControl *control*, when it exists."""
    if cmds.workspaceControl(control, exists=True):
        cmds.deleteUI(control, control=True)


def selected_transforms() -> list[str]:
    """Returns the selected transforms."""
    found: list[str] = cmds.ls(selection=True, type="transform") or []
    return found


def selected_attributes(required: bool = False) -> list[str]:
    """Returns ``node.attribute`` for each attribute selected in the Channel Box.

    Raises:
        ValueError: When *required* and nothing is selected there.
    """
    nodes: list[str] = cmds.ls(selection=True) or []
    # Maya: its stubs type this query as bool; it answers a list of names, or None.
    attributes = cast(
        "list[str] | None",
        cmds.channelBox(CHANNEL_BOX, query=True, selectedMainAttributes=True),
    )
    plugs = [f"{node}.{name}" for node in nodes for name in attributes or []]
    if required and not plugs:
        raise ValueError("select the node and its attributes in the Channel Box")
    return plugs


def select(node: str) -> None:
    """Selects *node* alone."""
    cmds.select(node, replace=True)
