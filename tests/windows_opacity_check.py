"""Verify live opacity against actual Windows compositor pixels, without folding."""
from collections import Counter
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import ImageGrab
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from config import DEFAULTS
from note_window import M, NoteWindow, new_note_data


def capture(window):
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(wintypes.HWND(int(window.winId())), ctypes.byref(rect))
    return ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), include_layered_windows=True)


def tone(image, window, point):
    x, y = point
    sx, sy = image.width / window.width(), image.height / window.height()
    area = image.crop((round(x * sx), round(y * sy), round((x + 14) * sx), round((y + 12) * sy)))
    return Counter(area.get_flattened_data()).most_common(1)[0][0]


def main():
    if sys.platform != "win32":
        raise SystemExit("This check requires Windows.")
    app = QApplication([])
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)
    settings = dict(DEFAULTS, hover_controls=False, corner_radius=5)
    note = NoteWindow(new_note_data(settings), settings)
    backdrop = QWidget()
    backdrop.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    backdrop.setStyleSheet("background: #234567;")
    backdrop.resize(note.width() + 40, note.height() + 40)
    area = app.primaryScreen().availableGeometry()
    backdrop.move(area.left() + 60, area.top() + 50)
    note.move(backdrop.x() + 20, backdrop.y() + 20)
    note.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    background = QColor("#234567").getRgb()[:3]
    positions = {"header": (M + 180, M + 12), "body": (M + 180, M + 100)}
    try:
        backdrop.show()
        note.show()
        note.raise_()
        QTest.qWait(350)
        native_id = int(note.winId())
        for menu_open in (False, True):
            if menu_open:
                note.show_menu()
            note.set_opacity(100)
            QTest.qWait(200)
            opaque = capture(note)
            source = {key: tone(opaque, note, point) for key, point in positions.items()}
            for value in (40, 70, 100, 55, 100):
                note.set_opacity(value)
                QTest.qWait(220)
                image = capture(note)
                alpha = note.windowOpacity()
                for key, point in positions.items():
                    actual = tone(image, note, point)
                    expected = tuple(round(foreground * alpha + behind * (1 - alpha))
                                     for foreground, behind in zip(source[key], background))
                    assert max(abs(a - b) for a, b in zip(actual, expected)) <= 3, (
                        f"{key}, options={menu_open}, opacity={value}: {actual} != {expected}")
                assert int(note.winId()) == native_id
                assert not note.data["collapsed"]
        print(f"Live Windows opacity at scale {app.primaryScreen().devicePixelRatio():g}: PASS")
    finally:
        note.hide()
        backdrop.hide()


if __name__ == "__main__":
    main()
