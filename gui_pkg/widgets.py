from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QMouseEvent, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.theme import THEME, AppTheme, StatTone


class LogView(QPlainTextEdit):
    def __init__(self, theme: AppTheme = THEME, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self.setFont(mono)

    def append_line(self, text: str, stream: str = "stdout") -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(self._theme.log_line_color(text, stream))
        cursor.setCharFormat(fmt)
        cursor.insertText(text.rstrip("\n") + "\n")
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def apply_theme(self, theme: AppTheme) -> None:
        self._theme = theme


class StatCard(QFrame):
    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        tone: StatTone = "default",
        theme: AppTheme = THEME,
    ) -> None:
        super().__init__(parent)
        self._tone = tone
        self._theme = theme
        self.setObjectName("statCard")
        self.setStyleSheet(theme.stat_card_stylesheet())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self._title = QLabel(title)
        self._title.setStyleSheet(theme.stat_title_style())
        self._value = QLabel("—")
        self._apply_value_style("—")
        layout.addWidget(self._title)
        layout.addWidget(self._value)

    def _apply_value_style(self, value: str) -> None:
        self._value.setStyleSheet(self._theme.stat_value_style(self._tone, value))

    def set_value(self, value: str) -> None:
        self._value.setText(value)
        self._apply_value_style(value)

    def apply_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        self.setStyleSheet(theme.stat_card_stylesheet())
        self._title.setStyleSheet(theme.stat_title_style())
        self._apply_value_style(self._value.text())


class ModuleListRow(QWidget):
    """Строка модуля: имя + цветной бейдж (как в HTML-макете)."""

    def __init__(
        self,
        display: str,
        badge: str,
        status: str,
        *,
        selected: bool = False,
        theme: AppTheme = THEME,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._display = display
        self._badge = badge
        self._status = status
        self._selected = selected
        self.setStyleSheet(theme.module_row_selected(selected))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)
        self._name = QLabel(display)
        self._name.setStyleSheet(theme.module_name_style(selected))
        self._badge_label = QLabel(badge)
        self._badge_label.setStyleSheet(theme.badge_stylesheet(status))  # type: ignore[arg-type]
        self._badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._name, stretch=1)
        layout.addWidget(self._badge_label)

    def update_row(
        self,
        display: str,
        badge: str,
        status: str,
        *,
        selected: bool,
    ) -> None:
        self._display = display
        self._status = status
        self._selected = selected
        self.setStyleSheet(self._theme.module_row_selected(selected))
        self._name.setText(display)
        self._name.setStyleSheet(self._theme.module_name_style(selected))
        self._badge_label.setText(badge)
        self._badge_label.setStyleSheet(self._theme.badge_stylesheet(status))  # type: ignore[arg-type]

    def apply_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        self.update_row(
            self._display,
            self._badge_label.text(),
            self._status,
            selected=self._selected,
        )


class ConflictEntryWidget(QFrame):
    """Карточка конфликта: клик по блоку — выделить для сохранения, радио — вариант перевода."""

    chosen_changed = pyqtSignal()
    highlight_changed = pyqtSignal()

    def __init__(
        self,
        track: str,
        item: dict[str, Any],
        parent: QWidget | None = None,
        theme: AppTheme = THEME,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.track = track
        self.source = str(item.get("source") or "")
        self._highlighted = False
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.buttonClicked.connect(lambda: self.chosen_changed.emit())

        self.setObjectName("conflictEntry")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self._mark_label = QLabel("Кликните по блоку, чтобы выделить для сохранения")
        self._mark_label.setStyleSheet(f"color: {theme.text_muted}; font-size: 11px;")
        header.addWidget(self._mark_label, stretch=1)
        layout.addLayout(header)

        track_label = {"en": "английский", "zh-CN": "китайский"}.get(track, track)
        src_label = QLabel(f"Исходная строка ({track_label})")
        src_label.setStyleSheet(theme.conflict_source_label_style())
        src_text = QLabel(self.source)
        src_text.setWordWrap(True)
        src_text.setStyleSheet(f"color: {theme.text_primary}; font-size: 13px;")
        src_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(src_label)
        layout.addWidget(src_text)

        translations = item.get("translations") or {}
        chosen = str(item.get("chosen") or "")
        if not isinstance(translations, dict):
            translations = {}

        for ru_text, mod_list in translations.items():
            mods = mod_list if isinstance(mod_list, list) else []
            mod_str = ", ".join(str(m) for m in mods[:6])
            if len(mods) > 6:
                mod_str += f" … (+{len(mods) - 6})"
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            rb = QRadioButton()
            rb.setProperty("ru_value", ru_text)
            rb.setCursor(Qt.CursorShape.ArrowCursor)
            row_layout.addWidget(rb, alignment=Qt.AlignmentFlag.AlignTop)
            text = QLabel(
                f"{ru_text}\n<span style='color:{theme.text_secondary}'>встречается в: {mod_str}</span>"
            )
            text.setTextFormat(Qt.TextFormat.RichText)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text.setCursor(Qt.CursorShape.IBeamCursor)
            row_layout.addWidget(text, stretch=1)
            if ru_text == chosen or (not chosen and not self._group.buttons()):
                rb.setChecked(True)
            self._group.addButton(rb)
            layout.addWidget(row)

        if not self._group.buttons() and chosen:
            rb = QRadioButton(chosen)
            rb.setProperty("ru_value", chosen)
            rb.setChecked(True)
            rb.setCursor(Qt.CursorShape.ArrowCursor)
            self._group.addButton(rb)
            layout.addWidget(rb)

        for child in self.findChildren(QWidget):
            child.installEventFilter(self)
        self.installEventFilter(self)
        self._apply_card_style()

    def _apply_card_style(self) -> None:
        self.setStyleSheet(self._theme.conflict_card_stylesheet(highlighted=self._highlighted))
        if self._highlighted:
            self._mark_label.setText("✓ Выделено для сохранения")
            self._mark_label.setStyleSheet(
                f"color: {self._theme.text_info}; font-size: 11px; font-weight: 500;"
            )
        else:
            self._mark_label.setText("Кликните по блоку, чтобы выделить для сохранения")
            self._mark_label.setStyleSheet(f"color: {self._theme.text_muted}; font-size: 11px;")

    def is_highlighted(self) -> bool:
        return self._highlighted

    def set_highlighted(self, highlighted: bool) -> None:
        if self._highlighted == highlighted:
            return
        self._highlighted = highlighted
        self._apply_card_style()
        self.highlight_changed.emit()

    def toggle_highlighted(self) -> None:
        self.set_highlighted(not self._highlighted)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
            and not isinstance(obj, QRadioButton)
        ):
            self.toggle_highlighted()
            return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_highlighted()
            event.accept()
            return
        super().mousePressEvent(event)

    def apply_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        self._apply_card_style()
        for label in self.findChildren(QLabel):
            if label is self._mark_label:
                continue
            if "Исходная строка" in (label.text() or ""):
                label.setStyleSheet(theme.conflict_source_label_style())
            elif label.text() == self.source:
                label.setStyleSheet(f"color: {theme.text_primary}; font-size: 13px;")

    def get_chosen(self) -> str:
        btn = self._group.checkedButton()
        if btn is None:
            return ""
        return str(btn.property("ru_value") or btn.text())
