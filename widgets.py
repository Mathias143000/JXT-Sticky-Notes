"""Small custom-painted widgets shared by the notes and the settings window."""
from __future__ import annotations

from PySide6.QtCore import (
    Property, QAbstractAnimation, QEasingCurve, QEvent, QObject, QPointF,
    QPropertyAnimation, QRectF, Qt, Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QColorDialog, QHBoxLayout, QPushButton, QWidget

from themes import ACCENT, NOTE_COLORS, luminance


class IconButton(QAbstractButton):
    """Flat vector icon button (plus / close / menu / pin), tinted to match the note."""

    def __init__(self, kind: str, tip: str = "", parent=None):
        super().__init__(parent)
        self.kind = kind
        self._color = QColor("#000000")
        self._active = False
        self._hover = False
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setFocusPolicy(Qt.NoFocus)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._hover:
            bg = QColor(self._color)
            bg.setAlpha(36)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        col = QColor(self._color)
        col.setAlpha(255 if (self._hover or self._active) else 165)
        p.setPen(QPen(col, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        cx, cy = self.width() / 2, self.height() / 2
        if self.kind == "plus":
            p.drawLine(QPointF(cx - 5, cy), QPointF(cx + 5, cy))
            p.drawLine(QPointF(cx, cy - 5), QPointF(cx, cy + 5))
        elif self.kind == "close":
            d = 4.5
            p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
            p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))
        elif self.kind == "menu":
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            for dx in (-5, 0, 5):
                p.drawEllipse(QPointF(cx + dx, cy), 1.7, 1.7)
        elif self.kind == "back":
            p.drawLine(QPointF(cx + 5, cy), QPointF(cx - 5, cy))
            p.drawLine(QPointF(cx - 5, cy), QPointF(cx, cy - 5))
            p.drawLine(QPointF(cx - 5, cy), QPointF(cx, cy + 5))
        elif self.kind == "pin":
            p.translate(cx, cy)
            p.rotate(35)
            if self._active:
                p.setBrush(col)
            p.drawRoundedRect(QRectF(-3.2, -7, 6.4, 8.5), 1.6, 1.6)
            p.drawLine(QPointF(-5, 1.5), QPointF(5, 1.5))
            p.drawLine(QPointF(0, 1.5), QPointF(0, 7))
        elif self.kind == "search":
            p.drawEllipse(QRectF(cx - 6, cy - 7, 10, 10))
            p.drawLine(QPointF(cx + 2, cy + 1), QPointF(cx + 7, cy + 6))
        elif self.kind == "settings":
            p.drawEllipse(QPointF(cx, cy), 3, 3)
            p.drawEllipse(QPointF(cx, cy), 7, 7)
            p.translate(cx, cy)
            for _ in range(8):
                p.drawLine(QPointF(0, -7), QPointF(0, -9))
                p.rotate(45)
        elif self.kind == "list":
            for dy in (-5, 0, 5):
                p.drawPoint(QPointF(cx - 7, cy + dy))
                p.drawLine(QPointF(cx - 3, cy + dy), QPointF(cx + 7, cy + dy))
        elif self.kind == "image":
            p.drawRect(QRectF(cx - 8, cy - 6, 16, 12))
            p.drawEllipse(QPointF(cx + 3, cy - 2), 1.3, 1.3)
            p.drawLine(QPointF(cx - 8, cy + 4), QPointF(cx - 3, cy - 1))
            p.drawLine(QPointF(cx - 3, cy - 1), QPointF(cx + 4, cy + 6))


class ListButton(IconButton):
    """Distinguish a single list click from a double checklist click."""

    single_clicked = Signal()
    double_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__("list", "Список · двойной клик: чек-лист", parent)
        self._double_release = False
        self.clicked.connect(self.single_clicked.emit)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._double_release = True
            self.setDown(False)
            self.double_clicked.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        self._double_release = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._double_release:
            self._double_release = False
            self.setDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SmoothScroll(QObject):
    """Interpolate mouse-wheel notches; preserve native touchpad pixel deltas."""

    def __init__(self, area):
        super().__init__(area)
        self.area = area
        self.bar = area.verticalScrollBar()
        self.animation = QPropertyAnimation(self.bar, b"value", self)
        self.animation.setDuration(170)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.target = self.bar.value()
        self.bar.sliderPressed.connect(self.animation.stop)
        self.bar.actionTriggered.connect(lambda _: self.animation.stop())
        self.bar.rangeChanged.connect(lambda *_: self.animation.stop())
        area.viewport().installEventFilter(self)
        area.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            self.animation.stop()
            return False
        if event.type() != QEvent.Wheel or event.modifiers() & Qt.ControlModifier:
            return False
        if not event.angleDelta().y() and not event.pixelDelta().y():
            return False
        if self.bar.maximum() <= self.bar.minimum():
            return False
        if event.pixelDelta().y():
            self.animation.stop()
            self.bar.setValue(self.bar.value() - event.pixelDelta().y())
        else:
            start = self.bar.value()
            target = self.target if self.animation.state() == QAbstractAnimation.Running else start
            distance = max(36, self.bar.singleStep() * 3)
            self.target = max(self.bar.minimum(), min(self.bar.maximum(),
                round(target - event.angleDelta().y() / 120 * distance)))
            self.animation.stop()
            self.animation.setStartValue(start)
            self.animation.setEndValue(self.target)
            self.animation.start()
        event.accept()
        return True


class SaveIndicator(QWidget):
    """A short vector check animation, shown only after a successful disk write."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 22)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._phase = 1.0
        self.color = QColor("#437A46")
        self.state = "clean"
        self.animation = QPropertyAnimation(self, b"phase", self)
        self.animation.setDuration(1250)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)

    def _get_phase(self):
        return self._phase

    def _set_phase(self, value):
        self._phase = value
        self.update()

    phase = Property(float, _get_phase, _set_phase)

    def pending(self):
        self.animation.stop()
        self.state = "pending"
        self.setToolTip("Сохранение…")
        self.update()

    def saved(self):
        self.state = "saved"
        self.setToolTip("Сохранено")
        self.animation.stop()
        self.animation.start()

    def failed(self):
        self.animation.stop()
        self.state = "error"
        self.setToolTip("Не удалось сохранить")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.state == "error":
            painter.setPen(QPen(QColor("#B83E3E"), 1.6))
            painter.drawLine(10, 5, 10, 12)
            painter.drawPoint(10, 16)
        elif self.state == "saved" and self._phase < 1:
            painter.setOpacity(min(1.0, (1 - self._phase) / .22))
            painter.setPen(QPen(self.color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            progress = min(1.0, self._phase / .18)
            a, b, c = QPointF(4, 11), QPointF(8, 15), QPointF(16, 6)
            if progress < .35:
                painter.drawLine(a, a + (b - a) * (progress / .35))
            else:
                painter.drawLine(a, b)
                painter.drawLine(b, b + (c - b) * ((progress - .35) / .65))


class ToggleSwitch(QAbstractButton):
    """Animated on/off switch."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def set_silent(self, on: bool) -> None:
        self.blockSignals(True)
        self.setChecked(bool(on))
        self.blockSignals(False)
        self._pos = 1.0 if on else 0.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        off, on = QColor("#3A3F4B"), QColor(ACCENT)
        t = self._pos
        bg = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(3 + t * (self.width() - 24), 3, 18, 18))


class Swatch(QAbstractButton):
    def __init__(self, color: str, name: str, d: int = 22, parent=None):
        super().__init__(parent)
        self.color = color
        self.selected = False
        self.setFixedSize(d + 8, d + 8)
        self.setToolTip(name)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        p.setPen(QPen(QColor(0, 0, 0, 70), 1))
        p.setBrush(QColor(self.color))
        p.drawEllipse(r)
        if self.selected:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawEllipse(r.adjusted(-3, -3, 3, 3))


class SwatchRow(QWidget):
    """Row of preset note colors."""

    picked = Signal(str)

    def __init__(self, current: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._sw: list[Swatch] = []
        for name, hex_ in NOTE_COLORS:
            sw = Swatch(hex_, name)
            sw.clicked.connect(lambda _=False, h=hex_: self.picked.emit(h))
            lay.addWidget(sw)
            self._sw.append(sw)
        self.set_current(current)

    def set_current(self, color: str) -> None:
        for sw in self._sw:
            sw.selected = sw.color.lower() == (color or "").lower()
            sw.update()


class ColorChip(QPushButton):
    """Button showing a color; opens the system color picker on click."""

    picked = Signal(str)

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._c = color
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32)
        self.setMinimumWidth(112)
        self.clicked.connect(self._choose)
        self._refresh()

    def set_color(self, color: str) -> None:
        self._c = color
        self._refresh()

    def _refresh(self) -> None:
        fg = "#111111" if luminance(self._c) > 0.55 else "#FFFFFF"
        self.setText(self._c.upper())
        self.setStyleSheet(
            f"QPushButton{{background:{self._c};color:{fg};border:1px solid rgba(255,255,255,50);"
            f"border-radius:9px;padding:0 14px;font-weight:600;}}"
            f"QPushButton:disabled{{background:#2A2E38;color:#6C7282;border:1px solid #2E323C;}}"
        )

    def _choose(self) -> None:
        c = QColorDialog.getColor(QColor(self._c), self.window(), "Choose a color")
        if c.isValid():
            self.set_color(c.name())
            self.picked.emit(c.name())
