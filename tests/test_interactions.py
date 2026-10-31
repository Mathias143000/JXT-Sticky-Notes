"""Exercise note interactions through Qt events and real persisted documents."""
from unittest.mock import patch
import unittest

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import (
    QColor, QImage, QTextBlockFormat, QTextCharFormat, QTextCursor, QWheelEvent,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import test_notes
from themes import NOTE_COLORS


class NoteInteractionsTests(unittest.TestCase):
    setUp = test_notes.NotesLifecycleTests.setUp
    tearDown = test_notes.NotesLifecycleTests.tearDown
    controller = test_notes.NotesLifecycleTests.controller
    saved = test_notes.NotesLifecycleTests.saved

    @classmethod
    def setUpClass(cls):
        test_notes.NotesLifecycleTests.setUpClass()
        cls.qt = test_notes.NotesLifecycleTests.qt

    def test_color_carousel_wraps_and_continues_after_restart_and_deletion(self):
        controller = self.controller(hidden=True)
        expected = [color for _, color in NOTE_COLORS]
        start = controller._next_color_index
        for index in range(len(expected) + 2):
            controller.new_note()
            note = controller.notes[-1]
            self.assertEqual(note.color(), expected[(start + index) % len(expected)])
            note.hide()
        controller.save_now()
        controller.delete_note(controller.notes[-1])
        next_color = expected[controller._next_color_index]
        restored = self.controller(hidden=True)
        restored.new_note()
        self.assertEqual(restored.notes[-1].color(), next_color)

    def test_format_buttons_enable_mixed_selection_then_disable_without_losing_focus(self):
        controller = self.controller()
        note = controller.notes[0]
        note.focus_editor()
        QTest.qWait(50)
        for index, kind in enumerate(("bold", "italic", "underline", "strike")):
            note.editor.setPlainText("plain styled")
            cursor = note.editor.textCursor()
            cursor.setPosition(6)
            cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            note.editor.setTextCursor(cursor)
            note.editor.set_format(kind, True)
            note.editor.selectAll()
            self.assertFalse(note.format_buttons[index].isChecked())
            QTest.mouseClick(note.format_buttons[index], Qt.LeftButton)
            self.assertTrue(note.editor.format_enabled(kind))
            self.assertTrue(note.editor.textCursor().hasSelection())
            self.assertTrue(note.editor.hasFocus())
            QTest.mouseClick(note.format_buttons[index], Qt.LeftButton)
            self.assertFalse(note.editor.format_enabled(kind))

    def test_double_click_creates_checklist_and_checkbox_click_strikes_and_restores(self):
        controller = self.controller()
        note = controller.notes[0]
        note.editor.setPlainText("First task\nSecond task")
        note.editor.selectAll()
        QTest.mouseDClick(note.btn_bullets, Qt.LeftButton)
        QTest.qWait(QApplication.doubleClickInterval() + 50)
        block = note.editor.document().begin()
        self.assertEqual(block.blockFormat().marker(), QTextBlockFormat.MarkerType.Unchecked)
        self.assertEqual(block.next().blockFormat().marker(), QTextBlockFormat.MarkerType.Unchecked)
        cursor = QTextCursor(block)
        note.editor.setTextCursor(cursor)
        rect = note.editor.cursorRect(cursor)
        point = QPoint(rect.left() - 8, rect.center().y())
        QTest.mouseClick(note.editor.viewport(), Qt.LeftButton, pos=point)
        self.assertEqual(block.blockFormat().marker(), QTextBlockFormat.MarkerType.Checked)
        cursor.setPosition(block.position() + 2)
        self.assertTrue(cursor.charFormat().fontStrikeOut())
        note.close()
        restored = self.controller(hidden=True).notes[0]
        block = restored.editor.document().begin()
        self.assertEqual(block.blockFormat().marker(), QTextBlockFormat.MarkerType.Checked)
        cursor = QTextCursor(block)
        cursor.setPosition(2)
        self.assertTrue(cursor.charFormat().fontStrikeOut())
        controller.open_note(note.data["id"])
        QTest.mouseClick(note.editor.viewport(), Qt.LeftButton, pos=point)
        self.assertEqual(note.editor.document().begin().blockFormat().marker(), QTextBlockFormat.MarkerType.Unchecked)
        cursor = QTextCursor(note.editor.document().begin())
        cursor.setPosition(2)
        self.assertFalse(cursor.charFormat().fontStrikeOut())

    def test_clipboard_image_paste_embeds_bytes_and_survives_restart(self):
        controller = self.controller()
        note = controller.notes[0]
        note.editor.clear()
        image = QImage(800, 400, QImage.Format_ARGB32)
        image.fill(QColor("#3344CC"))
        clipboard = QApplication.clipboard()
        previous = QMimeData()
        source = clipboard.mimeData()
        if source:
            for kind in source.formats():
                previous.setData(kind, source.data(kind))
        try:
            clipboard.setImage(image)
            note.focus_editor()
            QTest.keyClick(note.editor, Qt.Key_V, Qt.ControlModifier)
        finally:
            if previous.formats():
                clipboard.setMimeData(previous)
            else:
                clipboard.clear()
        cursor = note.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat().toImageFormat()
        self.assertTrue(fmt.name().startswith("data:image/png;base64,"))
        self.assertLessEqual(fmt.width(), note.editor.viewport().width())
        note.close()
        restored = self.controller(hidden=True).notes[0]
        cursor = restored.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.assertTrue(cursor.charFormat().isImageFormat())
        self.assertEqual(restored.editor.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)

    def test_save_check_animates_only_after_successful_write(self):
        controller = self.controller()
        note = controller.notes[0]
        note.editor.setPlainText("Save this")
        self.assertEqual(note.save_indicator.state, "pending")
        with patch("app.write_json_atomic", side_effect=OSError("disk full")), patch.object(controller.tray, "showMessage"):
            controller.save_now()
        self.assertEqual(note.save_indicator.state, "error")
        controller.save_now()
        self.assertEqual(note.save_indicator.state, "saved")
        QTest.qWait(100)
        self.assertGreater(note.save_indicator.phase, 0)
        self.assertLess(note.save_indicator.phase, 1)

    def test_options_stay_inside_note_and_all_resize_edges_preserve_opposite_edge(self):
        controller = self.controller()
        note = controller.notes[0]
        note.show_menu()
        self.assertTrue(note.options_panel.isVisible())
        self.assertIs(note.options_panel.window(), note)
        self.assertTrue(note.card.rect().contains(note.options_panel.geometry()))
        note.show_menu()
        self.assertFalse(note.options_panel.isVisible())
        geometry = note.geometry()
        self.assertEqual(len(note._resize_handles), 8)
        for handle in note._resize_handles:
            result = handle.drag_geometry(geometry, QPoint(-11, -9))
            if handle.edges & Qt.LeftEdge:
                self.assertEqual(result.right(), geometry.right())
                self.assertEqual(result.left(), geometry.left() - 11)
            if handle.edges & Qt.TopEdge:
                self.assertEqual(result.bottom(), geometry.bottom())
                self.assertEqual(result.top(), geometry.top() - 9)
            if handle.edges & Qt.RightEdge:
                self.assertEqual(result.left(), geometry.left())
            if handle.edges & Qt.BottomEdge:
                self.assertEqual(result.top(), geometry.top())

    def test_mouse_wheel_scrolls_through_intermediate_positions(self):
        controller = self.controller()
        note = controller.notes[0]
        note.editor.setPlainText("\n".join(f"Line {i}" for i in range(100)))
        note.editor.moveCursor(QTextCursor.Start)
        QTest.qWait(180)
        bar = note.editor.verticalScrollBar()
        bar.setValue(0)
        event = QWheelEvent(QPointF(70, 70), QPointF(70, 70), QPoint(), QPoint(0, -120),
                            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(note.editor.viewport(), event)
        QTest.qWait(55)
        middle = bar.value()
        self.assertGreater(middle, 0)
        QTest.qWait(220)
        self.assertGreater(bar.value(), middle)

    def test_single_click_bullets_is_immediate_and_enter_continues_unchecked_task(self):
        controller = self.controller()
        note = controller.notes[0]
        note.focus_editor()
        note.editor.setPlainText("Task")
        QTest.mouseClick(note.btn_bullets, Qt.LeftButton)
        self.assertIsNotNone(note.editor.textCursor().currentList())
        note.toggle_tasks()
        rect = note.editor.cursorRect(QTextCursor(note.editor.document().begin()))
        QTest.mouseClick(note.editor.viewport(), Qt.LeftButton,
                         pos=QPoint(rect.left() - 8, rect.center().y()))
        self.assertEqual(note.editor.document().begin().blockFormat().marker(), QTextBlockFormat.MarkerType.Checked)
        cursor = note.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        note.editor.setTextCursor(cursor)
        QTest.keyClick(note.editor, Qt.Key_Return)
        self.assertEqual(note.editor.textCursor().blockFormat().marker(), QTextBlockFormat.MarkerType.Unchecked)
        self.assertFalse(note.editor.currentCharFormat().fontStrikeOut())

    def test_colored_note_has_no_white_strip(self):
        controller = self.controller()
        note = controller.notes[0]
        note.set_color("#DDCEFF")
        note.editor.clear()
        note.focus_editor()
        QTest.qWait(200)
        image = note.card.grab().toImage()
        white = 0
        for y in range(2, image.height() - 2):
            for x in range(2, image.width() - 2):
                color = image.pixelColor(x, y)
                if color.alpha() == 255 and min(color.red(), color.green(), color.blue()) > 245:
                    white += 1
        self.assertEqual(white, 0, "A colored empty note must not contain a white scrollbar or separator")
