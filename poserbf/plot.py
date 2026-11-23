"""A small square plot for the Options tab, drawn with the window's palette.

A plot shows one :class:`Picture` on a square grid: its coordinate axes (the lines
x = 0 and y = 0, with an arrow at their positive end) wherever they cross the grid,
labels along both axes, a title over each, a legend of the lines that have a label,
shaded bands named at their foot, dashed marks and labelled dots. A marker, a
vertical line that can move on its own, shows where something is now. Text is drawn
in the palette's text colours; a line's colour only marks the line, its dots and its
swatch in the legend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import reference as ref

Colour: TypeAlias = tuple[int, int, int]
FIRST_COLOUR: Final[Colour] = (57, 135, 229)
"""The first pose's line (blue)."""
SECOND_COLOUR: Final[Colour] = (217, 89, 38)
"""The second pose's line (orange); both pass the colour-blind checks on Maya's grey."""
SIDE_LINES: Final[float] = 20.0
"""The side of the square, in lines of text."""
SWATCH_CHARACTERS: Final[int] = 3
"""How long a legend swatch is, in characters."""
DOT_RADIUS: Final[float] = 4.0
"""In pixels."""
ARROW: Final[float] = 6.0
"""Length of an axis arrow, in pixels."""


@dataclass(frozen=True, slots=True, eq=False)
class Line:
    """One series of the plot.

    Attributes:
        x: Positions along the x axis.
        y: Values at those positions.
        colour: RGB; None draws it in the text colour.
        faint: Drawn thin and dim, behind the others.
        dashed: Drawn dashed.
        label: Its entry in the legend; "" leaves it out.
    """

    x: ref.FloatArray
    y: ref.FloatArray
    colour: Colour | None = None
    faint: bool = False
    dashed: bool = False
    label: str = ""


@dataclass(frozen=True, slots=True)
class Tick:
    """A label at *at* along an axis; for a mark, its label at the top."""

    at: float
    label: str


@dataclass(frozen=True, slots=True)
class Band:
    """A shaded stretch of the x axis, from *start* to *end*, named at its foot."""

    start: float
    end: float
    label: str


@dataclass(frozen=True, slots=True)
class Dot:
    """A point drawn in *colour* (None: the text colour), with *label* on its right."""

    x: float
    y: float
    colour: Colour | None = None
    label: str = ""


@dataclass(frozen=True, slots=True)
class Picture:
    """Everything one plot shows but its marker.

    Attributes:
        lines: Series, drawn in order (faint ones first).
        x_range: Left and right ends of the x axis.
        y_range: Bottom and top of the y axis.
        x_step: Distance between the grid's vertical lines.
        y_step: Distance between the grid's horizontal lines.
        x_ticks: Labels under the grid.
        y_ticks: Labels left of the grid.
        x_title: What the x axis is, under its labels.
        y_title: What the y axis is, above it.
        bands: Shaded stretches of the x axis.
        marks: Dashed vertical lines, labelled at their top.
        dots: Points over the lines.
    """

    lines: tuple[Line, ...] = ()
    x_range: tuple[float, float] = (0.0, 1.0)
    y_range: tuple[float, float] = (0.0, 1.0)
    x_step: float = 0.25
    y_step: float = 0.25
    x_ticks: tuple[Tick, ...] = ()
    y_ticks: tuple[Tick, ...] = (Tick(0.0, "0"), Tick(1.0, "1"))
    x_title: str = ""
    y_title: str = ""
    bands: tuple[Band, ...] = ()
    marks: tuple[Tick, ...] = ()
    dots: tuple[Dot, ...] = ()


def _steps(start: float, end: float, step: float) -> list[float]:
    """Returns the multiples of *step* from *start* to *end*, both included."""
    first = int(np.ceil(start / step - 1e-9))
    last = int(np.floor(end / step + 1e-9))
    return [float(k * step) for k in range(first, last + 1)]


class Plot(QtWidgets.QWidget):
    """A square plot of one :class:`Picture`, with a marker over it."""

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        """Creates an empty plot, ``SIDE_LINES`` lines of text square."""
        super().__init__(parent)
        self.picture = Picture()
        self.marker: float | None = None
        """Where the marker is on the x axis; None hides it."""
        self.marker_label = ""
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed
        )

    def show_picture(self, picture: Picture) -> None:
        """Replaces what the plot shows; the marker stays where it is."""
        self.picture = picture
        self.updateGeometry()
        self.update()

    def show_marker(self, x: float | None, label: str = "") -> None:
        """Moves the marker to *x*, named *label* at its top; None hides it."""
        if (x, label) == (self.marker, self.marker_label):
            return
        self.marker, self.marker_label = x, label
        self.update()

    def _margins(self) -> tuple[float, float, float, float]:
        """Returns the left, top, right and bottom margins around the square."""
        metrics = self.fontMetrics()
        line = metrics.height()
        widest = max(
            (metrics.horizontalAdvance(t.label) for t in self.picture.y_ticks),
            default=0,
        )
        return widest + line * 0.8, line * 2.6, line * 1.2, line * 2.6

    def _side(self) -> float:
        """Returns the side of the square, in pixels."""
        return self.fontMetrics().height() * SIDE_LINES

    def sizeHint(self) -> QtCore.QSize:
        """Returns the size of the square and its margins."""
        left, top, right, bottom = self._margins()
        side = self._side()
        return QtCore.QSize(round(left + side + right), round(top + side + bottom))

    def minimumSizeHint(self) -> QtCore.QSize:
        """Returns the size hint: the square does not shrink."""
        return self.sizeHint()

    @staticmethod
    def _colour(colour: Colour | None, text: QtGui.QColor) -> QtGui.QColor:
        """Returns *colour* as a Qt colour, or the text colour for None."""
        return QtGui.QColor(*colour) if colour else QtGui.QColor(text)

    def _pen(self, line: Line, text: QtGui.QColor) -> QtGui.QPen:
        """Returns the pen that draws *line*."""
        colour = self._colour(line.colour, text)
        if line.faint:
            colour.setAlphaF(0.5)
        pen = QtGui.QPen(colour, 1.0 if line.faint else 2.0)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        if line.dashed:
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        return pen

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Draws the picture and the marker over it."""
        del event
        picture = self.picture
        palette = self.palette()
        text = palette.color(QtGui.QPalette.ColorRole.Text)
        muted = palette.color(QtGui.QPalette.ColorRole.PlaceholderText)
        dim = palette.color(QtGui.QPalette.ColorRole.Mid)
        base = palette.color(QtGui.QPalette.ColorRole.Base)
        metrics = self.fontMetrics()
        line_height = metrics.height()
        gap = metrics.horizontalAdvance("0")
        left, top, _right, _bottom = self._margins()
        side = self._side()
        area = QtCore.QRectF(left, top, side, side)
        (x0, x1), (y0, y1) = picture.x_range, picture.y_range
        width = x1 - x0 or 1.0
        height = y1 - y0 or 1.0

        def at(x: float, y: float) -> QtCore.QPointF:
            """Returns the point of the square at *x*, *y*."""
            return QtCore.QPointF(
                area.left() + (x - x0) / width * area.width(),
                area.bottom() - (y - y0) / height * area.height(),
            )

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        def write(
            rect: QtCore.QRectF, flags: QtCore.Qt.AlignmentFlag, words: str
        ) -> None:
            """Writes *words* in *rect*."""
            painter.drawText(rect, flags, words)

        align = QtCore.Qt.AlignmentFlag
        painter.setPen(muted)
        title_row = QtCore.QRectF(0, 0, self.width(), line_height * 1.2)
        write(
            title_row.adjusted(gap, 0, 0, 0),
            align.AlignLeft | align.AlignVCenter,
            picture.y_title,
        )
        legend_row = title_row.translated(0, line_height * 1.2)
        swatch = gap * SWATCH_CHARACTERS
        x = area.right()
        for item in reversed([item for item in picture.lines if item.label]):
            words = metrics.horizontalAdvance(item.label)
            x -= words
            painter.setPen(text)
            write(
                QtCore.QRectF(x, legend_row.top(), words, legend_row.height()),
                align.AlignVCenter,
                item.label,
            )
            x -= gap + swatch
            painter.setPen(self._pen(item, text))
            middle = legend_row.center().y()
            painter.drawLine(
                QtCore.QPointF(x, middle), QtCore.QPointF(x + swatch, middle)
            )
            x -= 2 * gap

        painter.fillRect(area, base)
        shade = QtGui.QColor(base).darker(125)
        for band in picture.bands:
            rect = QtCore.QRectF(at(band.start, y1), at(band.end, y0)).intersected(area)
            painter.fillRect(rect, shade)
            painter.setPen(muted)
            write(
                rect.adjusted(0, 0, 0, -line_height * 0.2),
                align.AlignHCenter | align.AlignBottom,
                band.label,
            )
        painter.setPen(QtGui.QPen(dim, 1.0))
        for x in _steps(x0, x1, picture.x_step):
            painter.drawLine(at(x, y0), at(x, y1))
        for y in _steps(y0, y1, picture.y_step):
            painter.drawLine(at(x0, y), at(x1, y))

        painter.setPen(muted)
        for tick in picture.y_ticks:
            if y0 - 1e-9 <= tick.at <= y1 + 1e-9:
                point = at(x0, tick.at)
                write(
                    QtCore.QRectF(
                        0, point.y() - line_height / 2, left - gap, line_height
                    ),
                    align.AlignRight | align.AlignVCenter,
                    tick.label,
                )
        below = area.bottom() + line_height * 0.2
        for tick in picture.x_ticks:
            if x0 - 1e-9 <= tick.at <= x1 + 1e-9:
                point = at(tick.at, y0)
                words = metrics.horizontalAdvance(tick.label)
                start = min(max(point.x() - words / 2, 0.0), self.width() - words)
                painter.setPen(text)
                write(
                    QtCore.QRectF(start, below, words, line_height),
                    align.AlignCenter,
                    tick.label,
                )
        painter.setPen(muted)
        write(
            QtCore.QRectF(area.left(), below + line_height, area.width(), line_height),
            align.AlignHCenter | align.AlignVCenter,
            picture.x_title,
        )

        axis = QtGui.QPen(text, 1.5)
        painter.setPen(axis)
        painter.setBrush(text)
        if y0 <= 0.0 <= y1:
            start, end = at(x0, 0.0), at(x1, 0.0)
            painter.drawLine(start, end - QtCore.QPointF(ARROW, 0))
            painter.drawPolygon(
                QtGui.QPolygonF(
                    [
                        end,
                        end + QtCore.QPointF(-ARROW, -ARROW / 2),
                        end + QtCore.QPointF(-ARROW, ARROW / 2),
                    ]
                )
            )
        if x0 <= 0.0 <= x1:
            start, end = at(0.0, y0), at(0.0, y1)
            painter.drawLine(start, end + QtCore.QPointF(0, ARROW))
            painter.drawPolygon(
                QtGui.QPolygonF(
                    [
                        end,
                        end + QtCore.QPointF(-ARROW / 2, ARROW),
                        end + QtCore.QPointF(ARROW / 2, ARROW),
                    ]
                )
            )
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        painter.setClipRect(area.adjusted(-2, -2, 2, 2))
        mark_pen = QtGui.QPen(muted, 1.0)
        mark_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        for mark in picture.marks:
            painter.setPen(mark_pen)
            painter.drawLine(at(mark.at, y0), at(mark.at, y1))
            painter.setPen(muted)
            point = at(mark.at, y1)
            write(
                QtCore.QRectF(
                    point.x() + gap / 2,
                    point.y() + line_height * 0.2,
                    area.right() - point.x(),
                    line_height,
                ),
                align.AlignLeft | align.AlignTop,
                mark.label,
            )
        for item in sorted(picture.lines, key=lambda item: not item.faint):
            painter.setPen(self._pen(item, text))
            painter.drawPolyline(
                QtGui.QPolygonF(
                    [
                        at(float(x), float(y))
                        for x, y in zip(item.x, item.y, strict=True)
                    ]
                )
            )
        for dot in picture.dots:
            self._dot(painter, at(dot.x, dot.y), self._colour(dot.colour, text), base)
            if dot.label:
                point = at(dot.x, dot.y)
                painter.setPen(text)
                write(
                    QtCore.QRectF(
                        point.x() + gap,
                        point.y() - line_height * 1.1,
                        area.right() - point.x(),
                        line_height,
                    ),
                    align.AlignLeft | align.AlignVCenter,
                    dot.label,
                )

        if self.marker is not None and x0 <= self.marker <= x1:
            painter.setPen(QtGui.QPen(text, 1.5))
            painter.drawLine(at(self.marker, y0), at(self.marker, y1))
            point = at(self.marker, y1)
            painter.setPen(text)
            write(
                QtCore.QRectF(
                    point.x() + gap / 2,
                    point.y() + line_height * 1.2,
                    area.right() - point.x(),
                    line_height,
                ),
                align.AlignLeft | align.AlignTop,
                self.marker_label,
            )
            for item in picture.lines:
                if item.colour is not None:
                    y = float(np.interp(self.marker, item.x, item.y))
                    self._dot(
                        painter,
                        at(self.marker, y),
                        self._colour(item.colour, text),
                        base,
                    )
        painter.end()

    @staticmethod
    def _dot(
        painter: QtGui.QPainter,
        point: QtCore.QPointF,
        colour: QtGui.QColor,
        ring: QtGui.QColor,
    ) -> None:
        """Draws a dot of *colour* at *point*, ringed in *ring*."""
        painter.setPen(QtGui.QPen(ring, 2.0))
        painter.setBrush(colour)
        painter.drawEllipse(point, DOT_RADIUS, DOT_RADIUS)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
