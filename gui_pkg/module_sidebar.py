"""Боковая панель со списком модулей."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.scanner import ModuleInfo, badge_text
from gui_pkg.theme import AppTheme
from gui_pkg.widgets import ModuleListRow


class ModuleSidebar(QWidget):
    """Список модулей с поиском, фильтром и сортировкой."""

    module_selected = pyqtSignal(str)
    module_double_clicked = pyqtSignal(str)
    context_menu_requested = pyqtSignal(object, object)  # QPoint, QListWidgetItem

    def __init__(
        self,
        *,
        theme: AppTheme,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._modules: dict[str, ModuleInfo] = {}
        self._module_rows: dict[str, tuple[QListWidgetItem, ModuleListRow]] = {}
        self._sort_mode = "name"
        self._status_filter = "all"
        self._google_modules: set[str] = set()
        self._sorted_names: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        head = QWidget()
        head_layout = QVBoxLayout(head)
        head_layout.setContentsMargins(14, 12, 14, 8)
        modules_label = QLabel("МОДУЛИ")
        modules_label.setObjectName("sectionLabel")
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Поиск…")
        self._filter_edit.textChanged.connect(self.apply_filter)
        head_layout.addWidget(modules_label)
        head_layout.addWidget(self._filter_edit)

        filter_row = QHBoxLayout()
        self._status_filter_combo = QComboBox()
        self._status_filter_combo.addItem("Все модули", "all")
        self._status_filter_combo.addItem("Нераспакованные APK", "apk_only")
        self._status_filter_combo.addItem("С заглушками", "placeholders")
        self._status_filter_combo.addItem("С конфликтами", "conflicts")
        self._status_filter_combo.addItem("С Google (отчёт)", "google")
        self._status_filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._status_filter_combo, stretch=1)
        self._sort_combo = QComboBox()
        self._sort_combo.addItem("По имени", "name")
        self._sort_combo.addItem("Заглушки ↓", "placeholders")
        self._sort_combo.addItem("Конфликты ↓", "conflicts")
        self._sort_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._sort_combo, stretch=1)
        head_layout.addLayout(filter_row)
        layout.addWidget(head)

        self._list = QListWidget()
        self._list.setToolTip(
            "Двойной щелчок — заглушки (распакованный модуль) или распаковка APK; ПКМ — меню"
        )
        self._list.currentItemChanged.connect(self._on_current_changed)
        self._list.itemDoubleClicked.connect(self._on_double_clicked)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._list)

    @property
    def list_widget(self) -> QListWidget:
        return self._list

    def set_google_modules(self, names: set[str]) -> None:
        self._google_modules = set(names)
        self.apply_filter()

    def set_modules(self, modules: dict[str, ModuleInfo]) -> None:
        self._modules = modules
        self.rebuild_list()

    def rebuild_list(self, *, preserve_selection: str | None = None) -> None:
        selected = preserve_selection or self.current_module_name()
        names = list(self._modules.keys())
        sort_key = self._sort_mode

        def sort_tuple(name: str) -> tuple:
            info = self._modules[name]
            stats = info.stats or {}
            if sort_key == "placeholders":
                return (-int(stats.get("placeholders", 0)), info.display.lower())
            if sort_key == "conflicts":
                return (-int(stats.get("conflicts", 0)), info.display.lower())
            return (info.display.lower(), name.lower())

        names.sort(key=sort_tuple)
        self._sorted_names = names
        self._list.clear()
        self._module_rows.clear()
        for name in names:
            info = self._modules[name]
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setSizeHint(QSize(0, 48))
            row = ModuleListRow(info.display, "…", "unprocessed", theme=self._theme)
            if info.kind == "apk":
                row = ModuleListRow(info.display, "не распакован", "apk_only", theme=self._theme)
            self._list.addItem(item)
            self._list.setItemWidget(item, row)
            self._module_rows[name] = (item, row)
            if info.stats:
                self.update_list_item(name)
        if selected:
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == selected:
                    self._list.setCurrentItem(item)
                    break
        self.apply_filter()

    def sorted_module_names(self) -> list[str]:
        return list(self._sorted_names)

    def current_module_name(self) -> str | None:
        item = self._list.currentItem()
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def set_current_module(self, name: str) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == name:
                self._list.setCurrentItem(item)
                break

    def update_list_item(self, name: str) -> None:
        info = self._modules.get(name)
        row_data = self._module_rows.get(name)
        if not info or not row_data:
            return
        item, row = row_data
        stats = info.stats
        badge = badge_text(stats) if stats else "…"
        status = stats.get("status", "unprocessed") if stats else "unprocessed"
        selected = self._list.currentItem() is item
        row.update_row(info.display, badge, status, selected=selected)

    def refresh_selection_styles(self) -> None:
        current = self.current_module_name()
        for name, (_item, row) in self._module_rows.items():
            row.apply_theme(self._theme)
            info = self._modules.get(name)
            if not info:
                continue
            stats = info.stats or {}
            badge = badge_text(stats) if stats else "…"
            status = stats.get("status", "unprocessed")
            row.update_row(info.display, badge, status, selected=(name == current))

    def apply_filter(self) -> None:
        needle = self._filter_edit.text().strip().lower()
        status_filter = self._status_filter
        for i in range(self._list.count()):
            item = self._list.item(i)
            if not item:
                continue
            name = item.data(Qt.ItemDataRole.UserRole) or ""
            info = self._modules.get(name)
            hay = f"{name} {info.display if info else ''}".lower()
            text_ok = not needle or needle in hay
            status_ok = True
            if info and status_filter != "all":
                st = (info.stats or {}).get("status", "unprocessed")
                if status_filter == "google":
                    status_ok = name in self._google_modules
                elif status_filter == "apk_only":
                    status_ok = info.kind == "apk"
                else:
                    status_ok = st == status_filter
            item.setHidden(not (text_ok and status_ok))

    def apply_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        self.refresh_selection_styles()

    def _on_filter_changed(self) -> None:
        self._status_filter = str(self._status_filter_combo.currentData() or "all")
        self._sort_mode = str(self._sort_combo.currentData() or "name")
        self.rebuild_list()

    def _on_current_changed(self, current: QListWidgetItem | None, _prev) -> None:
        if current:
            name = current.data(Qt.ItemDataRole.UserRole)
            if name:
                self.module_selected.emit(name)

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        if name:
            self.module_double_clicked.emit(name)

    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item:
            self.context_menu_requested.emit(pos, item)
