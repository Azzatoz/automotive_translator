from __future__ import annotations

import sys

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from gui_pkg.config import SETTINGS_APP, SETTINGS_ORG
from gui_pkg.main_window import MainWindow
from gui_pkg.theme import ThemeManager


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(SETTINGS_APP)
    app.setOrganizationName(SETTINGS_ORG)
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    theme_mgr = ThemeManager(settings)
    theme_mgr.apply(app)
    window = MainWindow(theme_mgr)
    window.show()
    return app.exec()
