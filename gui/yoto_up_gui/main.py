"""Yoto-UP GUI application entry point."""

import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from yoto_up_gui.app import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Yoto-UP")
    app.setApplicationDisplayName("Yoto-UP Card Manager")

    # Load stylesheet
    try:
        from importlib.resources import files

        style_path = files("yoto_up_gui.resources").joinpath("style.qss")
        app.setStyleSheet(style_path.read_text())
    except Exception:
        pass

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
