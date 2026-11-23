"""The installer copies the package whole, and nothing it does not own is lost."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import install_poseRBF

SOURCE = Path(install_poseRBF.__file__).resolve().parent / install_poseRBF.PACKAGE


def files_of(folder: Path) -> dict[str, bytes]:
    """Returns the content of every file the package ships, by its path."""
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in folder.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.name != ".DS_Store"
    }


def test_the_copy_holds_every_file_of_the_package(tmp_path: Path) -> None:
    target = install_poseRBF.copy_package(SOURCE, tmp_path / "scripts")
    assert target == tmp_path / "scripts" / install_poseRBF.PACKAGE
    assert files_of(target) == files_of(SOURCE)


def test_the_copy_leaves_compiled_files_out(tmp_path: Path) -> None:
    source = tmp_path / "source" / install_poseRBF.PACKAGE
    shutil.copytree(SOURCE, source, ignore=shutil.ignore_patterns("__pycache__"))
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "ui.pyc").write_bytes(b"compiled")
    target = install_poseRBF.copy_package(source, tmp_path / "scripts")
    assert not (target / "__pycache__").exists()


def test_an_earlier_copy_is_replaced(tmp_path: Path) -> None:
    target = install_poseRBF.copy_package(SOURCE, tmp_path)
    (target / "removed_since.py").write_text("", encoding="utf-8")
    install_poseRBF.copy_package(SOURCE, tmp_path)
    assert files_of(target) == files_of(SOURCE)


def test_a_folder_of_another_tool_is_left_alone(tmp_path: Path) -> None:
    other = tmp_path / install_poseRBF.PACKAGE
    other.mkdir()
    (other / "notes.txt").write_text("another tool", encoding="utf-8")
    with pytest.raises(FileExistsError, match="is not poseRBF"):
        install_poseRBF.copy_package(SOURCE, tmp_path)
    assert files_of(other) == {"notes.txt": b"another tool"}


def test_installing_where_it_already_is_changes_nothing(tmp_path: Path) -> None:
    target = install_poseRBF.copy_package(SOURCE, tmp_path)
    assert install_poseRBF.copy_package(target, tmp_path) == target
    assert files_of(target) == files_of(SOURCE)
