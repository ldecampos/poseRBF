"""The pose RBF window (PySide6), dockable in Maya.

Every edit calls one function of ``commands`` and is one undo step; creating an RBF is
not undone (Delete removes it). Poses are rows wherever they show; the actions on a
pose, a driver or a driven channel (its column header) are in its right-click menu, as
in Maya's editors. The window reads the shown RBF again after each action, undo, redo
and scene change, keeps the selected pose selected by name, and a few times a second
reads the weight of each pose while the Poses tab shows, and where the drivers are on
the plotted path while the Options tab shows.
"""

from __future__ import annotations

import contextlib
import functools
import logging
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass
from typing import Final, Literal, TypeAlias

import numpy as np
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

from . import commands, preview, session
from . import reference as ref
from .definition import Definition, Driver, Options, Pose
from .plot import (
    FIRST_COLOUR,
    SECOND_COLOUR,
    Band,
    Colour,
    Dot,
    Line,
    Picture,
    Plot,
    Tick,
)

logger = logging.getLogger(__name__)
OBJECT_NAME: Final[str] = "poseRBFWindow"
CONTROL: Final[str] = f"{OBJECT_NAME}WorkspaceControl"
"""The workspaceControl Maya makes for the window."""
WEIGHT_INTERVAL_MS: Final[int] = 150
"""How often the Poses tab reads the weights."""
DRIVER_COLUMNS: Final[tuple[str, ...]] = (
    "Driver", "Rotation", "Swing", "Twist", "Translation", "Axis", "Attribute",
)  # fmt: skip
WEIGHT_COLUMNS: Final[tuple[int, ...]] = (1, 2, 3, 4, 6)
"""The Drivers columns that hold how much a measure counts."""
FACTOR_FIELDS: Final[tuple[str, ...]] = ("rotation", "swing", "twist", "translation")
MOVE_CHANNELS: Final[tuple[str, ...]] = (
    "tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz",
)  # fmt: skip
"""The channels of a driven transform's move, by their short names."""
OPTIONS_TAB: Final[int] = 3
"""The index of the Options tab."""
PATH_EDGE: Final[float] = 0.5
"""How far the path is drawn past each pose, as a part of the way between them."""
WARNING_COLOUR: Final[str] = "#e67e22"
ERROR_COLOUR: Final[str] = "#e74c3c"
_window: Window | None = None
"""The window of the session, once shown."""


def show() -> Window:
    """Shows the window, one per session, floating at first; returns it."""
    global _window
    if _window is None or not Shiboken.isValid(_window):
        _drop_leftovers()
        _window = Window()
        _window.show(dockable=True, floating=True, retain=False, width=560, height=680)
        _window.watch()
    else:
        _window.show(dockable=True)
    _window.refresh()
    _window.raise_()
    return _window


def _drop_leftovers() -> None:
    """Deletes windows and controls an earlier session left under the window's name."""
    # Maya: it docks the widget its lookup finds by name, which may be an older one.
    session.stop_watching()
    for widget in QtWidgets.QApplication.allWidgets():
        if Shiboken.isValid(widget) and widget.objectName() == OBJECT_NAME:
            Shiboken.delete(widget)
    session.delete_control(CONTROL)


def _number(text: str) -> float:
    """Returns the number typed in a cell; a comma is read as the decimal point.

    Raises:
        ValueError: When *text* is not a number.
    """
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        raise ValueError(f"{text!r} is not a number") from None


def _text(value: float) -> str:
    """Returns a number as a cell shows it: up to four decimals, no negative zero."""
    return f"{round(value, 4) + 0.0:g}"


def _item(text: str, editable: bool = True) -> QtWidgets.QTableWidgetItem:
    """Returns a table cell that shows *text*."""
    item = QtWidgets.QTableWidgetItem(text)
    if not editable:
        item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
    return item


def _choices(box: QtWidgets.QComboBox, values: Sequence[str], tip: str = "") -> None:
    """Fills *box* with *values*, shown in Title Case and kept as its data."""
    for value in values:
        box.addItem(value.replace("_", " ").title(), value)
    box.setToolTip(tip)


def _weight_tip(measure: str) -> str:
    """Returns the tooltip of a Drivers column that says how much *measure* counts."""
    return (
        f"Set how much the {measure.lower()} counts: "
        "0 ignores it, 1 counts it, 2 counts it double"
    )


def _choose(box: QtWidgets.QComboBox, value: str) -> None:
    """Shows the entry of *box* whose data is *value*."""
    box.setCurrentIndex(box.findData(value))


Field: TypeAlias = QtWidgets.QWidget | QtWidgets.QLayout
"""What a row of an Options group holds after its label."""


@dataclass(frozen=True, slots=True)
class PoseColumn:
    """What one column of the Poses table shows.

    Attributes:
        kind: The pose's name, its live weight, or a driver channel at the pose.
        driver: The driver, for a driver column.
        channel: For a transform driver, 0-5 into its stored translate and rotate.
    """

    kind: Literal["name", "weight", "driver"]
    driver: Driver | None = None
    channel: int = 0


@dataclass(frozen=True, slots=True)
class DrivenColumn:
    """What one column of the Driven table shows, after the pose's name.

    Attributes:
        kind: A channel of a driven transform's move, or a driven value.
        index: Index of the transform or of the value.
        channel: 0-8 into :data:`MOVE_CHANNELS`, for a transform.
    """

    kind: Literal["move", "value"]
    index: int
    channel: int = 0


def driver_columns(driver: Driver) -> list[PoseColumn]:
    """Returns the Poses columns for *driver*: the channels its measures read."""
    if not driver.is_matrix:
        return [PoseColumn("driver", driver)] if driver.number > 0 else []
    channels: list[int] = []
    if driver.translation > 0:
        channels += [0, 1, 2]
    if driver.rotation > 0 or driver.swing > 0 or driver.twist > 0:
        channels += [3, 4, 5]
    return [PoseColumn("driver", driver, channel) for channel in channels]


def column_header(column: PoseColumn) -> str:
    """Returns the header of one Poses column."""
    if column.kind == "name":
        return "Pose"
    if column.kind == "weight":
        return "Weight"
    assert column.driver is not None
    if not column.driver.is_matrix:
        return column.driver.plug
    return (
        f"{column.driver.plug}.{('tx', 'ty', 'tz', 'rx', 'ry', 'rz')[column.channel]}"
    )


def column_value(column: PoseColumn, pose: Pose) -> float | None:
    """Returns what one Poses column holds for *pose*, or None for nothing."""
    if column.kind != "driver" or column.driver is None:
        return None
    if not column.driver.is_matrix:
        return pose.drivers[column.driver.name][0]
    channels = pose.channels.get(column.driver.name)
    return None if channels is None else channels[column.channel]


def _swatch(colour: Colour, size: int) -> QtGui.QIcon:
    """Returns a square of *colour*, *size* pixels wide, as an icon."""
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtGui.QColor(*colour))
    return QtGui.QIcon(pixmap)


class Columns(QtWidgets.QWidget):
    """Lays its widgets side by side, or one under the other when they do not fit."""

    def __init__(self, *widgets: QtWidgets.QWidget) -> None:
        """Lays out *widgets* side by side, in this order."""
        super().__init__()
        self._widgets = widgets
        self._layout = QtWidgets.QBoxLayout(
            QtWidgets.QBoxLayout.Direction.LeftToRight, self
        )
        self._layout.setContentsMargins(0, 0, 0, 0)
        for widget in widgets:
            self._layout.addWidget(widget, 1)
        self.setMinimumWidth(max(w.minimumSizeHint().width() for w in widgets))

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        """Lays the widgets side by side when they fit at their smallest, or stacked."""
        needed = sum(w.minimumSizeHint().width() for w in self._widgets)
        needed += self._layout.spacing() * (len(self._widgets) - 1)
        direction = (
            QtWidgets.QBoxLayout.Direction.LeftToRight
            if event.size().width() >= needed
            else QtWidgets.QBoxLayout.Direction.TopToBottom
        )
        if self._layout.direction() != direction:
            self._layout.setDirection(direction)
        super().resizeEvent(event)


class WeightDelegate(QtWidgets.QStyledItemDelegate):
    """A cell painter that draws a weight as a bar behind its number."""

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex | QtCore.QPersistentModelIndex,
    ) -> None:
        """Draws the bar, as long as the weight between 0 and 1, then the number."""
        weight = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if isinstance(weight, float):
            colour = QtGui.QColor(
                option.palette.color(QtGui.QPalette.ColorRole.Highlight)
            )
            colour.setAlphaF(0.55)
            bar = QtCore.QRectF(option.rect).adjusted(1, 2, -1, -2)
            bar.setWidth(bar.width() * min(max(weight, 0.0), 1.0))
            painter.fillRect(bar, colour)
        super().paint(painter, option, index)


class Window(MayaQWidgetDockableMixin, QtWidgets.QWidget):
    """The tool's window."""

    def __init__(self) -> None:
        """Builds the widgets; :meth:`watch` starts following the scene once shown."""
        super().__init__()
        self.setObjectName(OBJECT_NAME)
        self.setWindowTitle("poseRBF")
        self._loading = False
        self._shown: Definition | None = None
        self._pose: str | None = None
        """The selected pose, by name: the same row in the Poses and Driven tabs."""
        self._pose_columns: list[PoseColumn] = []
        self._driven_columns: list[DrivenColumn] = []
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(WEIGHT_INTERVAL_MS)
        self._timer.timeout.connect(self.update_weights)
        self._timer.timeout.connect(self.update_marker)

        self.rbf_box = QtWidgets.QComboBox()
        self.rbf_box.currentTextChanged.connect(self._rbf_picked)
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("new RBF name")
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("RBF"))
        top.addWidget(self.rbf_box, 1)
        top.addWidget(
            self._button(
                "Delete",
                self.delete_rbf,
                "Delete the RBF and return the driven to their rest values",
            )
        )
        create = QtWidgets.QHBoxLayout()
        create.addWidget(self.name_edit, 1)
        create.addWidget(
            self._button(
                "New from Selection",
                self.create_rbf,
                "Create an RBF driven by the selected objects or attributes",
            )
        )

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._poses_tab(), "Poses")
        self.tabs.addTab(self._drivers_tab(), "Drivers")
        self.tabs.addTab(self._driven_tab(), "Driven")
        self.tabs.addTab(self._options_tab(), "Options")
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(create)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.status)

    def watch(self) -> None:
        """Follows undo, redo and scene changes, and the weights, until it closes.

        Maya makes the window's control when it is first shown, so this runs after.
        """
        session.watch(self.refresh, CONTROL)
        self._timer.start()

    def dockCloseEventTriggered(self) -> None:
        """Stops following the scene when Maya closes the window's control."""
        self._timer.stop()
        session.stop_watching()

    # ---------------------------------------------------------------------------
    # Building
    # ---------------------------------------------------------------------------

    def _button(
        self, text: str, action: Callable[[], object], tip: str
    ) -> QtWidgets.QPushButton:
        """Returns a button that runs *action* through :meth:`_run`."""
        button = QtWidgets.QPushButton(text)
        button.setToolTip(tip)
        button.clicked.connect(lambda _checked=False: self._run(action))
        return button

    @staticmethod
    def _on_right_click(
        view: Callable[[], QtWidgets.QAbstractItemView],
        place: Callable[[QtCore.QPoint], int | None],
        menu: Callable[[int | None], QtWidgets.QMenu],
    ) -> None:
        """Opens ``menu(place(point))`` where the view from *view* is right-clicked."""
        # Qt: a view's wrapper can die while the view lives; it is asked for each time.
        view().setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)

        def requested(point: QtCore.QPoint) -> None:
            popup = menu(place(point))
            popup.exec(view().viewport().mapToGlobal(point))
            popup.deleteLater()

        view().customContextMenuRequested.connect(requested)

    def _table(
        self, menu: Callable[[int | None], QtWidgets.QMenu], poses: bool = False
    ) -> QtWidgets.QTableWidget:
        """Returns a table whose right-click menu *menu* builds.

        Args:
            menu: Builds the menu of the row clicked, or of the table for None.
            poses: Whether its rows are the poses, selecting one selecting the pose.
        """
        table = QtWidgets.QTableWidget()
        table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        table.verticalHeader().setVisible(False)

        def row_at(point: QtCore.QPoint) -> int | None:
            index = table.indexAt(point)
            if not index.isValid():
                return None
            table.selectRow(index.row())
            return index.row()

        self._on_right_click(lambda: table, row_at, menu)
        if poses:
            table.itemSelectionChanged.connect(lambda: self._pose_picked(table))
        return table

    def _action(
        self, menu: QtWidgets.QMenu, text: str, action: Callable[[], object]
    ) -> QtGui.QAction:
        """Adds to *menu* an item that runs *action* through :meth:`_run`."""
        item = QtGui.QAction(text, menu)
        item.triggered.connect(lambda _checked=False: self._run(action))
        menu.addAction(item)
        return item

    @staticmethod
    def _separator(menu: QtWidgets.QMenu) -> None:
        """Adds a separator to *menu*."""
        line = QtGui.QAction(menu)
        line.setSeparator(True)
        menu.addAction(line)

    def _poses_tab(self) -> QtWidgets.QWidget:
        """Returns the Poses tab."""
        tab = QtWidgets.QWidget()
        self.pose_table = self._table(self.pose_menu, poses=True)
        self.pose_table.setItemDelegateForColumn(1, WeightDelegate(self.pose_table))
        self.pose_table.itemChanged.connect(self._pose_cell_changed)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(
            self._button(
                "Add Pose", self.add_pose, "Add a pose at the current driver values"
            )
        )
        buttons.addStretch(1)
        layout = QtWidgets.QVBoxLayout(tab)
        layout.addWidget(self.pose_table, 1)
        layout.addLayout(buttons)
        return tab

    def _drivers_tab(self) -> QtWidgets.QWidget:
        """Returns the Drivers tab."""
        tab = QtWidgets.QWidget()
        self.driver_table = self._table(self.driver_menu)
        self.driver_table.setColumnCount(len(DRIVER_COLUMNS))
        self.driver_table.setHorizontalHeaderLabels(DRIVER_COLUMNS)
        for column in WEIGHT_COLUMNS:
            header = self.driver_table.horizontalHeaderItem(column)
            header.setToolTip(_weight_tip(DRIVER_COLUMNS[column]))
        self.driver_table.itemChanged.connect(self._driver_cell_changed)
        layout = QtWidgets.QVBoxLayout(tab)
        layout.addWidget(self.driver_table, 1)
        layout.addLayout(
            self._add_buttons(self.add_drivers, self.add_number_drivers, "drivers")
        )
        return tab

    def _driven_tab(self) -> QtWidgets.QWidget:
        """Returns the Driven tab."""
        tab = QtWidgets.QWidget()
        self.driven_table = self._table(self._driven_pose_menu, poses=True)
        self.driven_table.itemChanged.connect(self._driven_cell_changed)
        # Qt: a header's wrapper dies when its table's items are replaced.
        header = self.driven_table.horizontalHeader

        def column_at(point: QtCore.QPoint) -> int | None:
            column = header().logicalIndexAt(point)
            return column if column > 0 else None

        self._on_right_click(header, column_at, self.driven_menu)
        layout = QtWidgets.QVBoxLayout(tab)
        layout.addWidget(self.driven_table, 1)
        layout.addLayout(
            self._add_buttons(self.add_transforms, self.add_values, "driven")
        )
        return tab

    def _add_buttons(
        self,
        transforms: Callable[[], object],
        attributes: Callable[[], object],
        role: str,
    ) -> QtWidgets.QHBoxLayout:
        """Returns the buttons that add selected transforms and attributes as *role*."""
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(
            self._button(
                "Add Selected Transforms",
                transforms,
                f"Add the selected objects as {role}",
            )
        )
        buttons.addWidget(
            self._button(
                "Add Channel Box Attributes",
                attributes,
                f"Add the attributes selected in the Channel Box as {role}",
            )
        )
        return buttons

    def _option_box(self, box: QtWidgets.QComboBox, field: str) -> None:
        """Makes the entry picked in *box* set the option *field*."""

        def picked(_index: int) -> None:
            """Sets the option to the entry picked."""
            self._set_option(**{field: box.currentData()})

        box.currentIndexChanged.connect(picked)

    def _options_tab(self) -> QtWidgets.QWidget:
        """Returns the Options tab."""
        self.kernel_box = QtWidgets.QComboBox()
        _choices(
            self.kernel_box, ref.KERNELS, "Set the falloff of each pose's influence"
        )
        self._option_box(self.kernel_box, "kernel")
        self.curve_plot = Plot()
        self.from_box = QtWidgets.QComboBox()
        self.from_box.setToolTip("Set the pose the drivers start from")
        self.to_box = QtWidgets.QComboBox()
        self.to_box.setToolTip("Set the pose the drivers move to")
        for box in (self.from_box, self.to_box):
            box.currentIndexChanged.connect(self._path_changed)
        self.path_plot = Plot()

        self.automatic_box = QtWidgets.QCheckBox("Automatic")
        self.automatic_box.setToolTip("Set the radius from the distance between poses")
        self.automatic_box.toggled.connect(self._automatic_toggled)
        self.radius_spin = QtWidgets.QDoubleSpinBox()
        self.radius_spin.setToolTip("Set the distance over which the influence fades")
        self.radius_spin.setRange(0.001, 1e6)
        self.radius_spin.setDecimals(3)
        self.radius_spin.setKeyboardTracking(False)
        self.radius_spin.valueChanged.connect(self._radius_changed)

        self.mode_box = QtWidgets.QComboBox()
        _choices(
            self.mode_box,
            ("interpolative", "additive"),
            "Set whether each pose is matched exactly or added on top",
        )
        self._option_box(self.mode_box, "mode")
        self.margin_spin = QtWidgets.QDoubleSpinBox()
        self.margin_spin.setToolTip(
            "Set how much accuracy at the poses is traded for smoothness"
        )
        self.margin_spin.setRange(0.0, 10.0)
        self.margin_spin.setDecimals(4)
        self.margin_spin.setSingleStep(0.01)
        self.margin_spin.setKeyboardTracking(False)
        self.margin_spin.valueChanged.connect(self._margin_changed)

        self.normalize_box = QtWidgets.QComboBox()
        _choices(
            self.normalize_box,
            ref.NORMALIZE_MODES,
            "Set when the weights are scaled to add up to 1",
        )
        self._option_box(self.normalize_box, "normalize")
        self.negative_box = QtWidgets.QCheckBox("Allow Negative Weights")
        self.negative_box.toggled.connect(self._negative_toggled)

        radius = QtWidgets.QHBoxLayout()
        radius.addWidget(self.automatic_box)
        radius.addWidget(self.radius_spin, 1)

        def section(
            title: str, rows: list[tuple[str, Field]], plot: Plot | None = None
        ) -> QtWidgets.QGroupBox:
            """Returns a group titled *title* with *rows* and, under them, *plot*."""
            group = QtWidgets.QGroupBox(title)
            form = QtWidgets.QFormLayout(group)
            for label, field in rows:
                form.addRow(label, field)
            if plot is not None:
                form.addRow(plot)
                form.setAlignment(plot, QtCore.Qt.AlignmentFlag.AlignHCenter)
            return group

        content = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(content)
        column.addWidget(
            Columns(
                section(
                    "Falloff",
                    [("Curve", self.kernel_box), ("Radius", radius)],
                    self.curve_plot,
                ),
                section(
                    "Weights Between Poses",
                    [("From", self.from_box), ("To", self.to_box)],
                    self.path_plot,
                ),
            )
        )
        column.addWidget(
            Columns(
                section(
                    "Interpolation",
                    [("Mode", self.mode_box), ("Regularization", self.margin_spin)],
                ),
                section(
                    "Weights",
                    [("Normalize", self.normalize_box), ("", self.negative_box)],
                ),
            )
        )
        column.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    # ---------------------------------------------------------------------------
    # Reading
    # ---------------------------------------------------------------------------

    @property
    def rbf(self) -> str:
        """The RBF shown, or "" when there is none."""
        return self.rbf_box.currentText()

    @contextlib.contextmanager
    def _quiet(self) -> Generator[None, None, None]:
        """Ignores the widgets' signals while the block inside fills them."""
        loading = self._loading
        self._loading = True
        try:
            yield
        finally:
            self._loading = loading

    def refresh(self) -> None:
        """Lists the RBFs in the scene and shows the selected one."""
        if not Shiboken.isValid(self):
            session.stop_watching_later()
            return
        current = self.rbf
        with self._quiet():
            self.rbf_box.clear()
            self.rbf_box.addItems(commands.all_rbfs())
            if current:
                self.rbf_box.setCurrentText(current)
        self.refresh_rbf()

    def _rbf_picked(self, _name: str) -> None:
        """Shows the RBF picked in the list."""
        self.refresh_rbf()

    def refresh_rbf(self) -> None:
        """Shows the definition of the selected RBF."""
        if self._loading:
            return
        definition = self._definition()
        self._shown = definition
        with self._quiet():
            self._show_poses(definition)
            self._show_drivers(definition)
            self._show_driven(definition)
            self._show_options(definition)
            self._show_selected_pose()
        self.update_weights()

    def _pose_picked(self, table: QtWidgets.QTableWidget) -> None:
        """Takes the pose selected in *table* as the selected pose of both tabs."""
        rows = table.selectionModel().selectedRows()
        if self._loading or self._shown is None or not rows:
            return
        row = rows[0].row()
        if row < len(self._shown.poses):
            self._pose = self._shown.poses[row].name
            with self._quiet():
                self._show_selected_pose()

    def _show_selected_pose(self) -> None:
        """Selects the selected pose's row in the Poses and Driven tables."""
        names = [p.name for p in self._shown.poses] if self._shown else []
        row = names.index(self._pose) if self._pose in names else None
        for table in (self.pose_table, self.driven_table):
            if row is None:
                table.clearSelection()
                continue
            table.selectRow(row)
            # Trap: scrolling to column 0 would reset the horizontal scroll.
            left = max(table.columnAt(0), 0)
            table.scrollTo(table.model().index(row, left))

    def _definition(self) -> Definition | None:
        """Returns the definition of the RBF shown, or None."""
        if not self.rbf:
            return None
        try:
            return commands.definition_of(self.rbf)
        except ValueError:
            return None

    def _show_poses(self, definition: Definition | None) -> None:
        """Fills the Poses table with the poses of *definition*."""
        table = self.pose_table
        columns = [PoseColumn("name"), PoseColumn("weight")]
        if definition is not None:
            for driver in definition.drivers:
                columns += driver_columns(driver)
        self._pose_columns = columns
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels([column_header(c) for c in columns])
        poses = definition.poses if definition else ()
        table.setRowCount(len(poses))
        for row, pose in enumerate(poses):
            for index, column in enumerate(columns):
                if column.kind == "name":
                    table.setItem(row, index, _item(pose.name))
                    continue
                value = column_value(column, pose)
                text = "" if value is None else _text(value)
                table.setItem(row, index, _item(text, editable=False))
        table.resizeColumnsToContents()
        bar = self.fontMetrics().horizontalAdvance("-0.00") * 3
        table.setColumnWidth(1, max(table.columnWidth(1), bar))

    def update_weights(self) -> None:
        """Shows the weight of each pose now, in the Poses tab."""
        if (
            not Shiboken.isValid(self)
            or not self.isVisible()
            or self.tabs.currentIndex() != 0
            or self._shown is None
        ):
            return
        weights = commands.weights(self.rbf)
        with self._quiet():
            for row in range(min(self.pose_table.rowCount(), len(weights))):
                item = self.pose_table.item(row, 1)
                weight = weights[row]
                item.setData(QtCore.Qt.ItemDataRole.UserRole, weight)
                item.setText(f"{weight + 0.0:.2f}")

    def _show_drivers(self, definition: Definition | None) -> None:
        """Fills the Drivers table with the drivers of *definition*."""
        drivers = definition.drivers if definition else ()
        table = self.driver_table
        table.setRowCount(len(drivers))
        for row, driver in enumerate(drivers):
            table.setItem(row, 0, _item(f"{driver.name}  ({driver.plug})", False))
            for column, field in enumerate(FACTOR_FIELDS, 1):
                text = _text(getattr(driver, field)) if driver.is_matrix else ""
                table.setItem(row, column, _item(text, driver.is_matrix))
                if driver.is_matrix:
                    table.item(row, column).setToolTip(
                        _weight_tip(DRIVER_COLUMNS[column])
                    )
            axis = QtWidgets.QComboBox()
            _choices(axis, ref.AXES)
            _choose(axis, driver.axis)
            axis.setEnabled(driver.is_matrix)
            axis.currentIndexChanged.connect(
                functools.partial(self._axis_picked, driver.name, axis)
            )
            table.setCellWidget(row, 5, axis)
            number = "" if driver.is_matrix else _text(driver.number)
            table.setItem(row, 6, _item(number, not driver.is_matrix))
            if not driver.is_matrix:
                table.item(row, 6).setToolTip(_weight_tip(DRIVER_COLUMNS[6]))
        table.resizeColumnsToContents()

    def _show_driven(self, definition: Definition | None) -> None:
        """Fills the Driven table with each pose's moves and values in *definition*."""
        table = self.driven_table
        columns: list[DrivenColumn] = []
        labels = ["Pose"]
        poses: Sequence[Pose] = ()
        if definition is not None:
            poses = definition.poses
            for j, transform in enumerate(definition.transforms):
                for channel, name in enumerate(MOVE_CHANNELS):
                    columns.append(DrivenColumn("move", j, channel))
                    labels.append(f"{transform.node}.{name}")
            for k, value in enumerate(definition.values):
                columns.append(DrivenColumn("value", k))
                labels.append(value.plug)
        self._driven_columns = columns
        table.setColumnCount(len(labels))
        table.setHorizontalHeaderLabels(labels)
        table.setRowCount(len(poses))
        for row, pose in enumerate(poses):
            moves = [commands.move_channels(m) for m in pose.moves]
            table.setItem(row, 0, _item(pose.name))
            for column, driven in enumerate(columns, 1):
                if driven.kind == "move":
                    value = moves[driven.index][driven.channel]
                else:
                    value = pose.values[driven.index]
                table.setItem(row, column, _item(_text(value)))
        table.resizeColumnsToContents()

    def _show_options(self, definition: Definition | None) -> None:
        """Shows the options of *definition*, and its plots."""
        options = definition.options if definition else Options()
        enabled = definition is not None
        for widget in (
            self.kernel_box, self.automatic_box, self.radius_spin, self.mode_box,
            self.margin_spin, self.normalize_box, self.negative_box,
        ):  # fmt: skip
            widget.setEnabled(enabled)
        _choose(self.kernel_box, options.kernel)
        self.automatic_box.setChecked(options.radius is None)
        _choose(self.mode_box, options.mode)
        self.margin_spin.setValue(options.margin)
        _choose(self.normalize_box, options.normalize)
        self.negative_box.setChecked(not options.clamp_negative)
        radius = None
        if definition is not None:
            with contextlib.suppress(ValueError):
                radius = preview.radius(definition)
        if radius is not None:
            self.radius_spin.setValue(radius)
        self.radius_spin.setEnabled(enabled and options.radius is not None)
        self._fill_path(definition)
        self._show_plots()

    @staticmethod
    def _curve_picture(
        kernel: ref.Kernel, radius: float | None, between: Dot | None = None
    ) -> Picture:
        """Returns the falloff curves, *kernel* in front, over 0 to twice the radius.

        Args:
            kernel: The curve in use.
            radius: Labels the distances; None leaves them in radii.
            between: Where the To pose lies, seen from the From pose.
        """
        curves = preview.curves()
        others = [y for name, y in curves.items() if name != kernel]
        lines = [Line(preview.CURVE_X, curves[kernel], label=kernel.title())]
        lines += [
            Line(preview.CURVE_X, y, faint=True, label="" if n else "Other Curves")
            for n, y in enumerate(others)
        ]
        if radius is None:
            x_ticks = (Tick(0.0, "0"), Tick(1.0, "Radius"))
        else:
            x_ticks = tuple(
                Tick(k / 2, f"{round(radius * k / 2, 1):g}") for k in range(5)
            )
        return Picture(
            tuple(lines),
            x_range=(0.0, 2.0),
            y_range=(0.0, 1.0),
            x_step=0.25,
            y_step=0.125,
            x_ticks=x_ticks,
            y_ticks=(Tick(0.0, "0"), Tick(0.5, "0.5"), Tick(1.0, "1")),
            x_title="Distance from the pose",
            y_title="Influence",
            marks=(Tick(1.0, "Radius"),),
            dots=() if between is None else (between,),
        )

    def _fill_path(self, definition: Definition | None) -> None:
        """Lists the poses in From and To, keeping the poses they showed."""
        names = [p.name for p in definition.poses] if definition else []
        start = self.from_box.currentText()
        end = self.to_box.currentText()
        if start not in names:
            start = names[0] if names else ""
        if end not in names or end == start:
            others = [n for n in names if n != start]
            end = self._pose if self._pose in others else (others or [""])[0]
        size = self.fontMetrics().height() // 2
        for box, name, colour in (
            (self.from_box, start, FIRST_COLOUR),
            (self.to_box, end, SECOND_COLOUR),
        ):
            box.clear()
            for pose in names:
                box.addItem(_swatch(colour, size), pose)
            box.setCurrentIndex(box.findText(name))

    def _path_changed(self, _index: int) -> None:
        """Draws the plots again for the From and To picked."""
        if not self._loading:
            self._show_plots()

    def _show_plots(self) -> None:
        """Draws the curves, the To pose on them, and the weights from From to To."""
        definition = self._shown
        options = definition.options if definition else Options()
        first = self.from_box.currentIndex()
        second = self.to_box.currentIndex()
        radius = between = None
        path = Picture()
        if definition is not None:
            with contextlib.suppress(ValueError, np.linalg.LinAlgError):
                radius = preview.radius(definition)
                if min(first, second) >= 0 and first != second:
                    path = self._path_picture(definition, first, second)
                    away = preview.distance(definition, first, second) / radius
                    names = [p.name for p in definition.poses]
                    influence = float(ref.falloff(options.kernel, np.array([away]))[0])
                    between = Dot(
                        away,
                        influence,
                        SECOND_COLOUR,
                        f"{names[first]} → {names[second]}",
                    )
        self.curve_plot.show_picture(
            self._curve_picture(options.kernel, radius, between)
        )
        self.path_plot.show_picture(path)
        self.update_marker()

    def update_marker(self) -> None:
        """Marks where the drivers are now on the plotted path, in the Options tab."""
        if (
            not Shiboken.isValid(self)
            or not self.isVisible()
            or self.tabs.currentIndex() != OPTIONS_TAB
        ):
            return
        definition = self._shown
        first = self.from_box.currentIndex()
        second = self.to_box.currentIndex()
        where = None
        if definition is not None and min(first, second) >= 0 and first != second:
            with contextlib.suppress(RuntimeError, ValueError):
                drivers = {d.name: commands.driver_state(d) for d in definition.drivers}
                where = preview.locate(definition, first, second, drivers)
        self.path_plot.show_marker(where, "Drivers")

    @staticmethod
    def _path_picture(definition: Definition, first: int, second: int) -> Picture:
        """Returns every pose's weight while the drivers go from *first* to *second*.

        Raises:
            ValueError: When the path cannot be computed.
            LinAlgError: When the pose table has no solution.
        """
        shown = preview.path(definition, first, second)
        t = preview.PATH_T
        names = [p.name for p in definition.poses]
        start, end = names[first], names[second]
        others = [k for k in range(len(names)) if k not in (first, second)]
        lines = [
            Line(t, shown.weights[:, first], FIRST_COLOUR, label=start),
            Line(t, shown.weights[:, second], SECOND_COLOUR, label=end),
        ]
        lines += [
            Line(t, shown.weights[:, k], faint=True, label="" if n else "Other Poses")
            for n, k in enumerate(others)
        ]
        lines.append(Line(t, shown.total, dashed=True, label="Total"))
        step = 0.25
        lowest = min(float(shown.weights.min()), float(shown.total.min()))
        highest = max(float(shown.weights.max()), float(shown.total.max()))
        low = min(-PATH_EDGE, np.floor(lowest / step) * step)
        high = max(1.0 + PATH_EDGE, np.ceil(highest / step) * step)
        at_start = int(np.argmin(np.abs(t)))
        at_end = int(np.argmin(np.abs(t - 1.0)))
        return Picture(
            tuple(lines),
            x_range=(-PATH_EDGE, 1.0 + PATH_EDGE),
            y_range=(float(low), float(high)),
            x_step=step,
            y_step=step,
            x_ticks=(Tick(0.0, start), Tick(0.5, "Halfway"), Tick(1.0, end)),
            y_ticks=tuple(
                Tick(y, _text(y)) for y in np.arange(low, high + 1e-9, 2 * step)
            ),
            x_title=f"Drivers going from {start} to {end}",
            y_title="Weight",
            bands=(
                Band(-PATH_EDGE, 0.0, f"Before {start}"),
                Band(1.0, 1.0 + PATH_EDGE, f"Past {end}"),
            ),
            dots=(
                Dot(0.0, float(shown.weights[at_start, first]), FIRST_COLOUR),
                Dot(1.0, float(shown.weights[at_end, second]), SECOND_COLOUR),
            ),
        )

    # ---------------------------------------------------------------------------
    # Menus
    # ---------------------------------------------------------------------------

    def pose_menu(
        self, row: int | None, table: QtWidgets.QTableWidget | None = None
    ) -> QtWidgets.QMenu:
        """Returns the right-click menu of the pose at *row*, or of the table for None.

        *table* is the Poses table unless given; Rename edits the name there.
        """
        menu = QtWidgets.QMenu(self)
        pose = self._pose_name(row)
        names = table or self.pose_table
        if pose is not None and row is not None:
            self._action(menu, "Go To Pose", lambda: self.go_to_pose(pose))
            self._action(menu, "Update Pose", lambda: self.update_pose(pose))
            self._action(menu, "Update Driven", lambda: self.update_driven(pose))
            self._separator(menu)
            self._action(menu, "Rename", lambda: self._edit(names, row, 0))
            self._action(menu, "Delete", lambda: self.remove_pose(pose))
            self._separator(menu)
        self._action(menu, "Add Pose", self.add_pose)
        return menu

    def _driven_pose_menu(self, row: int | None) -> QtWidgets.QMenu:
        """Returns the right-click menu of the pose at *row* of the Driven table."""
        return self.pose_menu(row, self.driven_table)

    def driver_menu(self, row: int | None) -> QtWidgets.QMenu:
        """Returns the right-click menu of the driver at *row*, or of the table."""
        menu = QtWidgets.QMenu(self)
        driver = self._driver_at(row)
        if driver is not None:
            node = driver.plug.split(".")[0]
            self._action(menu, "Select", lambda: session.select(node))
            self._action(menu, "Remove", lambda: self.remove_driver(driver.name))
            self._separator(menu)
        self._action(menu, "Add Selected Transforms", self.add_drivers)
        self._action(menu, "Add Channel Box Attributes", self.add_number_drivers)
        return menu

    def driven_menu(self, column: int | None) -> QtWidgets.QMenu:
        """Returns the right-click menu of the driven at *column*, or of none."""
        menu = QtWidgets.QMenu(self)
        item = self._driven_at(column)
        if item is not None:
            node = item.split(".")[0]
            self._action(menu, "Select", lambda: session.select(node))
            self._action(menu, "Remove", lambda: self.remove_driven(item))
            self._separator(menu)
        self._action(menu, "Add Selected Transforms", self.add_transforms)
        self._action(menu, "Add Channel Box Attributes", self.add_values)
        return menu

    def _edit(self, table: QtWidgets.QTableWidget, row: int, column: int) -> None:
        """Starts editing the cell at *row* and *column* of *table*."""
        table.editItem(table.item(row, column))

    def _pose_name(self, row: int | None) -> str | None:
        """Returns the name of the pose at *row*, or None."""
        if self._shown is None or row is None or row >= len(self._shown.poses):
            return None
        return self._shown.poses[row].name

    def _driver_at(self, row: int | None) -> Driver | None:
        """Returns the driver at *row*, or None."""
        if self._shown is None or row is None or row >= len(self._shown.drivers):
            return None
        return self._shown.drivers[row]

    def _driven_at(self, column: int | None) -> str | None:
        """Returns the transform or the plug of the Driven column *column*, or None."""
        if (
            self._shown is None
            or column is None
            or not 0 < column <= len(self._driven_columns)
        ):
            return None
        driven = self._driven_columns[column - 1]
        if driven.kind == "move":
            return self._shown.transforms[driven.index].node
        return self._shown.values[driven.index].plug

    # ---------------------------------------------------------------------------
    # Actions
    # ---------------------------------------------------------------------------

    def _run(self, action: Callable[[], object]) -> None:
        """Runs one action; shows its error instead of raising, and refreshes."""
        try:
            action()
            self.status.setText("")
        except (ValueError, KeyError, RuntimeError) as error:
            self.status.setText(f"<font color='{WARNING_COLOUR}'>{error}</font>")
            logger.warning("poseRBF: %s", error)
        except Exception as error:
            self.status.setText(
                f"<font color='{ERROR_COLOUR}'>{type(error).__name__}: {error}</font>"
            )
            logger.exception("poseRBF failed")
        self.refresh()

    def _need_rbf(self) -> str:
        """Returns the RBF shown.

        Raises:
            ValueError: When none is shown.
        """
        if not self.rbf:
            raise ValueError("create or pick an RBF first")
        return self.rbf

    def create_rbf(self) -> None:
        """Creates an RBF driven by the selected transforms or attributes."""
        selection = session.selected_transforms()
        drivers = session.selected_attributes() or selection
        if not drivers:
            raise ValueError("select the driver transforms (or Channel Box attributes)")
        rbf = commands.create(self.name_edit.text().strip() or "poseRBF", drivers)
        self.refresh()
        self.rbf_box.setCurrentText(rbf)

    def delete_rbf(self) -> None:
        """Deletes the RBF shown."""
        commands.delete(self._need_rbf())

    def add_pose(self) -> None:
        """Adds a pose at the drivers' current state and selects it."""
        self._pose = commands.add_pose(self._need_rbf())

    def go_to_pose(self, pose: str) -> None:
        """Puts the drivers in *pose*."""
        commands.go_to_pose(self._need_rbf(), pose)

    def update_pose(self, pose: str) -> None:
        """Moves *pose* to where the drivers are now; what it asks for is kept."""
        commands.update_pose(self._need_rbf(), pose)

    def update_driven(self, pose: str) -> None:
        """Stores in *pose* where the driven transforms are now."""
        commands.update_driven(self._need_rbf(), pose)

    def remove_pose(self, pose: str) -> None:
        """Removes *pose*."""
        commands.remove_pose(self._need_rbf(), pose)

    def add_drivers(self) -> None:
        """Adds the selected transforms as drivers."""
        rbf = self._need_rbf()
        nodes = session.selected_transforms()
        if not nodes:
            raise ValueError("select the driver transforms")
        for node in nodes:
            commands.add_driver(rbf, node)

    def add_number_drivers(self) -> None:
        """Adds the Channel Box's selected attributes as number drivers."""
        rbf = self._need_rbf()
        for plug in session.selected_attributes(required=True):
            commands.add_driver(rbf, plug)

    def remove_driver(self, driver: str) -> None:
        """Removes *driver*."""
        commands.remove_driver(self._need_rbf(), driver)

    def add_transforms(self) -> None:
        """Adds the selected transforms as driven."""
        nodes = session.selected_transforms()
        if not nodes:
            raise ValueError("select the transforms to drive")
        commands.add_driven(self._need_rbf(), transforms=nodes)

    def add_values(self) -> None:
        """Adds the Channel Box's selected attributes as driven values."""
        commands.add_driven(
            self._need_rbf(), values=session.selected_attributes(required=True)
        )

    def remove_driven(self, item: str) -> None:
        """Stops driving *item*, a transform or a plug."""
        commands.remove_driven(self._need_rbf(), [item])

    # ---------------------------------------------------------------------------
    # Edits in place
    # ---------------------------------------------------------------------------

    def _pose_cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        """Renames the pose whose name *item* holds, once edited."""
        if self._loading or self._shown is None:
            return
        if self._pose_columns[item.column()].kind == "name":
            self._rename(self._shown.poses[item.row()].name, item.text())

    def _driver_cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        """Sets the factor of the driver *item* belongs to, once edited."""
        if self._loading or self._shown is None or item.column() in (0, 5):
            return
        driver = self._shown.drivers[item.row()]
        field = "number" if item.column() == 6 else FACTOR_FIELDS[item.column() - 1]
        rbf = self.rbf
        text = item.text()
        self._run(
            lambda: commands.set_driver(rbf, driver.name, **{field: _number(text)})
        )

    def _rename(self, pose: str, text: str) -> None:
        """Renames *pose* to *text*; the selection follows it."""
        rbf = self.rbf

        def rename() -> None:
            name = text.strip()
            commands.rename_pose(rbf, pose, name)
            if self._pose == pose:
                self._pose = name

        self._run(rename)

    def _driven_cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        """Stores the pose name, move channel or value *item* holds, once edited."""
        if self._loading or self._shown is None:
            return
        definition = self._shown
        pose = definition.poses[item.row()]
        rbf = self.rbf
        text = item.text()
        if item.column() == 0:
            self._rename(pose.name, text)
            return
        driven = self._driven_columns[item.column() - 1]

        def set_cell() -> None:
            number = _number(text)
            if driven.kind == "value":
                values = list(pose.values)
                values[driven.index] = number
                commands.set_pose_values(rbf, pose.name, values)
                return
            channels = list(commands.move_channels(pose.moves[driven.index]))
            channels[driven.channel] = number
            node = definition.transforms[driven.index].node
            commands.set_pose_move(
                rbf, pose.name, node, channels[0:3], channels[3:6], channels[6:9]
            )

        self._run(set_cell)

    def _axis_picked(self, driver: str, box: QtWidgets.QComboBox, _index: int) -> None:
        """Sets the axis of *driver* to the entry picked in *box*."""
        rbf = self.rbf
        self._run(lambda: commands.set_driver(rbf, driver, axis=box.currentData()))

    def _set_option(self, **change: object) -> None:
        """Changes options of the RBF shown, unless the window is filling its fields."""
        if self._loading or not self.rbf:
            return
        rbf = self.rbf
        self._run(lambda: commands.set_options(rbf, **change))

    def _automatic_toggled(self, automatic: bool) -> None:
        """Switches between the automatic radius and the one the field shows."""
        self._set_option(radius=None if automatic else self.radius_spin.value())

    def _radius_changed(self, value: float) -> None:
        """Sets the radius typed, unless it is automatic."""
        if not self.automatic_box.isChecked():
            self._set_option(radius=value)

    def _margin_changed(self, value: float) -> None:
        """Sets the regularization typed."""
        self._set_option(margin=value)

    def _negative_toggled(self, allowed: bool) -> None:
        """Allows negative weights, or clamps them at 0."""
        self._set_option(clamp_negative=not allowed)
