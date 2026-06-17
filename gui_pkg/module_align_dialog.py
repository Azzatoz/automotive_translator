"""Диалог расхождений APK ↔ словарь."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.module_align import ModuleDictMismatch, mismatches_to_updates
from gui_pkg.placeholder_editor import apply_placeholder_translations
from gui_pkg.scanner import ModuleInfo
from gui_pkg.theme import AppTheme


class ModuleAlignDialog(QDialog):
    def __init__(
        self,
        module: ModuleInfo,
        mismatches: list[ModuleDictMismatch],
        *,
        theme: AppTheme,
        on_saved: Callable[[ModuleInfo], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._module = module
        self._mismatches = mismatches
        self._theme = theme
        self._on_saved = on_saved

        self.setWindowTitle(f"APK ↔ словарь — {module.display}")
        self.setMinimumSize(720, 480)
        self.resize(860, 560)

        root = QVBoxLayout(self)
        hint = QLabel(
            f"<b>{module.display}</b> — строки, где перевод в APK не совпадает с общим словарём.<br>"
            f"Найдено: <b>{len(mismatches)}</b>. Выберите строки и примените значение из словаря."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for m in mismatches:
            apk = m.apk_ru.replace("\n", " ")
            if len(apk) > 40:
                apk = apk[:37] + "…"
            dict_preview = m.dict_ru.replace("\n", " ")
            if len(dict_preview) > 40:
                dict_preview = dict_preview[:37] + "…"
            item = QListWidgetItem(
                f"{m.resource_id}\nAPK: {apk!r}  →  словарь: {dict_preview!r}"
            )
            item.setData(Qt.ItemDataRole.UserRole, m.row_id)
            self._list.addItem(item)
        root.addWidget(self._list, stretch=1)

        row_btns = QHBoxLayout()
        btn_all = QPushButton("Выделить все")
        btn_all.clicked.connect(self._list.selectAll)
        row_btns.addWidget(btn_all)
        btn_apply_sel = QPushButton("Применить словарь к выделенным")
        btn_apply_sel.clicked.connect(self._apply_selected)
        row_btns.addWidget(btn_apply_sel)
        btn_apply_all = QPushButton("Применить словарь ко всем")
        btn_apply_all.clicked.connect(self._apply_all)
        row_btns.addWidget(btn_apply_all)
        row_btns.addStretch(1)
        root.addLayout(row_btns)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        if mismatches:
            self._list.setCurrentRow(0)

    def _selected_mismatches(self) -> list[ModuleDictMismatch]:
        by_id = {m.row_id: m for m in self._mismatches}
        out: list[ModuleDictMismatch] = []
        for item in self._list.selectedItems():
            row_id = item.data(Qt.ItemDataRole.UserRole)
            m = by_id.get(row_id)
            if m:
                out.append(m)
        return out

    def _apply(self, targets: list[ModuleDictMismatch]) -> None:
        if not targets:
            QMessageBox.information(self, "Применить", "Нет выделенных строк.")
            return
        updates = mismatches_to_updates(targets)
        rows = [m.row for m in self._mismatches]
        _, _, applied = apply_placeholder_translations(self._module.path, rows, updates)
        if not applied:
            QMessageBox.warning(self, "Применить", "Не удалось записать в APK.")
            return
        applied_set = set(applied)
        self._mismatches = [m for m in self._mismatches if m.row_id not in applied_set]
        self._rebuild_list()
        if self._on_saved:
            self._on_saved(self._module)
        QMessageBox.information(
            self,
            "Готово",
            f"Записано в APK: {len(applied)} строк.",
        )
        if not self._mismatches:
            self.accept()

    def _rebuild_list(self) -> None:
        self._list.clear()
        for m in self._mismatches:
            item = QListWidgetItem(
                f"{m.resource_id}\nAPK: {m.apk_ru!r}  →  словарь: {m.dict_ru!r}"
            )
            item.setData(Qt.ItemDataRole.UserRole, m.row_id)
            self._list.addItem(item)

    def _apply_selected(self) -> None:
        self._apply(self._selected_mismatches())

    def _apply_all(self) -> None:
        self._apply(list(self._mismatches))
