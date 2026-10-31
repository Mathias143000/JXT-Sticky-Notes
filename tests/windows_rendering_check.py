"""Check actual Windows pixels; QWidget.grab() hides partial-repaint artifacts.

Run with the build dependencies installed: python tests/windows_rendering_check.py
Only temporary test windows and fixture text are captured, without real note data.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import ImageChops, ImageGrab
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from config import DEFAULTS
from note_window import M, NoteWindow, new_note_data
from notes_list import NotesListWindow


def screen_pixels(widget):
    """Capture the compositor output without forcing Qt to repaint the widget."""
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(wintypes.HWND(int(widget.winId())), ctypes.byref(rect))
    image = ImageGrab.grab(
        bbox=(rect.left, rect.top, rect.right, rect.bottom), include_layered_windows=True)
    # Exclude the transparent outer margin, where other applications may change.
    # Inset in logical coordinates before converting to physical pixels. At
    # fractional DPI a symmetric integer crop can retain half a transparent
    # bottom edge, whose pixels legitimately depend on the desktop behind it.
    sx, sy = image.width / widget.width(), image.height / widget.height()
    inset = M + 2
    return image.crop((math.ceil(inset * sx), math.ceil(inset * sy),
                       math.floor((widget.width() - inset) * sx),
                       math.floor((widget.height() - inset) * sy)))


def main():
    if sys.platform != "win32":
        raise SystemExit("This check requires a Windows desktop.")
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qt = QApplication([])
    qt.setStyle("Fusion")
    qt.setQuitOnLastWindowClosed(False)
    qt.setCursorFlashTime(0)
    print(f"Windows scale: {qt.primaryScreen().devicePixelRatio():g}")
    # Keep chrome fixed to isolate glyph corruption from intentional animations.
    settings = dict(DEFAULTS, hover_controls=False)
    note = NoteWindow(new_note_data(settings), settings)
    library = NotesListWindow()
    sample = "Render test ABC 0123456789\nSecond line / Проверка текста"
    note.editor.setPlainText(sample)
    note.editor.setReadOnly(True)
    library.set_notes([{
        "id": "fixture", "color": "#FFF7CE", "preview": sample,
        "updated_at": "2026-10-31T13:00:00+00:00",
    }])
    library.search.setReadOnly(True)
    library.resize(404, 430)
    area = qt.primaryScreen().availableGeometry()
    library.move(area.left() + 24, area.top() + 24)
    note.move(area.left() + 460, area.top() + 24)
    windows = {"note": note, "library": library}
    try:
        for widget in windows.values():
            widget.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            widget.show()
        QTest.mouseMove(library.header, QPoint(100, 15))
        QTest.qWait(700)
        before = {name: screen_pixels(widget) for name, widget in windows.items()}
        for _ in range(3):
            library.search.setText("no matching note")
            note.editor.clear()
            QTest.qWait(80)
            library.search.clear()
            note.editor.setPlainText(sample)
            QTest.qWait(100)
        note_size = note.size()
        library_size = library.size()
        note.set_collapsed(True)
        QTest.qWait(180)
        note.set_collapsed(False)
        note.resize(note_size.width() + 45, note_size.height() + 37)
        library.resize(library_size.width() + 45, library_size.height() + 37)
        QTest.qWait(100)
        note.resize(note_size)
        library.resize(library_size)
        note.save_indicator.saved()
        QTest.qWait(1350)
        QTest.qWait(250)
        failures = []
        for name, widget in windows.items():
            after = screen_pixels(widget)
            difference = ImageChops.difference(before[name], after)
            # Histogram counts pixels changed in any color channel, independent
            # of antialiasing intensity. Identical UI must produce identical pixels.
            mask = difference.point(lambda value: 255 if value else 0).convert("L")
            changed = mask.width * mask.height - mask.histogram()[0]
            print(f"{name}: {changed} changed pixels after restoring identical content")
            if changed:
                artifacts = Path(__file__).resolve().parents[1] / "build" / "rendering-check"
                artifacts.mkdir(parents=True, exist_ok=True)
                before[name].save(artifacts / f"{name}-before.png")
                after.save(artifacts / f"{name}-after.png")
                difference.save(artifacts / f"{name}-difference.png")
                failures.append(name)
        if failures:
            raise AssertionError("Stale pixels in: " + ", ".join(failures))
        print("Windows rendering: PASS")
    finally:
        for widget in windows.values():
            widget.hide()
            widget.deleteLater()
        qt.processEvents()


if __name__ == "__main__":
    main()
