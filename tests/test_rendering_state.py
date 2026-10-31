"""Regressions for save feedback, uniform opacity, and list-marker geometry."""
import unittest
from unittest.mock import patch

from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

import test_notes
from note_window import M


class RenderingStateTests(unittest.TestCase):
    setUp = test_notes.NotesLifecycleTests.setUp
    tearDown = test_notes.NotesLifecycleTests.tearDown
    controller = test_notes.NotesLifecycleTests.controller
    saved = test_notes.NotesLifecycleTests.saved

    @classmethod
    def setUpClass(cls):
        test_notes.NotesLifecycleTests.setUpClass()
        cls.qt = test_notes.NotesLifecycleTests.qt

    def test_geometry_and_window_actions_do_not_animate_content_save(self):
        controller = self.controller()
        note = controller.notes[0]
        controller.save_now()
        with patch.object(note.save_indicator, "saved") as flash:
            for action in (
                lambda: note.set_collapsed(True), lambda: note.set_collapsed(False),
                lambda: note.move(note.x() + 5, note.y() + 5),
                lambda: note.resize(note.width() + 8, note.height() + 8),
                lambda: note.set_color("#BFE3FF"), lambda: note.set_font_size(14),
                lambda: note.set_opacity(70), note.show_menu, note.show_menu,
            ):
                action()
                controller.save_now()
                flash.assert_not_called()
            note.focus_editor()
            note.editor.insertPlainText("Actual content edit")
            controller.save_now()
            flash.assert_called_once()

    def test_folding_pending_content_saves_it_without_showing_a_check(self):
        controller = self.controller()
        note = controller.notes[0]
        note.editor.insertPlainText("Save while folding")
        note.set_collapsed(True)
        with patch.object(note.save_indicator, "saved") as flash:
            controller.save_now()
            flash.assert_not_called()
        self.assertIn("Save while folding", self.saved()["notes"][0]["text"])
        self.assertEqual(note.save_indicator.state, "clean")

    def test_note_surfaces_stay_opaque_while_window_opacity_changes_live(self):
        controller = self.controller()
        note = controller.notes[0]
        note.focus_editor()
        native_id = int(note.winId())
        note.set_opacity(50)
        QTest.qWait(180)
        image = note.grab().toImage()
        ratio = image.devicePixelRatio()
        x = round((M + 200) * ratio)
        header = image.pixelColor(x, round((M + 20) * ratio)).alpha()
        body = image.pixelColor(x, round((M + 100) * ratio)).alpha()
        note.show_menu()
        QTest.qWait(80)
        image = note.grab().toImage()
        panel = image.pixelColor(x, round((M + 100) * ratio)).alpha()
        self.assertEqual((header, body, panel), (255, 255, 255))
        self.assertAlmostEqual(note.windowOpacity(), .5, delta=.01)
        note.set_opacity(100)
        self.assertAlmostEqual(note.windowOpacity(), 1, delta=.01)
        self.assertEqual(int(note.winId()), native_id)
        self.assertFalse(note.data["collapsed"])

    def test_library_has_no_bottom_status_and_deletion_never_prompts(self):
        controller = self.controller()
        self.assertFalse(hasattr(controller.library, "status"))
        note = controller.notes[0]
        note.editor.setPlainText("Delete immediately")
        with patch.object(QMessageBox, "exec", side_effect=AssertionError("Deletion must not prompt")):
            controller.delete_note(note)
        self.assertEqual(self.saved()["notes"], [])

    def test_checkbox_and_text_ink_share_visual_center(self):
        controller = self.controller()
        controller.s.update(font_family="Segoe UI Symbol")
        note = controller.notes[0]
        note.editor.setPlainText("XXXX")
        note.toggle_tasks()
        note.focus_editor()
        QTest.qWait(200)
        rect = note.editor.cursorRect(QTextCursor(note.editor.document().begin()))
        image = note.editor.viewport().grab().toImage()
        ratio = image.devicePixelRatio()
        text_x = round(rect.left() * ratio)

        def ink_rows(left, right):
            rows = []
            for y in range(max(0, round((rect.top() - 4) * ratio)),
                           min(image.height(), round((rect.bottom() + 5) * ratio))):
                for x in range(max(0, left), min(image.width(), right)):
                    color = image.pixelColor(x, y)
                    if color.alpha() > 200 and max(color.red(), color.green(), color.blue()) < 100:
                        rows.append(y)
                        break
            self.assertTrue(rows, "Expected visible marker/text ink")
            return (min(rows) + max(rows)) / 2

        marker_center = ink_rows(text_x - round(23 * ratio), text_x - round(2 * ratio))
        text_center = ink_rows(text_x, text_x + round(65 * ratio))
        self.assertLessEqual(abs(marker_center - text_center), ratio)

    def test_rounded_header_and_options_do_not_fill_outside_paper_corners(self):
        controller = self.controller()
        note = controller.notes[0]
        controller.s.update(corner_radius=5)
        note.focus_editor()
        QTest.qWait(180)
        image = note.grab().toImage()
        ratio = image.devicePixelRatio()
        x, y = round((M + 1) * ratio), round((M + 1) * ratio)
        self.assertLess(image.pixelColor(x, y).alpha(), 240)
        note.show_menu()
        QTest.qWait(80)
        image = note.grab().toImage()
        y = round((note.height() - M - 2) * ratio)
        self.assertLess(image.pixelColor(x, y).alpha(), 240)
