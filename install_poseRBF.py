"""The poseRBF installer, run by dragging this file onto a Maya viewport.

It copies the ``poserbf`` folder to the folder it asks for, by default the Maya scripts
folder every Maya version reads, and adds a "poseRBF" button to the shelf shown. Each
RBF keeps its whole Bifrost graph inside the scene; nothing else is installed.
Deleting that folder and the button uninstalls it.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Final, cast

PACKAGE: Final[str] = "poserbf"
LABEL: Final[str] = "poseRBF"
ICON: Final[str] = "poseRBF.svg"
SHELVES: Final[str] = "ShelfLayout"
"""Maya's shelf tabs: the ``shelfTabLayout`` its ``shelf.mel`` names so."""
COMMAND: Final[str] = """import sys
folder = r"{folder}"
if folder not in sys.path:
    sys.path.append(folder)
import poserbf.ui
poserbf.ui.show()
"""


def default_folder() -> Path:
    """Returns the Maya scripts folder that every Maya version reads."""
    from maya import cmds

    return Path(cmds.internalVar(userAppDir=True)) / "scripts"


def copy_package(source: Path, folder: Path) -> Path:
    """Copies the package into *folder*, replacing an earlier copy; returns it.

    Raises:
        FileExistsError: When *folder* already holds a ``poserbf`` that is not this
            tool.
    """
    target = folder / PACKAGE
    if target.resolve() == source.resolve():
        return target
    if target.exists():
        if not (target / "commands.py").is_file():
            raise FileExistsError(f"{target} exists and is not poseRBF")
        shutil.rmtree(target)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source, target, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store")
    )
    return target


def add_shelf_button(folder: Path) -> str:
    """Adds the poseRBF button to the shelf shown (or updates it); returns the shelf."""
    from maya import cmds

    shelf = cmds.shelfTabLayout(SHELVES, query=True, selectTab=True)
    command = COMMAND.format(folder=folder)
    image = str(folder / PACKAGE / ICON)
    # Maya: its stubs type this query as bool; it answers a list of names, or None.
    children = cast(
        "list[str] | None", cmds.shelfLayout(shelf, query=True, childArray=True)
    )
    existing = [
        b
        for b in children or []
        if cmds.shelfButton(b, exists=True)
        and cmds.shelfButton(b, query=True, label=True) == LABEL
    ]
    if existing:
        cmds.shelfButton(existing[0], edit=True, command=command, image=image)
    else:
        cmds.shelfButton(
            parent=shelf,
            label=LABEL,
            annotation="Create and edit pose RBFs",
            image=image,
            command=command,
            sourceType="python",
        )
    cmds.saveAllShelves(SHELVES)
    return str(shelf)


def install(folder: Path) -> str:
    """Copies the tool into *folder* and adds its shelf button; returns a summary."""
    source = Path(__file__).resolve().parent / PACKAGE
    copy_package(source, folder)
    if str(folder) not in sys.path:
        sys.path.append(str(folder))
    for name in [m for m in sys.modules if m == PACKAGE or m.startswith(f"{PACKAGE}.")]:
        # Trap: a module already loaded would hide the copy just made.
        del sys.modules[name]
    shelf = add_shelf_button(folder)
    return f"poseRBF is in {folder / PACKAGE}.\nIts button is on the {shelf} shelf."


def onMayaDroppedPythonFile(*_: object) -> None:
    """Runs the installer when the file is dropped onto a viewport."""
    from maya import cmds

    folder = default_folder()
    answer = cmds.confirmDialog(
        title="Install poseRBF",
        message=f"Copy poseRBF to\n{folder}\nand add its button to the shelf shown?",
        button=["Install", "Choose Folder...", "Cancel"],
        defaultButton="Install",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if answer == "Choose Folder...":
        chosen = cmds.fileDialog2(
            fileMode=3,
            dialogStyle=2,
            startingDirectory=str(folder),
            caption="Folder for poseRBF",
        )
        if not chosen:
            return
        folder = Path(chosen[0])
    elif answer != "Install":
        return
    try:
        message = install(folder)
    except OSError as error:
        cmds.confirmDialog(title="Install poseRBF", message=str(error), button=["OK"])
        return
    cmds.confirmDialog(title="poseRBF installed", message=message, button=["OK"])
