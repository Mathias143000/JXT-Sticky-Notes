"""Lifecycle checks using real Qt widgets and isolated temporary note storage."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from app import Controller
from config import Settings, write_json_atomic
from note_window import HEADER_H


class NotesLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.patches = [
            patch("config.data_dir", return_value=self.path),
            patch("app.data_dir", return_value=self.path),
            patch.object(QSystemTrayIcon, "show"),
        ]
        for patcher in self.patches:
            patcher.start()
        self.controllers = []

    def tearDown(self):
        for controller in self.controllers:
            controller._save_timer.stop()
            controller._library_timer.stop()
            controller.s._timer.stop()
            for note in controller.notes:
                note.hide()
                note.deleteLater()
            controller.library.hide()
            controller.library.deleteLater()
            controller.tray.hide()
            controller.deleteLater()
        self.qt.processEvents()
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temp.cleanup()

    def controller(self, hidden=False):
        controller = Controller(Settings(), hidden)
        self.controllers.append(controller)
        return controller

    def saved(self):
        return json.loads((self.path / "notes.json").read_text(encoding="utf-8"))

    def test_close_saves_last_keystroke_and_reopen_from_search_after_restart(self):
        controller = self.controller()
        note = controller.notes[0]
        note.editor.setPlainText("Купить молоко и хлеб")
        note_id = note.data["id"]
        # Click the actual close control, before the autosave debounce fires.
        QTest.mouseClick(note.btn_close, Qt.LeftButton)
        self.assertEqual(len(controller.notes), 1)
        self.assertFalse(note.isVisible())
        self.assertFalse(self.saved()["notes"][0]["is_open"])
        self.assertIn("Купить молоко", self.saved()["notes"][0]["text"])

        restored = self.controller()
        self.assertFalse(restored.notes[0].isVisible())
        restored.library.search.setText("МОЛОКО")
        self.assertEqual(restored.library.list.count(), 1)
        restored.library.search.setText("не существует")
        self.assertEqual(restored.library.list.count(), 0)
        self.assertTrue(restored.library.empty.isVisible())
        restored.library.search.clear()
        restored.library.list.itemActivated.emit(restored.library.list.item(0))
        self.assertTrue(restored.notes[0].isVisible())
        self.assertTrue(restored.notes[0].data["is_open"])
        self.assertEqual(restored.notes[0].data["id"], note_id)

    def test_autosave_updates_library_and_keeps_closed_notes_closed_when_showing_all(self):
        controller = self.controller()
        first = controller.notes[0]
        first.close()
        controller.new_note()
        second = controller.notes[-1]
        second.editor.setPlainText("Новая идея")
        QTest.qWait(850)
        self.assertEqual(len(self.saved()["notes"]), 2)
        self.assertEqual(controller.library.list.item(0).data(Qt.UserRole)["preview"], "Новая идея")
        controller.hide_all()
        controller.show_all()
        self.assertFalse(first.isVisible())
        self.assertTrue(second.isVisible())

    def test_legacy_notes_keep_content_geometry_color_and_collapse_state(self):
        write_json_atomic(self.path / "notes.json", {"version": 1, "notes": [{
            "id": "legacy", "text": "<p><b>Старая заметка</b></p>",
            "x": 70, "y": 80, "w": 380, "h": 360, "color": "#FFD5BC",
            "collapsed": True, "on_top": True,
        }]})
        controller = self.controller(hidden=True)
        note = controller.notes[0]
        self.assertEqual(note.editor.toPlainText(), "Старая заметка")
        self.assertEqual(note.color(), "#FFD5BC")
        self.assertTrue(note.data["is_open"])
        self.assertTrue(note.data["collapsed"])
        self.assertFalse(note.isVisible())
        controller.save_now()
        saved = self.saved()["notes"][0]
        self.assertEqual((saved["w"], saved["h"]), (380, 360))
        self.assertTrue(saved["on_top"])
        self.assertEqual(self.saved()["version"], 2)

    def test_formatting_and_embedded_image_survive_restart(self):
        controller = self.controller(hidden=True)
        note = controller.notes[0]
        note.editor.clear()
        note.toggle_bold()
        note.toggle_underline()
        note.editor.insertPlainText("Важное")
        image_path = self.path / "source.png"
        image = QImage(20, 10, QImage.Format_ARGB32)
        image.fill(QColor("red"))
        image.save(str(image_path))
        self.assertTrue(note.add_image(str(image_path)))
        note.close()
        image_path.unlink()
        restored = self.controller(hidden=True).notes[0]
        cursor = restored.editor.textCursor()
        cursor.setPosition(1)
        self.assertTrue(cursor.charFormat().fontUnderline())
        self.assertGreaterEqual(cursor.charFormat().fontWeight(), 600)
        cursor.movePosition(QTextCursor.End)
        image_format = cursor.charFormat().toImageFormat()
        self.assertTrue(image_format.name().startswith("data:image/png;base64,"))
        resource = restored.editor.document().resource(2, image_format.name())
        self.assertFalse(resource.isNull())

    def test_header_folds_without_resizing_note_and_manual_collapse_restores_height(self):
        controller = self.controller(hidden=True)
        note = controller.notes[0]
        size = note.size()
        note._hover = False
        note._update_controls()
        QTest.qWait(220)
        self.assertEqual(note.header.maximumHeight(), 0)
        self.assertEqual(note.footer.maximumHeight(), 0)
        note.focus_editor()
        note._hover = True
        note._update_controls()
        QTest.qWait(220)
        self.assertEqual(note.header.maximumHeight(), HEADER_H)
        self.assertEqual(note.size(), size)
        note.set_collapsed(True)
        self.assertEqual(note.height(), HEADER_H + 24)
        note.set_collapsed(False)
        self.assertEqual(note.height(), size.height())

    def test_delete_and_duplicate_are_distinct_from_close(self):
        controller = self.controller(hidden=True)
        first = controller.notes[0]
        first.editor.setPlainText("Оригинал")
        first.close()
        controller.duplicate_note(first)
        copied = controller.notes[1]
        self.assertNotEqual(first.data["id"], copied.data["id"])
        self.assertTrue(copied.data["is_open"])
        self.assertEqual(copied.editor.toPlainText(), "Оригинал")
        controller.delete_note_by_id(first.data["id"])
        self.assertEqual(len(self.saved()["notes"]), 1)
        self.assertEqual(controller.library.list.count(), 1)
        controller.delete_note(copied)
        self.assertEqual(self.saved()["notes"], [])
        self.assertEqual(self.controller(hidden=True).notes, [])

    def test_save_failure_keeps_notes_in_memory_and_reports_error(self):
        controller = self.controller(hidden=True)
        note = controller.notes[0]
        note.editor.setPlainText("Не потерять")
        with patch("app.write_json_atomic", side_effect=OSError("Disk full")), \
                patch.object(controller.tray, "showMessage") as notification:
            controller.save_now()
            self.assertTrue(controller._save_failed)
            self.assertEqual(note.save_indicator.state, "error")
            self.assertEqual(note.editor.toPlainText(), "Не потерять")
            notification.assert_called_once()
        controller.save_now()
        self.assertIn("Не потерять", self.saved()["notes"][0]["text"])
        self.assertFalse(controller._save_failed)
        self.assertFalse(hasattr(controller.library, "status"))

    def test_tray_quit_exits_event_loop_and_preserves_open_state(self):
        controller = self.controller()
        note = controller.notes[0]
        note.editor.setPlainText("Сохранить при выходе")
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(lambda: self.qt.exit(2))
        timeout.start(2000)
        QTimer.singleShot(0, controller.menu.actions()[-1].trigger)
        result = self.qt.exec()
        timeout.stop()
        self.assertEqual(result, 0, "Tray Quit must stop the application event loop")
        self.assertTrue(self.saved()["notes"][0]["is_open"])
        self.assertIn("Сохранить при выходе", self.saved()["notes"][0]["text"])


if __name__ == "__main__":
    unittest.main()
