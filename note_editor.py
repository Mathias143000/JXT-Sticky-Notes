"""Rich note editing: formatting, native checkboxes, and embedded clipboard images."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRect, Qt
from PySide6.QtGui import (
    QImage, QImageReader, QTextBlockFormat, QTextCharFormat, QTextCursor,
    QTextImageFormat, QTextListFormat,
)
from PySide6.QtWidgets import QTextEdit

from widgets import SmoothScroll

MARKER = QTextBlockFormat.MarkerType


class NoteEditor(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAcceptRichText(True)
        self.smooth_scroll = SmoothScroll(self)
        self._pressed_task = None
        self._checkbox_press = False

    def selected_blocks(self):
        cursor = self.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        block = self.document().findBlock(start)
        blocks = []
        while block.isValid() and (block.position() < end or not blocks):
            blocks.append(block)
            block = block.next()
        return blocks

    @staticmethod
    def _enabled(fmt, kind):
        return {
            "bold": fmt.fontWeight() >= 600,
            "italic": fmt.fontItalic(),
            "underline": fmt.fontUnderline(),
            "strike": fmt.fontStrikeOut(),
        }[kind]

    def format_enabled(self, kind):
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return self._enabled(self.currentCharFormat(), kind)
        found = False
        for block in self.selected_blocks():
            fragment = block.begin()
            while not fragment.atEnd():
                part = fragment.fragment()
                if (part.isValid() and part.position() < cursor.selectionEnd()
                        and part.position() + part.length() > cursor.selectionStart()):
                    found = True
                    if not self._enabled(part.charFormat(), kind):
                        return False
                fragment += 1
        return found

    def set_format(self, kind, enabled):
        fmt = QTextCharFormat()
        if kind == "bold":
            fmt.setFontWeight(700 if enabled else 400)
        elif kind == "italic":
            fmt.setFontItalic(enabled)
        elif kind == "underline":
            fmt.setFontUnderline(enabled)
        elif kind == "strike":
            fmt.setFontStrikeOut(enabled)
        self.mergeCurrentCharFormat(fmt)
        self.window().activateWindow()
        self.setFocus(Qt.OtherFocusReason)

    def toggle_format(self, kind):
        self.set_format(kind, not self.format_enabled(kind))

    def set_list(self, tasks=False):
        blocks = self.selected_blocks()
        already_tasks = all(block.blockFormat().marker() != MARKER.NoMarker for block in blocks)
        remove = not tasks and all(block.textList() for block in blocks) and not already_tasks
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if not remove:
            fmt = QTextListFormat()
            fmt.setStyle(QTextListFormat.ListDisc)
            fmt.setIndent(1)
            cursor.createList(fmt)
        for block in blocks:
            block_cursor = QTextCursor(block)
            block_fmt = block_cursor.blockFormat()
            was_checked = block_fmt.marker() == MARKER.Checked
            block_fmt.setMarker(MARKER.Unchecked if tasks and not already_tasks else MARKER.NoMarker)
            if remove:
                block_fmt.setIndent(0)
                if block.textList():
                    block.textList().remove(block)
            block_cursor.setBlockFormat(block_fmt)
            if was_checked:
                self.strike_block(block, False)
        cursor.endEditBlock()
        self.setFocus(Qt.OtherFocusReason)
        self.cursorPositionChanged.emit()

    @staticmethod
    def strike_block(block, checked):
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(checked)
        cursor.mergeCharFormat(fmt)

    def mousePressEvent(self, event):
        block = self.cursorForPosition(event.position().toPoint()).block()
        self._checkbox_press = False
        marker = block.blockFormat().marker()
        if marker in (MARKER.Checked, MARKER.Unchecked) and event.button() == Qt.LeftButton and not self.isReadOnly():
            rect = self.cursorRect(QTextCursor(block))
            box = QRect(rect.left() - rect.height() - 5, rect.top(), rect.height() + 5, rect.height())
            if box.contains(event.position().toPoint()):
                cursor = QTextCursor(block)
                cursor.beginEditBlock()
                fmt = block.blockFormat()
                checked = marker != MARKER.Checked
                fmt.setMarker(MARKER.Checked if checked else MARKER.Unchecked)
                cursor.setBlockFormat(fmt)
                self.strike_block(block, checked)
                cursor.endEditBlock()
                self._checkbox_press = True
                self._pressed_task = None
                self.setFocus(Qt.MouseFocusReason)
                event.accept()
                return
        self._pressed_task = (block, block.blockFormat().marker()) if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._checkbox_press:
            self._checkbox_press = False
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self._pressed_task:
            block, before = self._pressed_task
            self._pressed_task = None
            if block.isValid():
                after = block.blockFormat().marker()
                if before != after and after in (MARKER.Checked, MARKER.Unchecked):
                    self.strike_block(block, after == MARKER.Checked)

    def keyPressEvent(self, event):
        was_task = self.textCursor().blockFormat().marker() != MARKER.NoMarker
        super().keyPressEvent(event)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier and was_task:
            cursor = self.textCursor()
            if cursor.currentList():
                fmt = cursor.blockFormat()
                fmt.setMarker(MARKER.Unchecked)
                cursor.setBlockFormat(fmt)
            char = QTextCharFormat()
            char.setFontStrikeOut(False)
            self.mergeCurrentCharFormat(char)
        # Markdown-style task prefixes are also convenient for keyboard entry.
        if event.key() == Qt.Key_Space and self.textCursor().block().text() in ("- [ ] ", "- [x] ", "- [X] "):
            cursor = self.textCursor()
            checked = cursor.block().text()[3].lower() == "x"
            cursor.beginEditBlock()
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.createList(QTextListFormat.ListDisc)
            fmt = cursor.blockFormat()
            fmt.setMarker(MARKER.Checked if checked else MARKER.Unchecked)
            cursor.setBlockFormat(fmt)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            self.set_format("strike", checked)

    def canInsertFromMimeData(self, source):
        return source.hasImage() or bool(self._clipboard_image_files(source)) or super().canInsertFromMimeData(source)

    @staticmethod
    def _clipboard_image_files(source):
        urls = source.urls()
        if not urls or not all(url.isLocalFile() for url in urls):
            return []
        paths = [url.toLocalFile() for url in urls]
        return paths if all(QImageReader(path).canRead() for path in paths) else []

    def insertFromMimeData(self, source):
        if source.hasImage():
            image = source.imageData()
            if isinstance(image, QImage):
                self.insert_image(image)
                return
            if hasattr(image, "toImage"):
                self.insert_image(image.toImage())
                return
        paths = self._clipboard_image_files(source)
        if paths:
            for index, path in enumerate(paths):
                if index:
                    self.textCursor().insertBlock()
                self.add_image(path)
            return
        super().insertFromMimeData(source)

    def add_image(self, path):
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        return self.insert_image(reader.read())

    def insert_image(self, image):
        if image.isNull():
            return False
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer, "PNG"):
            return False
        fmt = QTextImageFormat()
        fmt.setName("data:image/png;base64," + bytes(encoded.toBase64()).decode("ascii"))
        width = min(image.width(), max(64, self.viewport().width() - 2 * self.document().documentMargin()))
        fmt.setWidth(width)
        fmt.setHeight(image.height() * width / image.width())
        self.textCursor().insertImage(fmt)
        self.setFocus(Qt.OtherFocusReason)
        return True
