"""A single sticky note: frameless, draggable, resizable, fully themeable."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from PySide6.QtCore import (
    QEasingCurve, QEvent, QParallelAnimationGroup, QPoint, QPropertyAnimation,
    QRect, QRectF, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config import APP_NAME
from note_editor import NoteEditor
from themes import NOTE_COLORS, auto_text, is_dark, rgba
from widgets import IconButton, ListButton, SaveIndicator, SmoothScroll, Swatch

M = 12  # transparent margin around the card (room for the shadow)
HEADER_H = 40
MIN_W, MIN_H = 300, 150


def new_note_data(settings, x=None, y=None, text: str = "") -> dict:
    return {
        "id": uuid.uuid4().hex,
        "text": text,
        "x": x,
        "y": y,
        "w": int(settings["note_width"]) + 2 * M,
        "h": int(settings["note_height"]) + 2 * M,
        "color": None,  # None = follow the default color from Settings
        "on_top": bool(settings["always_on_top"]),
        "opacity": None,  # None = follow Settings
        "font_size": None,  # None = follow Settings
        "collapsed": False,
        "is_open": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


class Card(QFrame):
    """The note surface. Painted by hand so color/opacity changes always repaint fully."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bg = QColor("#FFF1A8")
        self.border = QColor(0, 0, 0, 22)
        self.radius = 14
        self.header_color = None
        self.header_height = 0

    def set_look(self, bg: QColor, border: QColor, radius: int) -> None:
        self.bg, self.border, self.radius = bg, border, radius
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), self.radius, self.radius)
        p.fillPath(path, self.bg)
        if self.header_color is not None and self.header_height:
            p.save()
            p.setClipPath(path)
            p.fillRect(QRectF(0, 0, self.width(), self.header_height), self.header_color)
            p.restore()
        p.setPen(QPen(self.border, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


class PaperWindow(QWidget):
    """Paint the shadow separately, without caching or resampling child text.

    QGraphicsDropShadowEffect on a container corrupts partial text repaints on
    translucent Windows windows at fractional DPI. Painting only the outer
    shadow here keeps editors, lists, and controls on Qt's normal paint path.
    """

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._shadow_enabled = True
        self._shadow_radius = 0
        self._resize_handles = []
        for edges, cursor in (
            (Qt.LeftEdge, Qt.SizeHorCursor), (Qt.RightEdge, Qt.SizeHorCursor),
            (Qt.TopEdge, Qt.SizeVerCursor), (Qt.BottomEdge, Qt.SizeVerCursor),
            (Qt.LeftEdge | Qt.TopEdge, Qt.SizeFDiagCursor),
            (Qt.RightEdge | Qt.BottomEdge, Qt.SizeFDiagCursor),
            (Qt.RightEdge | Qt.TopEdge, Qt.SizeBDiagCursor),
            (Qt.LeftEdge | Qt.BottomEdge, Qt.SizeBDiagCursor),
        ):
            self._resize_handles.append(ResizeHandle(self, edges, cursor))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        left, top, right, bottom = M - 4, M - 4, self.width() - M - 4, self.height() - M - 4
        rects = (
            QRect(left, top + 14, 8, max(0, bottom - top - 20)),
            QRect(right, top + 14, 8, max(0, bottom - top - 20)),
            QRect(left + 14, top, max(0, right - left - 20), 8),
            QRect(left + 14, bottom, max(0, right - left - 20), 8),
            QRect(left, top, 14, 14), QRect(right - 6, bottom - 6, 14, 14),
            QRect(right - 6, top, 14, 14), QRect(left, bottom - 6, 14, 14),
        )
        for handle, rect in zip(self._resize_handles, rects):
            handle.setGeometry(rect)
            handle.raise_()

    def set_shadow(self, enabled: bool, radius: int = 0) -> None:
        self._shadow_enabled = bool(enabled)
        self._shadow_radius = radius
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        # Clear the old alpha on every invalidated region, including old corners
        # left behind by collapse/expand, resizing, or changing corner radius.
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(event.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if not self._shadow_enabled:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(Qt.NoBrush)
        surface = QRectF(self.rect()).adjusted(M, M, -M, -M).translated(0, 2)
        for spread in range(M - 2, 0, -1):
            alpha = round(48 * (1 - spread / (M - 1)) ** 2)
            painter.setPen(QPen(QColor(0, 0, 0, alpha), 1.5))
            radius = self._shadow_radius + spread
            painter.drawRoundedRect(
                surface.adjusted(-spread, -spread, spread, spread), radius, radius)


class ResizeHandle(QWidget):
    def __init__(self, window, edges, cursor):
        super().__init__(window)
        self.edges = edges
        self.setCursor(cursor)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._drag = None

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        window = self.window()
        if window.windowHandle() and window.windowHandle().startSystemResize(self.edges):
            event.accept()
            return
        self._drag = (event.globalPosition().toPoint(), window.geometry())
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag and event.buttons() & Qt.LeftButton:
            origin, geometry = self._drag
            self.window().setGeometry(self.drag_geometry(geometry, event.globalPosition().toPoint() - origin))

    def drag_geometry(self, geometry, delta):
        result = QRect(geometry)
        minimum = self.window().minimumSize()
        if self.edges & Qt.LeftEdge:
            result.setLeft(min(geometry.left() + delta.x(), geometry.right() - minimum.width() + 1))
        if self.edges & Qt.RightEdge:
            result.setRight(max(geometry.right() + delta.x(), geometry.left() + minimum.width() - 1))
        if self.edges & Qt.TopEdge:
            result.setTop(min(geometry.top() + delta.y(), geometry.bottom() - minimum.height() + 1))
        if self.edges & Qt.BottomEdge:
            result.setBottom(max(geometry.bottom() + delta.y(), geometry.top() + minimum.height() - 1))
        return result

    def mouseReleaseEvent(self, event):
        self._drag = None


class HeaderBar(QWidget):
    """Top bar: drag to move, double-click to collapse."""

    double_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag: QPoint | None = None
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.double_clicked.emit()


class NoteWindow(PaperWindow):
    changed = Signal()
    content_changed = Signal()
    new_requested = Signal()
    delete_requested = Signal(object)
    duplicate_requested = Signal(object)
    list_requested = Signal()
    closed = Signal()

    def __init__(self, data: dict, settings):
        super().__init__()
        self.data = data
        self.s = settings
        self._loading = True
        self._hover = False
        self._menu_open = False
        self._title_text = ""
        self._expanded_h = int(data["h"])

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(MIN_W, MIN_H)
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint
        if data["on_top"]:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        self._build()
        self.resize(int(data["w"]), int(data["h"]))
        if data["x"] is not None and data["y"] is not None:
            self.move(int(data["x"]), int(data["y"]))
            self.ensure_on_screen()

        self.editor.blockSignals(True)
        if data.get("text"):
            self.editor.setHtml(data["text"])
        self.editor.blockSignals(False)
        self._refresh_title()
        self.set_collapsed(bool(data["collapsed"]), init=True)
        self.apply_style()
        self._sync_format_buttons()
        self._last_content_revision = self.editor.document().revision()
        self._loading = False

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        self.card = Card(self)
        self.card.setObjectName("card")
        self.card.installEventFilter(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(M, M, M, M)
        outer.addWidget(self.card)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.header = HeaderBar()
        self.header.setObjectName("noteHeader")
        self.header.installEventFilter(self)
        self.header.setAttribute(Qt.WA_StyledBackground)
        self.header.setMinimumHeight(0)
        self.header.setMaximumHeight(HEADER_H)
        self.header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.header.double_clicked.connect(lambda: self.set_collapsed(not self.data["collapsed"]))
        h = QHBoxLayout(self.header)
        h.setContentsMargins(7, 7, 7, 7)
        h.setSpacing(2)
        self.btn_new = IconButton("plus", "Новая заметка (Ctrl+N)")
        self.btn_menu = IconButton("menu", "Другие действия")
        self.btn_close = IconButton("close", "Закрыть заметку (Ctrl+W)")
        self.title = QLabel("")
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(self.btn_new)
        h.addWidget(self.title, 1)
        self.save_indicator = SaveIndicator()
        h.addWidget(self.save_indicator)
        h.addWidget(self.btn_menu)
        h.addWidget(self.btn_close)
        lay.addWidget(self.header)

        self.editor = NoteEditor()
        self.editor.setFrameShape(QFrame.NoFrame)
        self.editor.setPlaceholderText("Напишите заметку…")
        self.editor.document().setDocumentMargin(16)
        self.editor.document().setIndentWidth(18)
        self.editor.viewport().setAutoFillBackground(False)
        lay.addWidget(self.editor, 1)

        self.footer = QWidget()
        self.footer.setObjectName("noteFooter")
        self.footer.setAttribute(Qt.WA_StyledBackground)
        self.footer.setMinimumHeight(0)
        self.footer.setMaximumHeight(38)
        self.footer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        f = QHBoxLayout(self.footer)
        f.setContentsMargins(7, 2, 7, 2)
        f.setSpacing(4)
        self.format_buttons = []
        for label, tip, kind in (
            ("B", "Полужирный (Ctrl+B)", "bold"),
            ("I", "Курсив (Ctrl+I)", "italic"),
            ("U", "Подчёркнутый (Ctrl+U)", "underline"),
            ("ab", "Зачёркнутый (Ctrl+Shift+X)", "strike"),
        ):
            button = QToolButton()
            button.setText(label)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setFixedSize(32, 32)
            font = QFont("Segoe UI", 13)
            font.setBold(label == "B")
            font.setItalic(label == "I")
            font.setUnderline(label == "U")
            font.setStrikeOut(label == "ab")
            button.setFont(font)
            button.clicked.connect(lambda checked, style=kind: self.editor.set_format(style, checked))
            f.addWidget(button)
            self.format_buttons.append(button)
        self.btn_bullets = ListButton()
        self.btn_image = IconButton("image", "Добавить изображение")
        self.btn_bullets.single_clicked.connect(self.toggle_bullets)
        self.btn_bullets.double_clicked.connect(self.toggle_tasks)
        self.btn_image.clicked.connect(self.insert_image)
        f.addWidget(self.btn_bullets)
        f.addWidget(self.btn_image)
        f.addStretch(1)
        lay.addWidget(self.footer)
        self._build_options()

        self._chrome_animation = QParallelAnimationGroup(self)
        for widget in (self.header, self.footer):
            animation = QPropertyAnimation(widget, b"maximumHeight", self._chrome_animation)
            animation.setDuration(140)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            self._chrome_animation.addAnimation(animation)

        self.btn_new.clicked.connect(self.new_requested.emit)
        self.btn_menu.clicked.connect(self.show_menu)
        self.btn_close.clicked.connect(self.close)
        self.editor.textChanged.connect(self._on_text)
        self.editor.currentCharFormatChanged.connect(self._sync_format_buttons)
        self.editor.cursorPositionChanged.connect(self._sync_format_buttons)
        self.editor.selectionChanged.connect(self._sync_format_buttons)

        # Keyboard shortcuts
        ctx = Qt.WidgetWithChildrenShortcut
        for keys, fn in (
            ("Ctrl+B", self.toggle_bold),
            ("Ctrl+I", self.toggle_italic),
            ("Ctrl+U", self.toggle_underline),
            ("Ctrl+Shift+X", self.toggle_strike),
            ("Ctrl+Shift+L", self.toggle_bullets),
            ("Ctrl+Shift+C", self.toggle_tasks),
        ):
            sc = QShortcut(QKeySequence(keys), self.editor)
            sc.setContext(ctx)
            sc.activated.connect(fn)
        new_sc = QShortcut(QKeySequence("Ctrl+N"), self)
        new_sc.setContext(Qt.WindowShortcut)
        new_sc.activated.connect(self.new_requested.emit)
        for keys, fn in (("Ctrl+W", self.close), ("Ctrl+H", self.list_requested.emit)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(fn)

    # --------------------------------------------------------------- styling
    def color(self) -> str:
        return self.data.get("color") or self.s["default_color"]

    def font_size(self) -> int:
        return int(self.data.get("font_size") or self.s["font_size"])

    def opacity(self) -> int:
        v = self.data.get("opacity")
        return int(v if v is not None else self.s["opacity"])

    def apply_style(self) -> None:
        s = self.s
        bg = self.color()
        text = auto_text(bg) if s["auto_text"] else s["text_color"]
        border = QColor(255, 255, 255, 26) if is_dark(bg) else QColor(0, 0, 0, 22)
        fill = QColor(bg)
        self.card.set_look(fill, border, int(s["corner_radius"]))
        # Composite the finished window once; nested alpha backgrounds otherwise
        # produce different opacity in the header, editor, and options panel.
        self.setWindowOpacity(max(.3, min(1.0, self.opacity() / 100)))
        self.editor.set_surface(bg, text)
        header_color = QColor(bg)
        hue, saturation, value, _ = header_color.getHsvF()
        header_color.setHsvF(hue, min(1.0, saturation * 1.8), value)
        self.card.header_color = header_color
        self.card.header_height = self.header.height()
        self.card.setStyleSheet(
            f"""
            QWidget#noteHeader {{ background: transparent; }}
            QWidget#noteFooter {{ background: transparent; border: none; }}
            QScrollArea#noteOptions, QWidget#optionsBody {{ background: {bg}; color: {text}; border: none; }}
            QCheckBox, QPushButton, QLineEdit {{ color: {text}; background: transparent; font: 10pt 'Segoe UI'; }}
            QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid {rgba(text, 0.55)}; background: transparent; }}
            QCheckBox::indicator:checked {{ background: {rgba(text, 0.65)}; }}
            QPushButton {{ border: none; padding: 7px; text-align: left; }}
            QPushButton:hover {{ background: {rgba(text, 0.08)}; }}
            QLineEdit {{ border-bottom: 1px solid {rgba(text, 0.25)}; padding: 4px; }}
            QFrame#optionsDivider {{ background: {rgba(text, 0.15)}; border: none; }}
            QToolButton {{ color: {text}; background: transparent; border: none; }}
            QToolButton:hover, QToolButton:checked {{ background: {rgba(text, 0.10)}; }}
            QTextEdit {{ background: transparent; border: none; color: {text};
                         selection-background-color: {rgba(text, 0.28)}; }}
            QLabel {{ background: transparent; color: {rgba(text, 0.72)}; font-weight: 600; }}
            QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px 2px 2px 0; }}
            QScrollBar::handle:vertical {{ background: {rgba(text, 0.22)}; border-radius: 3px; min-height: 28px; }}
            QScrollBar::handle:vertical:hover {{ background: {rgba(text, 0.4)}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QAbstractScrollArea::corner {{ background: transparent; border: none; }}
            """
        )
        font = QFont(s["font_family"])
        font.setPointSize(self.font_size())
        self.editor.document().setDefaultFont(font)
        pal = self.editor.palette()
        ph = QColor(text)
        ph.setAlpha(110)
        pal.setColor(QPalette.PlaceholderText, ph)
        self.editor.setPalette(pal)
        self.save_indicator.color = QColor("#A5D9A6" if is_dark(bg) else "#437A46")

        for b in (self.btn_new, self.btn_menu, self.btn_close,
                  self.btn_bullets, self.btn_image):
            b.set_color(text)
        self._sync_options()

        self.set_shadow(bool(s["shadow"]), int(s["corner_radius"]))
        self.repaint_all()
        self._update_controls()

    def repaint_all(self) -> None:
        """Force a full repaint (also after a popup menu/dialog closed over the note)."""
        self.card.update()
        self.update()
        QTimer.singleShot(0, self._repaint_now)

    def _repaint_now(self) -> None:
        self.card.update()
        self.repaint()

    def _update_controls(self) -> None:
        collapsed = bool(self.data["collapsed"])
        show = ((not self.s["hover_controls"]) or collapsed
                or (self.isVisible() and (self._hover or self.isActiveWindow() or self._menu_open)))
        self.title.setText(self._title_text if collapsed else "")
        self._chrome_animation.stop()
        for index, height in enumerate((HEADER_H if show else 0, 38 if show and not collapsed else 0)):
            animation = self._chrome_animation.animationAt(index)
            widget = self.header if index == 0 else self.footer
            animation.setStartValue(widget.maximumHeight())
            animation.setEndValue(height)
        self._chrome_animation.start()
        self._position_options()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.ActivationChange and hasattr(self, "_chrome_animation"):
            self._update_controls()

    def eventFilter(self, obj, event):
        if obj is getattr(self, "card", None) and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._position_options)
        if obj is getattr(self, "header", None) and event.type() == QEvent.Resize:
            self.card.header_height = self.header.height()
            self.card.update()
        return super().eventFilter(obj, event)

    def enterEvent(self, e):
        self._hover = True
        self._update_controls()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._update_controls()
        super().leaveEvent(e)

    # ------------------------------------------------------------ behaviour
    def _refresh_title(self) -> None:
        self._title_text = "Пустая заметка"
        for line in self.editor.toPlainText().splitlines():
            if line.strip():
                self._title_text = line.strip()[:60]
                break
        if self.data.get("collapsed"):
            self.title.setText(self._title_text)

    def _on_text(self) -> None:
        if self._loading:
            return
        revision = self.editor.document().revision()
        if revision == self._last_content_revision:
            return
        self._last_content_revision = revision
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._refresh_title()
        self.content_changed.emit()
        self.changed.emit()

    def moveEvent(self, e):
        super().moveEvent(e)
        self.changed.emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "options_panel"):
            self._position_options()
        self.changed.emit()

    def closeEvent(self, e):
        e.ignore()
        self.data["is_open"] = False
        self.hide()
        self.changed.emit()
        self.closed.emit()

    def hideEvent(self, event):
        if hasattr(self, "save_indicator"):
            self.save_indicator.reset()
        super().hideEvent(event)

    def ensure_on_screen(self) -> None:
        center = self.frameGeometry().center()
        for sc in QGuiApplication.screens():
            if sc.availableGeometry().contains(center):
                return
        g = QGuiApplication.primaryScreen().availableGeometry()
        self.move(g.center() - QPoint(self.width() // 2, self.height() // 2))

    def focus_editor(self) -> None:
        self.data["is_open"] = True
        self.show()
        self.raise_()
        self.activateWindow()
        self.editor.setFocus()

    def set_collapsed(self, flag: bool, init: bool = False) -> None:
        if flag == self.data["collapsed"] and not init:
            return
        if flag and not init and not self.data["collapsed"]:
            self._expanded_h = self.height()
        self.data["collapsed"] = flag
        if flag:
            self.save_indicator.reset()
            self._menu_open = False
            self.btn_menu.kind = "menu"
            self.btn_menu.set_active(False)
            self.options_panel.hide()
            self.editor.setEnabled(True)
            self.editor.hide()
            self.footer.hide()
            self.setMinimumHeight(0)
            self.setFixedHeight(HEADER_H + 2 * M)
        else:
            self.editor.show()
            self.footer.show()
            self.setMinimumHeight(MIN_H)
            self.setMaximumHeight(16777215)
            self.resize(self.width(), self._expanded_h)
        self._update_controls()
        if not init:
            self.changed.emit()

    def set_on_top(self, flag: bool) -> None:
        flag = bool(flag)
        self.data["on_top"] = flag
        self.pin_check.blockSignals(True)
        self.pin_check.setChecked(flag)
        self.pin_check.blockSignals(False)
        if bool(self.windowFlags() & Qt.WindowStaysOnTopHint) == flag:
            return
        was_visible = self.isVisible()
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, flag)
        self.setGeometry(geo)
        if was_visible:
            self.show()
        self.changed.emit()

    def set_color(self, color: str | None) -> None:
        self.data["color"] = color
        self.apply_style()
        self.changed.emit()

    def set_opacity(self, value: int | None) -> None:
        self.data["opacity"] = value
        self.apply_style()
        self.changed.emit()

    def set_font_size(self, value: int | None) -> None:
        self.data["font_size"] = None if value is None else max(8, min(40, int(value)))
        self.apply_style()
        self.changed.emit()

    def clear_overrides(self) -> None:
        self.data["color"] = None
        self.data["opacity"] = None
        self.data["font_size"] = None
        self.apply_style()
        self.changed.emit()

    # ------------------------------------------------------------ formatting
    def toggle_bold(self) -> None:
        self.editor.toggle_format("bold")

    def toggle_italic(self) -> None:
        self.editor.toggle_format("italic")

    def toggle_underline(self) -> None:
        self.editor.toggle_format("underline")

    def toggle_strike(self) -> None:
        self.editor.toggle_format("strike")

    def toggle_bullets(self) -> None:
        self.editor.set_list()
        self._sync_format_buttons()

    def toggle_tasks(self) -> None:
        self.editor.set_list(tasks=True)
        self._sync_format_buttons()

    def _sync_format_buttons(self, *_args) -> None:
        for button, kind in zip(self.format_buttons, ("bold", "italic", "underline", "strike")):
            button.setChecked(self.editor.format_enabled(kind))
        self.btn_bullets.set_active(self.editor.textCursor().currentList() is not None)

    def insert_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Добавить изображение", "", "Изображения (*.png *.jpg *.jpeg *.bmp *.gif)")
        if path:
            self.add_image(path)

    def add_image(self, path: str) -> bool:
        return self.editor.add_image(path)

    # ------------------------------------------------------------------ menu
    def _build_options(self) -> None:
        self.options_panel = QScrollArea(self.card)
        self.options_panel.setObjectName("noteOptions")
        self.options_panel.setFrameShape(QFrame.NoFrame)
        self.options_panel.setFocusPolicy(Qt.StrongFocus)
        self.options_panel.setWidgetResizable(True)
        self.options_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("optionsBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(0)
        self._swatches = []
        for name, color in NOTE_COLORS:
            swatch = Swatch(color, name, d=14)
            swatch.clicked.connect(lambda checked=False, value=color: self.set_color(value))
            row.addWidget(swatch)
            self._swatches.append(swatch)
        row.addStretch()
        layout.addLayout(row)
        self.custom_color = QLineEdit()
        self.custom_color.setMaxLength(7)
        self.custom_color.setAccessibleName("Цвет заметки")
        self.custom_color.editingFinished.connect(self._set_custom_color)
        layout.addWidget(self.custom_color)
        self.pin_check = QCheckBox("Поверх других окон")
        self.pin_check.toggled.connect(self.set_on_top)
        layout.addWidget(self.pin_check)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("Непрозрачность"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setAccessibleName("Непрозрачность заметки")
        self.opacity_slider.valueChanged.connect(self.set_opacity)
        opacity_row.addWidget(self.opacity_slider, 1)
        layout.addLayout(opacity_row)
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Размер текста"), 1)
        smaller, larger = QToolButton(), QToolButton()
        smaller.setText("−")
        larger.setText("+")
        smaller.setAccessibleName("Уменьшить текст")
        larger.setAccessibleName("Увеличить текст")
        smaller.clicked.connect(lambda: self.set_font_size(self.font_size() - 1))
        larger.clicked.connect(lambda: self.set_font_size(self.font_size() + 1))
        self.font_label = QLabel()
        for widget in (smaller, self.font_label, larger):
            font_row.addWidget(widget)
        layout.addLayout(font_row)
        divider = QFrame()
        divider.setObjectName("optionsDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        button = QPushButton("Все записки")
        button.clicked.connect(self.list_requested.emit)
        layout.addWidget(button)
        layout.addStretch()
        self.options_panel.setWidget(body)
        self.options_scroll = SmoothScroll(self.options_panel)
        self.options_panel.hide()

    def _set_custom_color(self):
        color = QColor(self.custom_color.text())
        if color.isValid():
            self.set_color(color.name())
        else:
            self.custom_color.setText(self.color())

    def _sync_options(self):
        for swatch in self._swatches:
            swatch.selected = swatch.color.lower() == self.color().lower()
            swatch.update()
        for widget, value in ((self.pin_check, self.data["on_top"]), (self.opacity_slider, self.opacity())):
            widget.blockSignals(True)
            if isinstance(widget, QCheckBox):
                widget.setChecked(value)
            else:
                widget.setValue(value)
            widget.blockSignals(False)
        if not self.custom_color.hasFocus():
            self.custom_color.setText(self.color())
        self.font_label.setText(str(self.font_size()))

    def _position_options(self):
        if hasattr(self, "options_panel"):
            top = max(HEADER_H, self.header.height())
            inset = max(1, int(self.s["corner_radius"]))
            self.options_panel.setGeometry(inset, top, max(0, self.card.width() - 2 * inset),
                                           max(0, self.card.height() - top - inset))
            if self._menu_open:
                self.options_panel.raise_()

    def show_menu(self) -> None:
        if self.data["collapsed"]:
            self.set_collapsed(False)
        self._menu_open = not self._menu_open
        self.options_panel.setVisible(self._menu_open)
        self.editor.setEnabled(not self._menu_open)
        self.btn_menu.kind = "back" if self._menu_open else "menu"
        self.btn_menu.setToolTip("Вернуться к заметке" if self._menu_open else "Другие действия")
        self.btn_menu.set_active(self._menu_open)
        self._update_controls()
        if self._menu_open:
            self.options_panel.setFocus()
        else:
            self.editor.setFocus()

    # ----------------------------------------------------------- persistence
    def snapshot(self) -> dict:
        g = self.geometry()
        d = self.data
        d["x"], d["y"], d["w"] = g.x(), g.y(), g.width()
        d["h"] = self._expanded_h if d["collapsed"] else g.height()
        d["text"] = self._html()
        return d

    def _html(self) -> str:
        """Rich text as HTML, minus the body font so Settings can still control the font."""
        if not self.editor.toPlainText() and not self.editor.document().begin().textList():
            return ""
        return re.sub(r'<body style="[^"]*">', "<body>", self.editor.toHtml(), count=1)
