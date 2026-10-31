"""Windows-style notes library. Closing a note never removes it from this list."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QStyle, QStyledItemDelegate, QVBoxLayout,
)

from note_window import Card, Grip, HeaderBar, M, PaperWindow
from themes import MENU_QSS, auto_text
from widgets import IconButton


class NoteDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(250, 106)

    def paint(self, painter: QPainter, option, index):
        note = index.data(Qt.UserRole)
        if not note:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect).adjusted(0, 4, -1, -4)
        bg = QColor(note["color"])
        text = QColor(auto_text(note["color"]))
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 2, 2)
        if option.state & (QStyle.State_Selected | QStyle.State_MouseOver):
            outline = QColor(text)
            outline.setAlpha(50)
            painter.setPen(QPen(outline, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(.5, .5, -.5, -.5), 2, 2)

        stamp = note.get("updated_at", "")
        try:
            modified = datetime.fromisoformat(stamp).astimezone()
            stamp = modified.strftime("%H:%M" if modified.date() == datetime.now().date() else "%d.%m.%Y")
        except (ValueError, TypeError):
            stamp = ""
        painter.setPen(text)
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(rect.adjusted(16, 10, -14, 0), Qt.AlignTop | Qt.AlignRight, stamp)
        painter.setFont(QFont("Segoe UI", 11))
        preview = note["preview"].replace("\ufffc", "[Изображение]").strip()
        if not preview:
            text.setAlpha(160)
            painter.setPen(text)
            preview = "Напишите что-нибудь…"
        painter.save()
        body = rect.adjusted(18, 34, -18, -12)
        painter.setClipRect(body)
        painter.drawText(body, Qt.AlignTop | Qt.TextWordWrap, preview)
        painter.restore()

        fold = QPainterPath()
        fold.moveTo(rect.right() - 16, rect.bottom())
        fold.lineTo(rect.right() - 16, rect.bottom() - 16)
        fold.lineTo(rect.right(), rect.bottom() - 16)
        fold.closeSubpath()
        painter.fillPath(fold, bg.darker(114))
        corner = QPainterPath()
        corner.moveTo(rect.right() - 16, rect.bottom())
        corner.lineTo(rect.right(), rect.bottom() - 16)
        corner.lineTo(rect.right(), rect.bottom())
        corner.closeSubpath()
        painter.fillPath(corner, QColor("white"))
        painter.restore()


class NotesListWindow(PaperWindow):
    new_requested = Signal()
    settings_requested = Signal()
    open_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Записки")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(320, 400)
        self.resize(404, 710)
        self._notes = []
        self.setStyleSheet("""
            QLabel { background: transparent; color: #202020; font-family: 'Segoe UI'; }
            QLineEdit { background: #EEEEEE; color: #282828; border: none;
                        padding: 10px 12px; font: 11pt 'Segoe UI'; }
            QLineEdit:focus { background: #F5F5F5; border-bottom: 2px solid #777; padding-bottom: 8px; }
            QListWidget { background: white; border: none; outline: none; }
            QScrollBar:vertical { background: white; width: 6px; }
            QScrollBar::handle:vertical { background: #CCCCCC; min-height: 24px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(M, M, M, M)
        self.card = Card()
        self.card.set_look(QColor("white"), QColor("#B5B5B5"), 0)
        outer.addWidget(self.card)
        body = QVBoxLayout(self.card)
        body.setContentsMargins(15, 0, 15, 8)
        body.setSpacing(10)

        self.header = HeaderBar()
        self.header.setFixedHeight(44)
        top = QHBoxLayout(self.header)
        top.setContentsMargins(0, 0, 0, 0)
        self.btn_new = IconButton("plus", "Новая заметка (Ctrl+N)")
        self.btn_settings = IconButton("settings", "Настройки")
        self.btn_close = IconButton("close", "Закрыть список")
        top.addWidget(self.btn_new)
        top.addStretch()
        top.addWidget(self.btn_settings)
        top.addWidget(self.btn_close)
        body.addWidget(self.header)
        title = QLabel("Записки")
        title.setStyleSheet("font-size: 24px; font-weight: 700; padding-bottom: 2px;")
        body.addWidget(title)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск…")
        self.search.setAccessibleName("Поиск заметок")
        self.search.setClearButtonEnabled(True)
        body.addWidget(self.search)
        self.list = QListWidget()
        self.list.setAccessibleName("Все заметки")
        self.list.setItemDelegate(NoteDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        body.addWidget(self.list, 1)
        self.empty = QLabel("Пока нет заметок.\nНажмите +, чтобы создать первую.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet("color: #707070; font-size: 14px; padding: 28px 0;")
        body.addWidget(self.empty, 1)
        bottom = QHBoxLayout()
        self.status = QLabel("Все изменения сохранены")
        self.status.setStyleSheet("font-size: 11px; color: #777777;")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        bottom.addWidget(Grip(), 0, Qt.AlignBottom)
        body.addLayout(bottom)

        self.btn_new.clicked.connect(self.new_requested.emit)
        self.btn_settings.clicked.connect(self.settings_requested.emit)
        self.btn_close.clicked.connect(self.close)
        self.search.textChanged.connect(self._render)
        self.list.itemClicked.connect(self._open)
        self.list.itemActivated.connect(self._open)
        self.list.customContextMenuRequested.connect(self._context_menu)
        for key, callback in (("Ctrl+N", self.new_requested.emit), ("Ctrl+F", self.search.setFocus)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
        self._render()

    def set_notes(self, notes: list[dict]) -> None:
        self._notes = sorted(notes, key=lambda n: n.get("updated_at") or "", reverse=True)
        self._render()

    def _render(self) -> None:
        selected = self.list.currentItem()
        selected_id = selected.data(Qt.UserRole)["id"] if selected else None
        scroll = self.list.verticalScrollBar().value()
        self.list.clear()
        query = self.search.text().strip().casefold()
        for note in self._notes:
            if query and query not in note["preview"].casefold():
                continue
            item = QListWidgetItem()
            item.setData(Qt.UserRole, note)
            item.setText(note["preview"][:120] or "Пустая заметка")
            item.setToolTip("Открыть заметку")
            self.list.addItem(item)
            if note["id"] == selected_id:
                self.list.setCurrentItem(item)
        self.list.verticalScrollBar().setValue(scroll)
        has_items = self.list.count() > 0
        self.list.setVisible(has_items)
        self.empty.setVisible(not has_items)
        self.empty.setText("Ничего не найдено.\nПопробуйте другой запрос." if query else
                           "Пока нет заметок.\nНажмите +, чтобы создать первую.")

    def _open(self, item):
        self.open_requested.emit(item.data(Qt.UserRole)["id"])

    def _context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        note_id = item.data(Qt.UserRole)["id"]
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        menu.addAction("Открыть заметку", lambda: self.open_requested.emit(note_id))
        menu.addSeparator()
        menu.addAction("Удалить заметку", lambda: self.delete_requested.emit(note_id))
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def set_save_status(self, text: str) -> None:
        self.status.setText(text)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
