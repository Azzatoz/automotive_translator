"""Редактор всех строк values-ru модуля с исходником из values-en / values."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.backup import backup_module_values_ru
from gui_pkg.placeholder_editor import (
    PlaceholderRow,
    apply_placeholder_translations,
    collect_all_module_rows,
    row_accepts_ru,
)
from gui_pkg.placeholder_undo import PlaceholderUndoStack
from gui_pkg.scanner import ModuleInfo
from gui_pkg.theme import AppTheme

_COL_SOURCE = 0
_COL_NAME = 1
_COL_TYPE = 2
_COL_RU = 3


def _source_locale_label(module_path) -> str:
    if (module_path / "res" / "values-en").is_dir():
        return "Исходник (values-en)"
    if (module_path / "res" / "values-zh-rCN").is_dir():
        return "Исходник (values-zh-rCN)"
    return "Исходник (values)"


class ValuesRuEditorDialog(QDialog):
    def __init__(
        self,
        module: ModuleInfo,
        *,
        theme: AppTheme,
        on_saved: Callable[[ModuleInfo], None] | None = None,
        initial_filter: str = "",
        focus_row_id: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._module = module
        self._theme = theme
        self._on_saved = on_saved
        self._initial_filter = (initial_filter or "").strip()
        self._focus_row_id = focus_row_id
        self._rows: list[PlaceholderRow] = []
        self._filtered: list[PlaceholderRow] = []
        self._dirty: dict[str, str] = {}
        self._loading_detail = False
        self._current_row_id: str | None = None
        self._undo = PlaceholderUndoStack()
        self._undo_rows: list[list[PlaceholderRow]] = []
        self._source_label = _source_locale_label(module.path)
        self._loaded = False

        self.setWindowTitle(f"values-ru — {module.display}")
        self.setMinimumSize(900, 560)
        self.resize(1040, 680)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        header = QLabel(
            f"<b>{module.display}</b> — правка <code>res/values-ru</code>. "
            f"Слева список строк; справа — {self._source_label.lower()} и редактируемый перевод."
        )
        header.setWordWrap(True)
        root.addWidget(header)

        self._count_label = QLabel()
        self._count_label.setObjectName("hintLabel")
        root.addWidget(self._count_label)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText(
            "Фильтр по исходнику, переводу, имени ресурса или типу…"
        )
        self._filter_edit.textChanged.connect(self._apply_filter)
        root.addWidget(self._filter_edit)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Исходник", "Имя", "Тип", "values-ru"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.setWordWrap(False)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_SOURCE, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_RU, QHeaderView.ResizeMode.Stretch)
        self._table.currentCellChanged.connect(self._on_table_row_changed)
        splitter.addWidget(self._table)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)

        self._meta_label = QLabel("Выберите строку слева.")
        self._meta_label.setObjectName("hintLabel")
        self._meta_label.setWordWrap(True)
        right_layout.addWidget(self._meta_label)

        src_caption = QLabel(self._source_label)
        src_caption.setObjectName("sectionLabel")
        right_layout.addWidget(src_caption)
        self._source_view = QPlainTextEdit()
        self._source_view.setReadOnly(True)
        self._source_view.setMinimumHeight(88)
        right_layout.addWidget(self._source_view)

        ru_caption = QLabel("Перевод (values-ru)")
        ru_caption.setObjectName("sectionLabel")
        right_layout.addWidget(ru_caption)
        self._ru_edit = QPlainTextEdit()
        self._ru_edit.setMinimumHeight(96)
        self._ru_edit.textChanged.connect(self._on_ru_changed)
        right_layout.addWidget(self._ru_edit)

        btn_row = QHBoxLayout()
        self._btn_save = QPushButton("Сохранить строку")
        self._btn_save.setObjectName("primaryBtn")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._save_current)
        btn_row.addWidget(self._btn_save)
        self._btn_save_all = QPushButton("Сохранить все правки")
        self._btn_save_all.setEnabled(False)
        self._btn_save_all.clicked.connect(self._save_all)
        btn_row.addWidget(self._btn_save_all)
        self._btn_undo = QPushButton("Отменить")
        self._btn_undo.setToolTip("Ctrl+Z — откатить последнюю запись")
        self._btn_undo.clicked.connect(self._undo_last)
        self._btn_undo.setEnabled(False)
        btn_row.addWidget(self._btn_undo)
        btn_row.addStretch()
        right_layout.addLayout(btn_row)

        hint = QLabel(
            "● в таблице — несохранённая правка. Запись только в APK; словарь en/zh не меняется. "
            "Ctrl+S — сохранить все правки."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        right_layout.addWidget(hint)
        right_layout.addStretch()
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        QShortcut(QKeySequence.StandardKey.Save, self, self._save_all)
        QShortcut(QKeySequence.StandardKey.Undo, self, self._undo_last)

        self._count_label.setText("Загрузка строк модуля…")
        self._set_actions_enabled(False)
        QTimer.singleShot(0, self._load_rows)

    def _set_actions_enabled(self, enabled: bool) -> None:
        self._btn_save.setEnabled(enabled)
        self._btn_save_all.setEnabled(enabled and any(self._is_dirty(r) for r in self._rows))

    def _load_rows(self) -> None:
        try:
            self._rows = collect_all_module_rows(self._module.path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "values-ru",
                f"Не удалось прочитать модуль «{self._module.display}»:\n{exc}",
            )
            self.reject()
            return
        self._filtered = list(self._rows)
        self._loaded = True
        if self._initial_filter:
            self._filter_edit.blockSignals(True)
            self._filter_edit.setText(self._initial_filter)
            self._filter_edit.blockSignals(False)
            self._apply_filter()
        else:
            self._rebuild_table(select_first=bool(self._rows) and not self._focus_row_id)
        if self._focus_row_id:
            self._select_row_id(self._focus_row_id)
        self._set_actions_enabled(bool(self._rows))
        if not self._rows:
            self._meta_label.setText("Нет переводимых строк в values-ru.")

    def _preview(self, text: str, limit: int = 72) -> str:
        one = (text or "").replace("\n", " ")
        if len(one) <= limit:
            return one
        return one[: limit - 1] + "…"

    def _track_label(self, row: PlaceholderRow) -> str:
        track = (row.track or "?").strip().upper()
        return track if track in ("EN", "ZH") else track or "?"

    def _ru_for_row(self, row: PlaceholderRow) -> str:
        if row.row_id in self._dirty:
            return self._dirty[row.row_id]
        return row.ru

    def _is_dirty(self, row: PlaceholderRow) -> bool:
        if row.row_id not in self._dirty:
            return False
        return self._dirty[row.row_id] != row.ru

    def _row_by_id(self) -> dict[str, PlaceholderRow]:
        return {r.row_id: r for r in self._rows}

    def _update_count_label(self) -> None:
        total = len(self._rows)
        shown = len(self._filtered)
        dirty_n = sum(1 for r in self._rows if self._is_dirty(r))
        if shown == total:
            base = f"Строк: <b>{total}</b>"
        else:
            base = f"Показано: <b>{shown}</b> из {total}"
        if dirty_n:
            base += f" · несохранённых правок: <b>{dirty_n}</b>"
        self._count_label.setText(base)

    def _apply_filter(self) -> None:
        self._flush_current_edit()
        needle = self._filter_edit.text().strip().casefold()
        if not needle:
            self._filtered = list(self._rows)
        else:
            self._filtered = [
                r
                for r in self._rows
                if needle in (r.source or "").casefold()
                or needle in (r.ru or "").casefold()
                or needle in self._ru_for_row(r).casefold()
                or needle in r.resource_id.casefold()
                or needle in self._track_label(r).casefold()
            ]
        self._rebuild_table(select_first=True)

    def _row_id_at(self, table_row: int) -> str | None:
        item = self._table.item(table_row, _COL_SOURCE)
        if item is None:
            item = self._table.item(table_row, _COL_NAME)
        if item is None:
            return None
        val = item.data(Qt.ItemDataRole.UserRole)
        return val if isinstance(val, str) else None

    def _current_row(self) -> PlaceholderRow | None:
        row_idx = self._table.currentRow()
        if row_idx < 0:
            return None
        row_id = self._row_id_at(row_idx)
        if not row_id:
            return None
        return self._row_by_id().get(row_id)

    def _make_items(self, row: PlaceholderRow) -> tuple[QTableWidgetItem, ...]:
        mark = "● " if self._is_dirty(row) else ""
        src_item = QTableWidgetItem(mark + self._preview(row.source))
        src_item.setData(Qt.ItemDataRole.UserRole, row.row_id)
        src_item.setToolTip(row.source)
        name_item = QTableWidgetItem(row.resource_id)
        name_item.setData(Qt.ItemDataRole.UserRole, row.row_id)
        type_item = QTableWidgetItem(self._track_label(row))
        type_item.setData(Qt.ItemDataRole.UserRole, row.row_id)
        ru_item = QTableWidgetItem(mark + self._preview(self._ru_for_row(row)))
        ru_item.setData(Qt.ItemDataRole.UserRole, row.row_id)
        ru_item.setToolTip(self._ru_for_row(row))
        return src_item, name_item, type_item, ru_item

    def _select_row_id(self, row_id: str) -> None:
        for r in range(self._table.rowCount()):
            if self._row_id_at(r) == row_id:
                self._table.setCurrentCell(r, _COL_SOURCE)
                cur = self._current_row()
                self._current_row_id = cur.row_id if cur else None
                self._show_detail(cur)
                break

    def _rebuild_table(self, *, select_first: bool = False) -> None:
        self._loading_detail = True
        prev_id = self._current_row_id
        self._table.blockSignals(True)
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        self._table.setRowCount(len(self._filtered))
        app = QApplication.instance()
        for i, row in enumerate(self._filtered):
            items = self._make_items(row)
            for col, item in enumerate(items):
                self._table.setItem(i, col, item)
            if app is not None and i > 0 and i % 250 == 0:
                app.processEvents()
        self._table.setSortingEnabled(True)
        self._update_count_label()
        self._table.blockSignals(False)

        if self._filtered:
            pick = self._filtered[0].row_id if select_first else prev_id
            for r in range(self._table.rowCount()):
                if self._row_id_at(r) == pick:
                    self._table.setCurrentCell(r, _COL_SOURCE)
                    break
            else:
                self._table.setCurrentCell(0, _COL_SOURCE)
            cur = self._current_row()
            self._current_row_id = cur.row_id if cur else None
            self._show_detail(cur)
        else:
            self._current_row_id = None
            self._show_detail(None)
        self._loading_detail = False

    def _refresh_row(self, row: PlaceholderRow) -> None:
        for r in range(self._table.rowCount()):
            if self._row_id_at(r) == row.row_id:
                items = self._make_items(row)
                for col, item in enumerate(items):
                    self._table.setItem(r, col, item)
                break
        self._update_count_label()
        self._update_dirty_buttons()

    def _flush_current_edit(self) -> None:
        if self._current_row_id is None:
            return
        row = self._row_by_id().get(self._current_row_id)
        if row is None:
            return
        text = self._ru_edit.toPlainText()
        if text == row.ru:
            self._dirty.pop(row.row_id, None)
        else:
            self._dirty[row.row_id] = text

    def _on_table_row_changed(
        self,
        current_row: int,
        _c: int,
        _p: int,
        _pc: int,
    ) -> None:
        if self._loading_detail:
            return
        self._flush_current_edit()
        row = self._current_row() if current_row >= 0 else None
        self._current_row_id = row.row_id if row else None
        self._show_detail(row)

    def _show_detail(self, row: PlaceholderRow | None) -> None:
        self._loading_detail = True
        if row is None:
            self._meta_label.setText(
                "Нет строк." if not self._rows else "Выберите строку слева."
            )
            self._source_view.clear()
            self._ru_edit.clear()
            self._btn_save.setEnabled(False)
            self._loading_detail = False
            return
        self._meta_label.setText(
            f"<b>{row.resource_id}</b> · трек {self._track_label(row)} · "
            f"<code>{row.xml_file}</code>"
        )
        self._source_view.setPlainText(row.source or "")
        self._ru_edit.setPlainText(self._ru_for_row(row))
        self._btn_save.setEnabled(True)
        self._loading_detail = False

    def _on_ru_changed(self) -> None:
        if self._loading_detail:
            return
        row = self._current_row()
        if row is None:
            return
        text = self._ru_edit.toPlainText()
        if text == row.ru:
            self._dirty.pop(row.row_id, None)
        else:
            self._dirty[row.row_id] = text
        self._refresh_row(row)

    def _update_dirty_buttons(self) -> None:
        n = sum(1 for r in self._rows if self._is_dirty(r))
        self._btn_save_all.setEnabled(n > 0)
        depth = self._undo.depth()
        self._btn_undo.setEnabled(depth > 0)
        self._btn_undo.setText(f"Отменить ({depth})" if depth else "Отменить")

    def _collect_updates(self, row_ids: set[str] | None = None) -> dict[str, str]:
        self._flush_current_edit()
        by_id = self._row_by_id()
        updates: dict[str, str] = {}
        skipped: list[str] = []
        for row_id, ru_text in self._dirty.items():
            if row_ids is not None and row_id not in row_ids:
                continue
            row = by_id.get(row_id)
            if row is None:
                continue
            if not row_accepts_ru(row, ru_text):
                skipped.append(row.resource_id)
                continue
            updates[row_id] = ru_text
        if skipped:
            QMessageBox.warning(
                self,
                "Сохранение",
                "Не подходит для записи:\n"
                + "\n".join(skipped[:12])
                + ("\n…" if len(skipped) > 12 else ""),
            )
        return updates

    def _apply_updates(self, updates: dict[str, str]) -> bool:
        if not updates:
            return False
        snapshots = {
            rid: self._row_by_id()[rid].ru
            for rid in updates
            if rid in self._row_by_id()
        }
        if len(updates) > 1:
            backup_module_values_ru(self._module.path)
        _, _, applied = apply_placeholder_translations(
            self._module.path,
            self._rows,
            updates,
            update_dictionary=False,
        )
        if not applied:
            QMessageBox.warning(self, "Сохранение", "Не удалось записать в values-ru.")
            return False
        self._undo.push(snapshots)
        self._undo_rows.append(list(self._rows))
        by_id = self._row_by_id()
        for row_id in applied:
            row = by_id.get(row_id)
            if row is None:
                continue
            new_ru = updates[row_id]
            idx = self._rows.index(row)
            self._rows[idx] = replace(row, ru=new_ru)
            self._dirty.pop(row_id, None)
        needle = self._filter_edit.text().strip().casefold()
        if needle:
            self._apply_filter()
        else:
            self._filtered = list(self._rows)
            self._rebuild_table()
        if self._on_saved:
            self._on_saved(self._module)
        self._update_dirty_buttons()
        return True

    def _save_current(self) -> None:
        row = self._current_row()
        if row is None:
            return
        updates = self._collect_updates({row.row_id})
        if updates:
            backup_module_values_ru(self._module.path)
            self._apply_updates(updates)

    def _save_all(self) -> None:
        updates = self._collect_updates()
        if not updates:
            QMessageBox.information(self, "Сохранение", "Нет несохранённых правок.")
            return
        self._apply_updates(updates)

    def _undo_last(self) -> None:
        record = self._undo.pop()
        rows_snapshot = self._undo_rows.pop() if self._undo_rows else None
        if record is None:
            return
        backup_module_values_ru(self._module.path)
        apply_placeholder_translations(
            self._module.path,
            self._rows,
            record.snapshots,
            update_dictionary=False,
        )
        if rows_snapshot:
            self._rows = rows_snapshot
        else:
            by_id = {r.row_id: r for r in self._rows}
            for row_id, old_ru in record.snapshots.items():
                row = by_id.get(row_id)
                if row:
                    idx = self._rows.index(row)
                    self._rows[idx] = replace(row, ru=old_ru)
        self._dirty = {
            k: v for k, v in self._dirty.items() if k not in record.snapshots
        }
        self._apply_filter() if self._filter_edit.text().strip() else self._rebuild_table()
        if self._on_saved:
            self._on_saved(self._module)
        self._update_dirty_buttons()
