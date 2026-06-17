"""Диалог быстрого перевода заглушек модуля."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.backup import backup_module_values_ru
from gui_pkg.confirm import confirm_dangerous_action
from gui_pkg.placeholder_editor import (
    PlaceholderRow,
    apply_placeholder_translations,
    collect_all_module_rows,
    collect_module_placeholders,
    is_untranslated_ru,
    library_placeholder_updates,
    placeholder_dialog_stats,
    prefill_placeholders_from_library,
    row_accepts_ru,
)
from gui_pkg.dictionary_data import load_google_fill_index
from gui_pkg.placeholder_undo import PlaceholderUndoStack
from gui_pkg.similar_translations_dialog import SimilarTranslationsDialog
from gui_pkg.scanner import ModuleInfo
from gui_pkg.theme import AppTheme


class PlaceholdersDialog(QDialog):
    def __init__(
        self,
        module: ModuleInfo,
        *,
        theme: AppTheme,
        on_saved: Callable[[ModuleInfo], None] | None = None,
        find_next_module: Callable[[str | None], ModuleInfo | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._module = module
        self._theme = theme
        self._on_saved = on_saved
        self._find_next_module = find_next_module
        self._next_module: ModuleInfo | None = None
        self._undo = PlaceholderUndoStack()
        self._rows = collect_module_placeholders(module.path)
        prefill_placeholders_from_library(self._rows, module.path)
        self._filtered_indices: list[int] = list(range(len(self._rows)))
        self._dirty: dict[str, str] = {}
        self._current_index: int | None = None
        self._loading_fields = False
        self._status_note = ""
        self._google_index = load_google_fill_index()

        self.setWindowTitle(f"Заглушки — {module.display}")
        self.setMinimumSize(760, 520)
        self.resize(920, 640)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        self._header = QLabel()
        self._header.setWordWrap(True)
        root.addWidget(self._header)

        self._status_label = QLabel()
        self._status_label.setObjectName("hintLabel")
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Фильтр по ресурсу или исходнику…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        root.addWidget(self._filter_edit)

        self._chk_google_only = QCheckBox("Только из отчёта Google (fill)")
        self._chk_google_only.setToolTip(
            "Показать заглушки в APK, для которых перевод уже был получен через Google "
            "(reports/fill_values_ru_google_report.json)"
        )
        self._chk_google_only.stateChanged.connect(self._apply_filter)
        root.addWidget(self._chk_google_only)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._list = QListWidget()
        self._list.setMinimumWidth(280)
        self._list.currentRowChanged.connect(self._on_list_row_changed)
        splitter.addWidget(self._list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)

        self._meta_label = QLabel()
        self._meta_label.setWordWrap(True)
        self._meta_label.setObjectName("hintLabel")
        right_layout.addWidget(self._meta_label)

        src_label = QLabel("Исходник")
        src_label.setObjectName("sectionLabel")
        right_layout.addWidget(src_label)
        self._source_edit = QPlainTextEdit()
        self._source_edit.setReadOnly(True)
        self._source_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._source_edit.setMinimumHeight(100)
        right_layout.addWidget(self._source_edit)

        ru_label = QLabel("Перевод (Ctrl+C / Ctrl+V / Ctrl+X / Ctrl+A)")
        ru_label.setObjectName("sectionLabel")
        right_layout.addWidget(ru_label)
        self._ru_edit = QPlainTextEdit()
        self._ru_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._ru_edit.setMinimumHeight(120)
        self._ru_edit.textChanged.connect(self._on_ru_changed)
        right_layout.addWidget(self._ru_edit)

        ru_tools = QHBoxLayout()
        self._btn_similar = QPushButton("Найти похожие…")
        self._btn_similar.clicked.connect(self._find_similar)
        ru_tools.addWidget(self._btn_similar)
        ru_tools.addStretch(1)
        right_layout.addLayout(ru_tools)

        hint = QLabel(
            "◆ — перевод уже в словаре → «Подставить в APK» (в т.ч. оставить как оригинал). "
            "● — вы правили поле → «В APK и словарь». Ctrl+Z — отмена · Ctrl+Enter — далее."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        right_layout.addWidget(hint)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, stretch=1)

        lib_row = QHBoxLayout()
        self._btn_apply_library = QPushButton("Подставить в APK")
        self._btn_apply_library.setToolTip(
            "Записать в APK перевод из словаря (◆) или из поля — строка исчезнет из списка. "
            "Для «оставить как оригинал» (map13 → map13) — эта кнопка, не «В APK и словарь»."
        )
        self._btn_apply_library.clicked.connect(self._apply_library_current)
        lib_row.addWidget(self._btn_apply_library)
        self._btn_apply_library_all = QPushButton("Подставить всё из словаря")
        self._btn_apply_library_all.setToolTip(
            "Записать в APK все заглушки, для которых перевод уже есть в словаре"
        )
        self._btn_apply_library_all.clicked.connect(self._save_all_from_library)
        lib_row.addWidget(self._btn_apply_library_all)
        self._btn_undo = QPushButton("Отменить")
        self._btn_undo.setToolTip("Ctrl+Z — отменить последнюю запись в APK")
        self._btn_undo.clicked.connect(self._undo_last)
        self._btn_undo.setEnabled(False)
        lib_row.addWidget(self._btn_undo)
        self._btn_undo_all = QPushButton("Отменить всё")
        self._btn_undo_all.setToolTip(
            "Вернуть APK к состоянию до всех записей в этой сессии"
        )
        self._btn_undo_all.clicked.connect(self._undo_all)
        self._btn_undo_all.setEnabled(False)
        lib_row.addWidget(self._btn_undo_all)
        lib_row.addStretch(1)
        root.addLayout(lib_row)

        buttons = QDialogButtonBox()
        self._btn_save = buttons.addButton(
            "В APK и словарь", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._btn_save.setToolTip(
            "Сохранить ручные правки (●) в APK и в общий словарь. "
            "Для строк ◆ без правок используйте «Подставить в APK»."
        )
        self._btn_save_next = buttons.addButton(
            "В APK и словарь · далее", QDialogButtonBox.ButtonRole.ActionRole
        )
        self._btn_next_module = buttons.addButton(
            "Следующий модуль →", QDialogButtonBox.ButtonRole.ActionRole
        )
        self._btn_next_module.clicked.connect(self._go_next_module)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self._save_all)
        self._btn_save_next.clicked.connect(self._save_and_next)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        QShortcut(QKeySequence.StandardKey.Save, self, self._save_all)
        QShortcut(QKeySequence.StandardKey.Undo, self, self._undo_last)
        QShortcut(QKeySequence("Ctrl+Return"), self, self._save_and_next)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self._save_and_next)

        self._update_next_module_button()
        has_google = self._module.name in self._google_index.modules
        self._chk_google_only.setEnabled(has_google)
        if not has_google:
            self._chk_google_only.setChecked(False)
        self._refresh_ui()
        if not self._rows:
            self._meta_label.setText("Нет заглушек для редактирования.")

    def _stats(self) -> dict[str, int]:
        return placeholder_dialog_stats(self._rows, self._dirty)

    def _update_header(self) -> None:
        s = self._stats()
        self._header.setText(
            f"<b>{self._module.display}</b> — заглушки в <b>APK</b> "
            f"(<code>res/values-ru</code>).<br>"
            f"<b>{s['total']}</b> заглушек · "
            f"<b>{s['from_library']}</b> есть в словаре · "
            f"<b>{s['staged']}</b> правок вручную (ещё не в APK) · "
            f"<b>{s['manual']}</b> без перевода в словаре."
        )
        if self._status_note:
            self._status_label.setText(self._status_note)
        else:
            self._status_label.setText(
                "◆ — в словаре есть перевод → «Подставить в APK». "
                "● — правка в поле → «В APK и словарь». Обе кнопки убирают строку из списка."
            )
        self._update_undo_buttons()

    def take_next_module(self) -> ModuleInfo | None:
        n = self._next_module
        self._next_module = None
        return n

    def _update_next_module_button(self) -> None:
        has_next = bool(
            self._find_next_module and self._find_next_module(self._module.name)
        )
        self._btn_next_module.setEnabled(has_next)

    def _go_next_module(self) -> None:
        if not self._find_next_module:
            return
        if self._dirty:
            answer = QMessageBox.question(
                self,
                "Следующий модуль",
                "Есть несохранённые правки. Перейти к следующему модулю?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if self._rows:
            answer = QMessageBox.question(
                self,
                "Следующий модуль",
                f"В модуле осталось {len(self._rows)} заглушек. Перейти дальше?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        nxt = self._find_next_module(self._module.name)
        if nxt is None:
            QMessageBox.information(self, "Модули", "Нет других модулей с заглушками.")
            return
        self._next_module = nxt
        self.accept()

    def _find_similar(self) -> None:
        row = self._row_by_index(self._current_index)
        if row is None:
            return
        dlg = SimilarTranslationsDialog(row.source, row.track, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ru = dlg.selected_ru()
        if not ru:
            return
        self._ru_edit.setPlainText(ru)
        self._dirty[row.row_id] = ru

    def _snapshots_for_updates(self, updates: dict[str, str]) -> dict[str, str]:
        by_id = {r.row_id: r for r in self._rows}
        return {
            row_id: by_id[row_id].ru
            for row_id in updates
            if row_id in by_id
        }

    def _push_undo(self, updates: dict[str, str]) -> None:
        snap = self._snapshots_for_updates(updates)
        if snap:
            self._undo.push(snap)
            self._update_undo_buttons()

    def _update_undo_buttons(self) -> None:
        can = self._undo.can_undo()
        depth = self._undo.depth()
        self._btn_undo.setEnabled(can)
        self._btn_undo_all.setEnabled(depth > 1)
        if can:
            self._btn_undo.setText(f"Отменить ({depth})")
            self._btn_undo_all.setText(
                f"Отменить всё ({depth})" if depth > 1 else "Отменить всё"
            )
        else:
            self._btn_undo.setText("Отменить")
            self._btn_undo_all.setText("Отменить всё")

    def _apply_undo_snapshots(
        self, snapshots: dict[str, str], *, status: str
    ) -> bool:
        if not snapshots:
            return False
        rows = collect_all_module_rows(self._module.path)
        by_id = {r.row_id: r for r in rows}
        updates = {
            rid: old_ru
            for rid, old_ru in snapshots.items()
            if rid in by_id
        }
        if not updates:
            return False
        list_pos = self._list.currentRow()
        backup_module_values_ru(self._module.path)
        apply_placeholder_translations(self._module.path, rows, updates)
        self._reload_rows_after_undo(snapshots)
        self._status_note = status
        self._loading_fields = True
        self._refresh_ui(done=len(self._rows) == 0)
        self._loading_fields = False
        if self._list.count() > 0:
            pos = min(max(list_pos, 0), self._list.count() - 1)
            self._list.blockSignals(True)
            self._list.setCurrentRow(pos)
            self._list.blockSignals(False)
            self._sync_selection_and_fields()
        self._list.viewport().update()
        QApplication.processEvents()
        self._update_undo_buttons()
        if self._on_saved:
            self._on_saved(self._module)
        return True

    def _undo_last(self) -> None:
        record = self._undo.pop()
        if record is None:
            return
        self._apply_undo_snapshots(
            record.snapshots,
            status=f"Отменено: восстановлено {len(record.snapshots)} строк.",
        )

    def _undo_all(self) -> None:
        depth = self._undo.depth()
        if depth <= 1:
            self._undo_last()
            return
        answer = QMessageBox.question(
            self,
            "Отменить всё",
            f"Вернуть APK к состоянию до {depth} записей в этой сессии?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        snapshots = self._undo.drain_merged()
        n = len(snapshots)
        self._apply_undo_snapshots(
            snapshots,
            status=f"Отменено всё: восстановлено {n} строк.",
        )

    def _update_library_buttons(self) -> None:
        lib_updates = library_placeholder_updates(self._rows)
        n = len(lib_updates)
        self._btn_apply_library_all.setEnabled(n > 0)
        self._btn_apply_library_all.setText(
            f"Подставить всё из словаря ({n})" if n else "Подставить всё из словаря"
        )
        row = self._row_by_index(self._current_index)
        if row is None:
            row = self._current_row()
        has_lib = row is not None and self._ru_for_library_apply(row) is not None
        self._btn_apply_library.setEnabled(has_lib)
        self._update_action_buttons()

    def _has_saveable_staged(self) -> bool:
        if not self._dirty:
            return False
        by_id = {r.row_id: r for r in self._rows}
        for row_id, ru_text in self._dirty.items():
            row = by_id.get(row_id)
            if row is not None and row_accepts_ru(row, ru_text):
                return True
        return False

    def _update_action_buttons(self) -> None:
        row = self._row_by_index(self._current_index)
        has_staged = self._has_saveable_staged()
        self._btn_save.setEnabled(has_staged)
        self._btn_save_next.setEnabled(has_staged)
        if row is not None and row.row_id in self._dirty:
            self._btn_apply_library.setText("Только в APK")
            self._btn_apply_library.setToolTip(
                "Записать текст из поля только в APK (без обновления словаря)."
            )
        else:
            self._btn_apply_library.setText("Подставить в APK")
            self._btn_apply_library.setToolTip(
                "Записать в APK перевод из словаря (◆) или из поля. "
                "Для «оставить как оригинал» — эта кнопка."
            )

    def _reload_from_apk(self, *, hide_ids: frozenset[str] | None = None) -> None:
        self._rows = collect_module_placeholders(self._module.path)
        if hide_ids:
            self._rows = [r for r in self._rows if r.row_id not in hide_ids]
        prefill_placeholders_from_library(self._rows, self._module.path)
        self._filtered_indices = []
        remaining_ids = {r.row_id for r in self._rows}
        self._dirty = {k: v for k, v in self._dirty.items() if k in remaining_ids}

    def _reload_rows_after_undo(self, snapshots: dict[str, str]) -> None:
        """Вернуть отменённые заглушки в список (в т.ч. при лаге диска на внешних носителях)."""
        fresh = collect_module_placeholders(self._module.path)
        merged: dict[str, PlaceholderRow] = {r.row_id: r for r in fresh}
        placeholder_snap = {
            rid: old_ru
            for rid, old_ru in snapshots.items()
            if is_untranslated_ru(old_ru)
        }
        if placeholder_snap:
            all_rows = {r.row_id: r for r in collect_all_module_rows(self._module.path)}
            for rid, old_ru in placeholder_snap.items():
                if rid in merged:
                    if not is_untranslated_ru(merged[rid].ru):
                        merged[rid] = replace(merged[rid], ru=old_ru)
                else:
                    base = all_rows.get(rid)
                    if base is not None:
                        merged[rid] = replace(base, ru=old_ru)
        self._rows = sorted(
            merged.values(), key=lambda r: (r.xml_file, r.resource_id)
        )
        prefill_placeholders_from_library(self._rows, self._module.path)
        self._filtered_indices = []
        remaining_ids = {r.row_id for r in self._rows}
        self._dirty = {k: v for k, v in self._dirty.items() if k in remaining_ids}

    def _purge_applied_rows(self, applied_ids: frozenset[str]) -> None:
        """Сразу убрать применённые строки из модели (до/после перечитывания APK)."""
        if not applied_ids:
            return
        for row_id in applied_ids:
            self._dirty.pop(row_id, None)
        self._rows = [r for r in self._rows if r.row_id not in applied_ids]
        if self._current_index is not None:
            row = self._row_by_index(self._current_index)
            if row is None or row.row_id in applied_ids:
                self._current_index = None

    def _after_apk_apply(self, applied_ids: frozenset[str], *, list_pos: int, status: str) -> None:
        """Обновить список и поля после записи в APK."""
        if not applied_ids:
            return
        self._purge_applied_rows(applied_ids)
        self._status_note = status
        self._loading_fields = True
        self._refresh_ui(done=len(self._rows) == 0)
        self._loading_fields = False
        self._reload_from_apk(hide_ids=applied_ids)
        self._loading_fields = True
        self._refresh_ui(done=len(self._rows) == 0)
        self._loading_fields = False
        if self._list.count() > 0:
            pos = min(max(list_pos, 0), self._list.count() - 1)
            self._list.blockSignals(True)
            self._list.setCurrentRow(pos)
            self._list.blockSignals(False)
            self._sync_selection_and_fields()
        self._list.viewport().update()
        QApplication.processEvents()
        if self._on_saved:
            self._on_saved(self._module)

    def _show_empty_state(self, *, done: bool = False) -> None:
        self._current_index = None
        self._list.blockSignals(True)
        self._list.clearSelection()
        if self._list.count() > 0:
            self._list.setCurrentRow(-1)
        self._list.blockSignals(False)
        self._load_fields(None)
        self._meta_label.setText(
            "Все заглушки обработаны." if done else "Нет заглушек для редактирования."
        )
        self._source_edit.setEnabled(False)
        self._ru_edit.setEnabled(False)
        self._btn_apply_library.setEnabled(False)
        self._update_header()
        self._update_library_buttons()

    def _refresh_ui(self, *, done: bool = False) -> None:
        self._update_header()
        self._rebuild_list(sync_fields=False)
        if self._list.count() == 0:
            self._show_empty_state(done=done)
        else:
            self._source_edit.setEnabled(True)
            self._ru_edit.setEnabled(True)
            self._sync_selection_and_fields()
            self._update_library_buttons()

    def _sync_current_index_from_list(self) -> PlaceholderRow | None:
        list_row = self._list.currentRow()
        if list_row < 0 or list_row >= len(self._filtered_indices):
            self._current_index = None
            return None
        self._current_index = self._filtered_indices[list_row]
        return self._rows[self._current_index]

    def _sync_selection_and_fields(self) -> None:
        """Список → _current_index → поля исходник/перевод (всегда после перестройки списка)."""
        if self._list.count() == 0:
            self._current_index = None
            self._load_fields(None)
            return
        list_row = self._list.currentRow()
        if list_row < 0:
            list_row = 0
            self._list.blockSignals(True)
            self._list.setCurrentRow(0)
            self._list.blockSignals(False)
        row = self._sync_current_index_from_list()
        self._load_fields(row)

    def _current_row(self) -> PlaceholderRow | None:
        return self._sync_current_index_from_list()

    def _row_at(self, list_row: int) -> PlaceholderRow | None:
        if list_row < 0 or list_row >= len(self._filtered_indices):
            return None
        return self._rows[self._filtered_indices[list_row]]

    def _rebuild_list(self, *, sync_fields: bool = True) -> None:
        needle = self._filter_edit.text().strip().lower()
        cur = self._list.currentRow()
        prev_row_id: str | None = None
        active = self._row_by_index(self._current_index)
        if active is not None:
            prev_row_id = active.row_id

        self._list.blockSignals(True)
        self._list.clear()
        self._filtered_indices = []
        for i, row in enumerate(self._rows):
            hay = f"{row.resource_id} {row.source} {row.xml_file}".lower()
            if needle and needle not in hay:
                continue
            if self._chk_google_only.isChecked():
                if not self._google_index.matches_row(
                    self._module.name,
                    source=row.source,
                    resource_id=row.resource_id,
                ):
                    continue
            self._filtered_indices.append(i)
            if row.row_id in self._dirty:
                mark = "● "
            elif (
                row.library_ru
                and is_untranslated_ru(row.ru)
                and row_accepts_ru(row, row.library_ru)
            ):
                mark = "◆ "
            else:
                mark = ""
            preview = row.source.replace("\n", " ")
            if len(preview) > 72:
                preview = preview[:69] + "…"
            item = QListWidgetItem(f"{mark}{row.resource_id}\n{preview}")
            item.setData(Qt.ItemDataRole.UserRole, row.row_id)
            self._list.addItem(item)

        next_row = -1
        if prev_row_id:
            for r in range(self._list.count()):
                it = self._list.item(r)
                if it and it.data(Qt.ItemDataRole.UserRole) == prev_row_id:
                    next_row = r
                    break
        if next_row < 0 and self._list.count() > 0:
            if cur >= 0:
                next_row = min(cur, self._list.count() - 1)
            else:
                next_row = 0
        if next_row >= 0:
            self._list.setCurrentRow(next_row)
        elif self._list.count() == 0:
            self._list.setCurrentRow(-1)
        self._list.blockSignals(False)
        if sync_fields and not self._loading_fields:
            if self._list.count() == 0:
                self._current_index = None
                self._load_fields(None)
            else:
                self._sync_selection_and_fields()

    def _apply_filter(self) -> None:
        self._commit_current_edit()
        self._rebuild_list()
        self._update_header()
        self._update_library_buttons()
        if self._list.count() > 0 and self._list.currentRow() < 0:
            self._list.setCurrentRow(0)
        elif self._list.count() == 0:
            self._load_fields(None)

    def _row_by_index(self, index: int | None) -> PlaceholderRow | None:
        if index is None or index < 0 or index >= len(self._rows):
            return None
        return self._rows[index]

    def _commit_current_edit(self) -> None:
        """Сохранить поле «Перевод» в _dirty для текущего _current_index (не по списку!)."""
        row = self._row_by_index(self._current_index)
        if row is None:
            return
        new_ru = self._ru_edit.toPlainText()
        expected = self._resolve_ru_for_row(row)
        if new_ru != expected:
            self._dirty[row.row_id] = new_ru
        elif row.row_id in self._dirty:
            del self._dirty[row.row_id]

    def _on_list_row_changed(self, list_row: int) -> None:
        if self._loading_fields:
            return
        # Сначала зафиксировать правку для старой строки (_current_index), потом переключить.
        self._commit_current_edit()
        row = self._row_at(list_row)
        if row is None:
            self._current_index = None
            self._load_fields(None)
            self._update_library_buttons()
            return
        self._current_index = self._filtered_indices[list_row]
        self._load_fields(row)
        self._update_library_buttons()

    def _resolve_ru_for_row(self, row: PlaceholderRow) -> str:
        if row.row_id in self._dirty:
            return self._dirty[row.row_id]
        if row.library_ru and is_untranslated_ru(row.ru):
            return row.library_ru
        return row.ru

    def _load_fields(self, row: PlaceholderRow | None) -> None:
        self._loading_fields = True
        if row is None:
            self._meta_label.setText("")
            self._source_edit.clear()
            self._ru_edit.clear()
        else:
            track = "EN" if row.track == "en" else "ZH"
            from_lib = (
                row.library_ru
                and is_untranslated_ru(row.ru)
                and self._resolve_ru_for_row(row) == row.library_ru
            )
            lib_note = " · <b>из словаря</b>" if from_lib else ""
            self._meta_label.setText(
                f"<code>{row.xml_file}</code> · <b>{row.resource_id}</b> · трек {track}{lib_note}"
            )
            self._source_edit.setPlainText(row.source)
            self._ru_edit.setPlainText(self._resolve_ru_for_row(row))
        self._loading_fields = False

    def _on_ru_changed(self) -> None:
        if self._loading_fields:
            return
        row = self._row_by_index(self._current_index)
        if row is None:
            return
        self._dirty[row.row_id] = self._ru_edit.toPlainText()
        list_row = self._list.currentRow()
        if list_row >= 0:
            item = self._list.item(list_row)
            if item and not item.text().startswith("● "):
                item.setText("● " + item.text())
        self._update_library_buttons()

    def _collect_valid_updates(self) -> dict[str, str]:
        self._commit_current_edit()
        out: dict[str, str] = {}
        by_id = {r.row_id: r for r in self._rows}
        for row_id, ru_text in self._dirty.items():
            row = by_id.get(row_id)
            if row is None:
                continue
            if row_accepts_ru(row, ru_text):
                out[row_id] = ru_text.strip()
        return out

    def _ru_for_library_apply(self, row: PlaceholderRow) -> str | None:
        """Перевод для «Подставить в APK»: правка в поле или значение из словаря."""
        self._commit_current_edit()
        if row.row_id in self._dirty:
            ru = self._dirty[row.row_id].strip()
            if row_accepts_ru(row, ru):
                return ru
        if row.library_ru and is_untranslated_ru(row.ru):
            ru = row.library_ru.strip()
            if row_accepts_ru(row, ru):
                return ru
        return None

    def _apply_library_current(self) -> None:
        row = self._row_by_index(self._current_index)
        if row is None:
            row = self._current_row()
        if row is None:
            return
        ru = self._ru_for_library_apply(row)
        if not ru:
            return
        applied_id = row.row_id
        resource = row.resource_id
        list_pos = self._list.currentRow()
        self._push_undo({applied_id: ru})
        backup_module_values_ru(self._module.path)
        _, _, applied = apply_placeholder_translations(
            self._module.path, self._rows, {applied_id: ru}
        )
        if applied_id not in applied:
            QMessageBox.warning(
                self,
                "Подставить в APK",
                f"Не удалось записать перевод для {resource}.\n"
                "Проверьте файл values-ru в модуле.",
            )
            return
        self._after_apk_apply(
            applied,
            list_pos=list_pos,
            status=f"Записано в APK: {resource} → {ru!r}",
        )

    def _save_all_from_library(self) -> None:
        updates = library_placeholder_updates(self._rows)
        if not updates:
            QMessageBox.information(
                self,
                "Словарь",
                "Нет заглушек в APK, для которых в общем словаре уже есть перевод.",
            )
            return
        if not confirm_dangerous_action(
            self,
            title="Подставить из словаря",
            summary=f"Записать в APK {len(updates)} переводов из словаря?",
            details="Будет создан бэкап values-ru модуля.",
        ):
            return
        self._push_undo(updates)
        backup_module_values_ru(self._module.path)
        _, _, applied = apply_placeholder_translations(
            self._module.path, self._rows, updates
        )
        if not applied:
            QMessageBox.warning(
                self,
                "Подставить из словаря",
                "Не удалось записать переводы в APK.\nПроверьте файлы values-ru в модуле.",
            )
            return
        self._after_apk_apply(
            applied,
            list_pos=0,
            status=f"Из словаря записано в APK: {len(applied)} строк.",
        )
        QMessageBox.information(
            self,
            "Готово",
            f"Записано в APK: {len(applied)} строк.",
        )

    def _save_all(self, *, quiet: bool = False) -> int:
        updates = self._collect_valid_updates()
        if not updates:
            if not quiet:
                if self._dirty:
                    QMessageBox.information(
                        self,
                        "Сохранение",
                        "Нет готовых ручных правок для записи в словарь.\n\n"
                        "Если перевод уже есть в словаре (◆) и его нужно только "
                        "записать в APK — нажмите «Подставить в APK».\n\n"
                        "Если правили поле — нужен осмысленный перевод "
                        "(не пустой и не заглушка « »).",
                    )
                elif any(
                    r.library_ru and is_untranslated_ru(r.ru) for r in self._rows
                ):
                    QMessageBox.information(
                        self,
                        "Сохранение",
                        "Нет ручных правок (●).\n\n"
                        "Для строк с ◆ (перевод в словаре) используйте "
                        "«Подставить в APK» — в том числе для «оставить как оригинал».",
                    )
                else:
                    QMessageBox.information(self, "Сохранение", "Нет изменений.")
            return 0
        self._push_undo(updates)
        if len(updates) > 1:
            backup_module_values_ru(self._module.path)
        xml_n, dict_n, applied = apply_placeholder_translations(
            self._module.path, self._rows, updates
        )
        if not applied:
            if not quiet:
                QMessageBox.warning(
                    self,
                    "Сохранение",
                    "Не удалось записать переводы в APK.",
                )
            return 0
        list_pos = self._list.currentRow()
        self._after_apk_apply(
            applied,
            list_pos=list_pos,
            status=f"Сохранено в APK: {len(applied)} строк.",
        )
        if not quiet:
            QMessageBox.information(
                self,
                "Сохранено",
                f"Записано в APK: {len(applied)} строк.\nОбновлено в словаре: {dict_n} ключей.",
            )
        return len(applied)

    def _save_and_next(self) -> None:
        list_pos = self._list.currentRow()
        saved = self._save_all(quiet=True)
        if saved <= 0 and self._dirty:
            QMessageBox.information(
                self,
                "Перевод",
                "Текущая строка не сохранена: нужен осмысленный перевод.",
            )
            return
        if self._list.count() == 0:
            self._show_empty_state(done=saved > 0)
            if saved > 0:
                QMessageBox.information(self, "Готово", "Все заглушки обработаны.")
            return
        next_pos = min(max(list_pos, 0), self._list.count() - 1)
        self._list.blockSignals(True)
        self._list.setCurrentRow(next_pos)
        self._list.blockSignals(False)
        self._sync_selection_and_fields()
        if saved > 0 and self._list.count() == 0:
            self._show_empty_state(done=True)
            QMessageBox.information(self, "Готово", "Последняя заглушка в списке обработана.")
