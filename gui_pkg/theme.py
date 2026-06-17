from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PyQt6.QtCore import QObject, QSettings, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

ModuleStatus = Literal["ready", "ready_drift", "placeholders", "conflicts", "unprocessed"]
StatTone = Literal["default", "success", "warning", "danger"]


@dataclass(frozen=True)
class AppTheme:
    """Дизайн-токены и QSS для GUI."""

    bg_app: str
    bg_surface: str
    bg_muted: str
    bg_info: str
    bg_info_hover: str
    bg_success: str
    bg_success_muted: str
    bg_warning: str
    bg_danger: str

    text_primary: str
    text_secondary: str
    text_muted: str
    text_info: str
    text_success: str
    text_success_muted: str
    text_warning: str
    text_danger: str

    border: str
    border_strong: str
    border_info: str

    radius_sm: int = 6
    radius_md: int = 8
    radius_lg: int = 10

    @classmethod
    def light(cls) -> AppTheme:
        return cls(
            bg_app="#f1f5f9",
            bg_surface="#ffffff",
            bg_muted="#f8fafc",
            bg_info="#eff6ff",
            bg_info_hover="#dbeafe",
            bg_success="#dcfce7",
            bg_success_muted="#e4f2ea",
            bg_warning="#fef3c7",
            bg_danger="#fee2e2",
            text_primary="#0f172a",
            text_secondary="#64748b",
            text_muted="#94a3b8",
            text_info="#1d4ed8",
            text_success="#15803d",
            text_success_muted="#4d8f63",
            text_warning="#b45309",
            text_danger="#b91c1c",
            border="#e2e8f0",
            border_strong="#cbd5e1",
            border_info="#3b82f6",
        )

    @classmethod
    def dark(cls) -> AppTheme:
        return cls(
            bg_app="#0f172a",
            bg_surface="#1e293b",
            bg_muted="#334155",
            bg_info="#1e3a5f",
            bg_info_hover="#1e40af",
            bg_success="#14532d",
            bg_success_muted="#1a3d28",
            bg_warning="#78350f",
            bg_danger="#7f1d1d",
            text_primary="#f1f5f9",
            text_secondary="#94a3b8",
            text_muted="#64748b",
            text_info="#60a5fa",
            text_success="#4ade80",
            text_success_muted="#6bc48a",
            text_warning="#fbbf24",
            text_danger="#f87171",
            border="#334155",
            border_strong="#475569",
            border_info="#3b82f6",
        )

    def apply(self, app: QApplication) -> None:
        app.setStyleSheet(self.stylesheet())

    def _check_icon_data_uri(self) -> str:
        return (
            "data:image/svg+xml;charset=utf-8,"
            "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
            "%3Cpath fill='%23ffffff' d='M6.5 11.5L3 8l1-1 2.5 2.5L12 4l1 1z'/%3E"
            "%3C/svg%3E"
        )

    def _radio_icon_data_uri(self) -> str:
        color = self.border_info.replace("#", "%23")
        return (
            "data:image/svg+xml;charset=utf-8,"
            "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
            f"%3Ccircle cx='8' cy='8' r='4.5' fill='{color}'/%3E"
            "%3C/svg%3E"
        )

    def stylesheet(self) -> str:
        t = self
        return f"""
QMainWindow {{
    background: {t.bg_app};
    color: {t.text_primary};
    font-size: 13px;
}}

QWidget#centralRoot {{
    background: {t.bg_app};
}}

QWidget#titleBar {{
    background: {t.bg_surface};
    border-bottom: 1px solid {t.border};
}}

QWidget#sidebarPanel {{
    background: {t.bg_surface};
    border: 1px solid {t.border};
    border-radius: {t.radius_md}px;
}}

QWidget#contentPanel {{
    background: {t.bg_surface};
    border: 1px solid {t.border};
    border-radius: {t.radius_md}px;
}}

QLabel#sectionLabel {{
    color: {t.text_secondary};
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.05em;
}}

QLabel#hintLabel {{
    color: {t.text_secondary};
    font-size: 11px;
}}

QLabel#moduleTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {t.text_primary};
}}

QStatusBar {{
    background: {t.bg_surface};
    border-top: 1px solid {t.border};
    color: {t.text_secondary};
    font-size: 12px;
}}

QPushButton {{
    padding: 5px 14px;
    border: 1px solid {t.border_strong};
    border-radius: {t.radius_sm}px;
    background: {t.bg_surface};
    color: {t.text_primary};
}}
QPushButton:hover {{
    background: {t.bg_muted};
    border-color: {t.border_strong};
}}
QPushButton:pressed {{ background: {t.border}; }}
QPushButton:disabled {{ color: {t.text_muted}; border-color: {t.border}; }}

QPushButton#themeToggleBtn,
QPushButton#faqBtn,
QPushButton#sidebarModeBtn {{
    padding: 4px 8px;
    min-width: 32px;
    font-size: 15px;
}}

QPushButton#actionBtn {{
    padding: 8px 10px;
    text-align: center;
}}

QPushButton#primaryBtn {{
    background: {t.bg_info};
    border-color: {t.border_info};
    color: {t.text_info};
    font-weight: 500;
}}
QPushButton#primaryBtn:hover {{
    background: {t.bg_info_hover};
}}

QGroupBox {{
    font-weight: 500;
    color: {t.text_primary};
    border: 1px solid {t.border};
    border-radius: {t.radius_md}px;
    margin-top: 10px;
    padding: 12px 10px 10px 10px;
    background: {t.bg_surface};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {t.text_secondary};
}}

QListWidget {{
    background: {t.bg_surface};
    border: none;
    outline: none;
}}
QListWidget::item {{
    padding: 0;
    border: none;
    border-bottom: 1px solid {t.border};
    background: {t.bg_surface};
}}
QListWidget::item:selected {{
    background: {t.bg_info};
}}
QListWidget::item:hover:!selected {{
    background: {t.bg_muted};
}}

QTabWidget::pane {{
    border: none;
    background: {t.bg_surface};
    border-top: 1px solid {t.border};
}}
QTabBar {{
    background: {t.bg_surface};
}}
QTabBar::tab {{
    padding: 9px 16px;
    color: {t.text_secondary};
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    background: transparent;
}}
QTabBar::tab:selected {{
    color: {t.text_info};
    border-bottom-color: {t.border_info};
    font-weight: 500;
}}
QTabBar::tab:hover:!selected {{
    color: {t.text_primary};
    background: {t.bg_muted};
}}

QProgressBar {{
    border: none;
    border-radius: 4px;
    background: {t.bg_muted};
    min-height: 6px;
    max-height: 6px;
    text-align: center;
    color: {t.text_secondary};
}}
QProgressBar::chunk {{
    background: {t.text_success};
    border-radius: 4px;
}}

QProgressBar#cmdProgress::chunk {{
    background: {t.border_info};
}}

QLineEdit, QComboBox, QPlainTextEdit {{
    background: {t.bg_muted};
    color: {t.text_primary};
    border: 1px solid {t.border_strong};
    border-radius: {t.radius_sm}px;
    padding: 5px 8px;
    selection-background-color: {t.bg_info};
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {t.border_info};
    background: {t.bg_surface};
}}

QComboBox QAbstractItemView {{
    background: {t.bg_surface};
    border: 1px solid {t.border};
    selection-background-color: {t.bg_info};
    selection-color: {t.text_info};
}}

QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: {t.bg_surface};
}}

QRadioButton, QCheckBox {{
    color: {t.text_primary};
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
}}
QCheckBox::indicator:unchecked {{
    border: 1.5px solid {t.border_strong};
    border-radius: 4px;
    background: {t.bg_surface};
}}
QCheckBox::indicator:unchecked:hover {{
    border-color: {t.border_info};
    background: {t.bg_muted};
}}
QCheckBox::indicator:checked {{
    border: 1.5px solid {t.border_info};
    border-radius: 4px;
    background: {t.border_info};
    image: url({t._check_icon_data_uri()});
}}
QCheckBox::indicator:checked:hover {{
    background: {t.text_info};
    border-color: {t.text_info};
}}
QCheckBox::indicator:disabled {{
    border-color: {t.border};
    background: {t.bg_muted};
}}

QRadioButton::indicator {{
    width: 18px;
    height: 18px;
}}
QRadioButton::indicator:unchecked {{
    border: 1.5px solid {t.border_strong};
    border-radius: 9px;
    background: {t.bg_surface};
}}
QRadioButton::indicator:unchecked:hover {{
    border-color: {t.border_info};
    background: {t.bg_muted};
}}
QRadioButton::indicator:checked {{
    border: 1.5px solid {t.border_info};
    border-radius: 9px;
    background: {t.bg_surface};
    image: url({t._radio_icon_data_uri()});
}}
QRadioButton::indicator:checked:hover {{
    border-color: {t.text_info};
}}
QRadioButton::indicator:disabled {{
    border-color: {t.border};
    background: {t.bg_muted};
}}
"""

    def stat_card_stylesheet(self) -> str:
        t = self
        return f"""
            QFrame#statCard {{
                background: {t.bg_muted};
                border: 1px solid {t.border};
                border-radius: {t.radius_sm}px;
            }}
        """

    def stat_title_style(self) -> str:
        return (
            f"color: {self.text_secondary}; font-size: 11px; "
            "font-weight: 500; letter-spacing: 0.04em;"
        )

    def stat_value_style(self, tone: StatTone, value: str) -> str:
        palettes: dict[StatTone, tuple[str, str]] = {
            "default": (self.text_primary, self.text_muted),
            "success": (self.text_success, self.text_muted),
            "warning": (self.text_warning, self.text_muted),
            "danger": (self.text_danger, self.text_muted),
        }
        active, muted = palettes.get(tone, palettes["default"])
        try:
            n = int(value.replace(" ", ""))
        except ValueError:
            n = -1
        color = active if n > 0 else muted
        return f"font-size: 20px; font-weight: 500; color: {color};"

    def conflict_card_stylesheet(self, *, highlighted: bool = False) -> str:
        t = self
        if highlighted:
            return f"""
                QFrame#conflictEntry {{
                    background: {t.bg_info};
                    border: 2px solid {t.border_info};
                    border-radius: {t.radius_md}px;
                }}
            """
        return f"""
            QFrame#conflictEntry {{
                background: {t.bg_surface};
                border: 1px solid {t.border};
                border-radius: {t.radius_md}px;
            }}
        """

    def conflict_source_label_style(self) -> str:
        return f"color: {self.text_secondary}; font-size: 12px; font-weight: 500;"

    def title_label_style(self) -> str:
        return f"font-size: 13px; font-weight: 500; color: {self.text_primary};"

    def path_label_style(self) -> str:
        return f"font-size: 12px; color: {self.text_secondary};"

    def progress_label_style(self) -> str:
        return f"font-size: 13px; color: {self.text_secondary}; min-width: 80px;"

    def progress_pct_style(self) -> str:
        return (
            f"font-size: 13px; font-weight: 500; color: {self.text_success}; "
            "min-width: 36px;"
        )

    def log_line_color(self, text: str, stream: str) -> QColor:
        stripped = text.strip().lower()
        if "[ok]" in stripped or "[write]" in stripped:
            return QColor(self.text_success)
        if "[warn]" in stripped:
            return QColor(self.text_warning)
        if "[error]" in stripped or stream == "stderr":
            return QColor(self.text_danger)
        return QColor(self.text_secondary)

    def module_row_selected(self, selected: bool) -> str:
        bg = self.bg_info if selected else self.bg_surface
        return f"background: {bg};"

    def module_name_style(self, selected: bool) -> str:
        color = self.text_info if selected else self.text_primary
        return f"color: {color}; font-size: 13px;"

    def badge_stylesheet(self, status: ModuleStatus) -> str:
        mapping: dict[ModuleStatus, tuple[str, str]] = {
            "ready": (self.bg_success, self.text_success),
            "ready_drift": (self.bg_success_muted, self.text_success_muted),
            "placeholders": (self.bg_warning, self.text_warning),
            "conflicts": (self.bg_danger, self.text_danger),
            "unprocessed": (self.bg_muted, self.text_muted),
        }
        bg, fg = mapping.get(status, (self.bg_muted, self.text_muted))
        return (
            f"background: {bg}; color: {fg}; font-size: 11px; "
            "padding: 2px 7px; border-radius: 99px;"
        )


class ThemeManager(QObject):
    """Переключение светлой / тёмной темы с сохранением в QSettings."""

    changed = pyqtSignal()

    def __init__(self, settings: QSettings | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._dark = bool(settings.value("dark_theme", False)) if settings else False

    @property
    def is_dark(self) -> bool:
        return self._dark

    @property
    def current(self) -> AppTheme:
        return AppTheme.dark() if self._dark else AppTheme.light()

    def toggle(self) -> None:
        self._dark = not self._dark
        if self._settings is not None:
            self._settings.setValue("dark_theme", self._dark)
        self.changed.emit()

    def apply(self, app: QApplication) -> None:
        self.current.apply(app)

    def toggle_button_icon(self) -> str:
        return "☀️" if self._dark else "🌙"

    def toggle_button_tooltip(self) -> str:
        return "Светлая тема" if self._dark else "Тёмная тема"


THEME = AppTheme.light()
