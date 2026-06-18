"""Диалог: записать в APK перевод из общего словаря, если он отличается."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
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
from gui_pkg.module_align import ModuleDictMismatch
from gui_pkg.placeholder_editor import (
    apply_placeholder_translations,
    collect_all_module_rows,
    row_accepts_ru,
)
from gui_pkg.placeholder_undo import PlaceholderUndoStack
from gui_pkg.scanner import ModuleInfo
from gui_pkg.theme import AppTheme

_COL_TEXT = 0
_COL_NAME = 1
_COL_TYPE = 2


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
        self._filtered: list[ModuleDictMismatch] = list(mismatches)
        self._edits: dict[str, str] = {}
        self._loading_detail = False
        self._current_row_id: str | None = None
        self._undo = PlaceholderUndoStack()
        self._undo_mismatches: list[list[ModuleDictMismatch]] = []

        self.setWindowTitle(f"Подстановка из словаря — {module.display}")
        self.setMinimumSize(820, 520)
        self.resize(960, 640)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        header = QLabel(
            f"<b>{module.display}</b> — в <code>values-ru</code> другой текст, чем в общем словаре."
        )
        header.setWordWrap(True)
        root.addWidget(header)

        self._count_label = QLabel()
        self._count_label.setObjectName("hintLabel")
        root.addWidget(self._count_label)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Фильтр по тексту в APK, имени ресурса или типу…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        root.addWidget(self._filter_edit)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["В APK", "Имя", "Тип"])
        self._table.setMinimumWidth(300)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.setWordWrap(False)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self._table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(_COL_TEXT, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSortIndicatorShown(True)
        self._table.currentCellChanged.connect(self._on_table_row_changed)
        splitter.addWidget(self._table)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)

        self._meta_label = QLabel("Выберите строку слева.")
        self._meta_label.setWordWrap(True)
        self._meta_label.setObjectName("hintLabel")
        right_layout.addWidget(self._meta_label)

        src_label = QLabel("Исходник")
        src_label.setObjectName("sectionLabel")
        right_layout.addWidget(src_label)
        self._source_view = QPlainTextEdit()
        self._source_view.setReadOnly(True)
        self._source_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._source_view.setMinimumHeight(80)
        right_layout.addWidget(self._source_view)

        apk_label = QLabel("Сейчас в APK (values-ru)")
        apk_label.setObjectName("sectionLabel")
        right_layout.addWidget(apk_label)
        self._apk_view = QPlainTextEdit()
        self._apk_view.setReadOnly(True)
        self._apk_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._apk_view.setMinimumHeight(64)
        right_layout.addWidget(self._apk_view)

        dict_label = QLabel("В общем словаре")
        dict_label.setObjectName("sectionLabel")
        right_layout.addWidget(dict_label)
        self._dict_view = QPlainTextEdit()
        self._dict_view.setReadOnly(True)
        self._dict_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._dict_view.setMinimumHeight(56)
        right_layout.addWidget(self._dict_view)

        ru_label = QLabel("Новый перевод (для «Записать новую»)")
        ru_label.setObjectName("sectionLabel")
        right_layout.addWidget(ru_label)
        self._ru_edit = QPlainTextEdit()
        self._ru_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._ru_edit.setMinimumHeight(72)
        self._ru_edit.textChanged.connect(self._on_ru_changed)
        right_layout.addWidget(self._ru_edit)

        action_row = QHBoxLayout()
        self._btn_keep = QPushButton("Оставить")
        self._btn_keep.setToolTip("Не менять APK; убрать строку из списка")
        self._btn_keep.clicked.connect(self._keep_current)
        self._btn_keep.setEnabled(False)
        action_row.addWidget(self._btn_keep)

        self._btn_from_dict = QPushButton("Из словаря")
        self._btn_from_dict.setToolTip("Записать в APK перевод из общего словаря")
        self._btn_from_dict.clicked.connect(self._apply_dictionary_current)
        self._btn_from_dict.setEnabled(False)
        action_row.addWidget(self._btn_from_dict)

        self._btn_apply_new = QPushButton("Записать новую")
        self._btn_apply_new.setToolTip("Записать в APK текст из поля «Новый перевод»")
        self._btn_apply_new.clicked.connect(self._apply_new_current)
        self._btn_apply_new.setEnabled(False)
        action_row.addWidget(self._btn_apply_new)

        self._btn_apply_new_dict = QPushButton("Новая + словарь")
        self._btn_apply_new_dict.setObjectName("primaryBtn")
        self._btn_apply_new_dict.setToolTip(
            "Записать в APK текст из поля «Новый перевод» и обновить общий словарь en/zh"
        )
        self._btn_apply_new_dict.clicked.connect(self._apply_new_with_dict_current)
        self._btn_apply_new_dict.setEnabled(False)
        action_row.addWidget(self._btn_apply_new_dict)
        right_layout.addLayout(action_row)

        hint = QLabel(
            "◆ — без правок в поле · ● — правили «Новый перевод». "
            "«Записать новую» — только APK; «Новая + словарь» — APK и JSON en/zh. "
            "Ctrl+Z — отмена последней записи в APK."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        right_layout.addWidget(hint)

        right_layout.addStretch(1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, stretch=1)

        row_btns = QHBoxLayout()
        btn_all = QPushButton("Выделить все")
        btn_all.clicked.connect(self._table.selectAll)
        row_btns.addWidget(btn_all)
        btn_dict_sel = QPushButton("Из словаря (выдел.)")
        btn_dict_sel.setToolTip("Записать в APK перевод из словаря для выделенных строк")
        btn_dict_sel.clicked.connect(self._apply_dictionary_selected)
        row_btns.addWidget(btn_dict_sel)
        btn_apply_sel = QPushButton("Записать новую (выдел.)")
        btn_apply_sel.setToolTip("Записать в APK текст из поля для текущей строки / правки по строкам")
        btn_apply_sel.clicked.connect(self._apply_selected)
        row_btns.addWidget(btn_apply_sel)
        btn_apply_dict_sel = QPushButton("Новая + словарь (выдел.)")
        btn_apply_dict_sel.setToolTip(
            "Записать в APK и обновить словарь en/zh для выделенных строк"
        )
        btn_apply_dict_sel.clicked.connect(self._apply_selected_with_dict)
        row_btns.addWidget(btn_apply_dict_sel)
        btn_keep_sel = QPushButton("Оставить (выдел.)")
        btn_keep_sel.clicked.connect(self._keep_selected)
        row_btns.addWidget(btn_keep_sel)
        self._btn_undo = QPushButton("Отменить")
        self._btn_undo.setToolTip("Ctrl+Z — откатить последнюю запись в APK")
        self._btn_undo.clicked.connect(self._undo_last)
        self._btn_undo.setEnabled(False)
        row_btns.addWidget(self._btn_undo)
        row_btns.addStretch(1)
        root.addLayout(row_btns)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        QShortcut(QKeySequence.StandardKey.Undo, self, self._undo_last)

        self._rebuild_table(select_first=True)
        self._update_undo_buttons()

    def _update_count_label(self) -> None:
        total = len(self._mismatches)
        shown = len(self._filtered)
        if shown == total:
            self._count_label.setText(f"Расхождений: <b>{total}</b>")
        else:
            self._count_label.setText(f"Показано: <b>{shown}</b> из {total}")

    def _draft_for_mismatch(self, m: ModuleDictMismatch) -> str:
        if m.row_id in self._edits:
            return self._edits[m.row_id]
        return m.dict_ru

    def _is_draft_edited(self, m: ModuleDictMismatch) -> bool:
        if m.row_id not in self._edits:
            return False
        return self._edits[m.row_id] != m.dict_ru

    def _track_label(self, m: ModuleDictMismatch) -> str:
        track = (m.row.track or "?").strip().upper()
        if track in ("EN", "ZH"):
            return track
        return track or "?"

    def _text_cell(self, m: ModuleDictMismatch) -> str:
        marker = "● " if self._is_draft_edited(m) else "◆ "
        text = (m.apk_ru or "").replace("\n", " ").strip()
        if not text:
            text = "«пусто»"
        if len(text) > 120:
            text = text[:117] + "…"
        return f"{marker}{text}"

    def _text_cell_tooltip(self, m: ModuleDictMismatch) -> str:
        apk = (m.apk_ru or "").strip()
        src = (m.source or "").strip()
        if src and src != apk:
            return f"values-ru: {apk}\nисходник: {src}"
        return apk or src

    def _make_table_items(
        self, m: ModuleDictMismatch
    ) -> tuple[QTableWidgetItem, QTableWidgetItem, QTableWidgetItem]:
        text_item = QTableWidgetItem(self._text_cell(m))
        text_item.setData(Qt.ItemDataRole.UserRole, m.row_id)
        text_item.setToolTip(self._text_cell_tooltip(m))
        name_item = QTableWidgetItem(m.resource_id)
        name_item.setData(Qt.ItemDataRole.UserRole, m.row_id)
        name_item.setToolTip(f"{m.resource_id}\n{m.row.xml_file}")
        type_item = QTableWidgetItem(self._track_label(m))
        type_item.setData(Qt.ItemDataRole.UserRole, m.row_id)
        type_item.setTextAlignment(
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        )
        return text_item, name_item, type_item

    def _apply_filter(self) -> None:
        self._flush_current_edit()
        needle = self._filter_edit.text().strip().casefold()
        if not needle:
            self._filtered = list(self._mismatches)
        else:
            self._filtered = [
                m
                for m in self._mismatches
                if needle in m.resource_id.casefold()
                or needle in (m.source or "").casefold()
                or needle in (m.apk_ru or "").casefold()
                or needle in (m.dict_ru or "").casefold()
                or needle in self._draft_for_mismatch(m).casefold()
                or needle in self._track_label(m).casefold()
            ]
        self._rebuild_table(select_first=True)

    def _row_id_at(self, table_row: int) -> str | None:
        item = self._table.item(table_row, _COL_TEXT)
        if item is None:
            item = self._table.item(table_row, _COL_NAME)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) else None

    def _table_row_for_id(self, row_id: str) -> int | None:
        for row in range(self._table.rowCount()):
            if self._row_id_at(row) == row_id:
                return row
        return None

    def _select_row_id(self, row_id: str | None, *, first_if_missing: bool = False) -> None:
        if not self._filtered:
            return
        target: int | None = None
        if row_id:
            target = self._table_row_for_id(row_id)
        if target is None and first_if_missing:
            target = 0
        if target is not None:
            self._table.setCurrentCell(target, _COL_TEXT)

    def _rebuild_table(self, *, select_first: bool = False) -> None:
        self._loading_detail = True
        prev_id = self._current_row_id
        sort_col = self._table.horizontalHeader().sortIndicatorSection()
        sort_order = self._table.horizontalHeader().sortIndicatorOrder()

        self._table.blockSignals(True)
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        self._table.setRowCount(len(self._filtered))
        for row, m in enumerate(self._filtered):
            text_item, name_item, type_item = self._make_table_items(m)
            self._table.setItem(row, _COL_TEXT, text_item)
            self._table.setItem(row, _COL_NAME, name_item)
            self._table.setItem(row, _COL_TYPE, type_item)

        self._table.setSortingEnabled(True)
        if sort_col >= 0:
            self._table.sortItems(sort_col, sort_order)

        self._update_count_label()
        self._table.blockSignals(False)

        if self._filtered:
            pick_id = None if select_first else prev_id
            self._select_row_id(pick_id, first_if_missing=True)
            m = self._current_mismatch()
            self._current_row_id = m.row_id if m else None
            self._show_detail(m)
        else:
            self._current_row_id = None
            self._show_detail(None)
        self._loading_detail = False

    def _refresh_table_row(self, m: ModuleDictMismatch) -> None:
        row = self._table_row_for_id(m.row_id)
        if row is None:
            return
        self._table.blockSignals(True)
        sorting = self._table.isSortingEnabled()
        self._table.setSortingEnabled(False)
        text_item, name_item, type_item = self._make_table_items(m)
        self._table.setItem(row, _COL_TEXT, text_item)
        self._table.setItem(row, _COL_NAME, name_item)
        self._table.setItem(row, _COL_TYPE, type_item)
        self._table.setSortingEnabled(sorting)
        self._table.blockSignals(False)

    def _mismatch_by_row_id(self) -> dict[str, ModuleDictMismatch]:
        return {m.row_id: m for m in self._mismatches}

    def _current_mismatch(self) -> ModuleDictMismatch | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        row_id = self._row_id_at(row)
        if not row_id:
            return None
        return self._mismatch_by_row_id().get(row_id)

    def _flush_current_edit(self) -> None:
        if self._current_row_id is None:
            return
        m = self._mismatch_by_row_id().get(self._current_row_id)
        if m is None:
            return
        text = self._ru_edit.toPlainText()
        if text == m.dict_ru:
            self._edits.pop(m.row_id, None)
        else:
            self._edits[m.row_id] = text

    def _on_table_row_changed(
        self,
        current_row: int,
        _current_col: int,
        _prev_row: int,
        _prev_col: int,
    ) -> None:
        if self._loading_detail:
            return
        self._flush_current_edit()
        m = self._current_mismatch() if current_row >= 0 else None
        self._current_row_id = m.row_id if m else None
        self._show_detail(m)

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        self._btn_keep.setEnabled(enabled)
        self._btn_from_dict.setEnabled(enabled)
        self._btn_apply_new.setEnabled(enabled)
        self._btn_apply_new_dict.setEnabled(enabled)

    def _show_detail(self, m: ModuleDictMismatch | None) -> None:
        self._loading_detail = True
        if m is None:
            self._meta_label.setText(
                "Нет строк для показа." if not self._mismatches else "Выберите строку слева."
            )
            self._source_view.clear()
            self._apk_view.clear()
            self._dict_view.clear()
            self._ru_edit.clear()
            self._set_action_buttons_enabled(False)
            self._loading_detail = False
            return
        track = self._track_label(m)
        self._meta_label.setText(
            f"<b>{m.resource_id}</b> · трек {track} · <code>{m.row.xml_file}</code>"
        )
        self._source_view.setPlainText(m.source or "")
        self._apk_view.setPlainText(m.apk_ru or "")
        self._dict_view.setPlainText(m.dict_ru or "")
        self._ru_edit.setPlainText(self._draft_for_mismatch(m))
        self._set_action_buttons_enabled(True)
        self._loading_detail = False

    def _on_ru_changed(self) -> None:
        if self._loading_detail:
            return
        m = self._current_mismatch()
        if m is None:
            return
        text = self._ru_edit.toPlainText()
        if text == m.dict_ru:
            self._edits.pop(m.row_id, None)
        else:
            self._edits[m.row_id] = text
        self._refresh_table_row(m)

    def _selected_mismatches(self) -> list[ModuleDictMismatch]:
        by_id = self._mismatch_by_row_id()
        out: list[ModuleDictMismatch] = []
        seen: set[str] = set()
        for index in self._table.selectedIndexes():
            row_id = self._row_id_at(index.row())
            if not row_id or row_id in seen:
                continue
            seen.add(row_id)
            m = by_id.get(row_id)
            if m:
                out.append(m)
        return out

    def _build_updates_from_drafts(
        self, targets: list[ModuleDictMismatch]
    ) -> dict[str, str]:
        self._flush_current_edit()
        updates: dict[str, str] = {}
        skipped: list[str] = []
        for m in targets:
            ru = self._draft_for_mismatch(m).strip()
            if not row_accepts_ru(m.row, ru):
                skipped.append(m.resource_id)
                continue
            updates[m.row_id] = self._draft_for_mismatch(m)
        if skipped:
            QMessageBox.warning(
                self,
                "Запись в APK",
                "Не подходит для записи (пусто или неверный формат):\n"
                + "\n".join(skipped[:12])
                + ("\n…" if len(skipped) > 12 else ""),
            )
        return updates

    def _build_updates_from_dictionary(
        self, targets: list[ModuleDictMismatch]
    ) -> dict[str, str]:
        updates: dict[str, str] = {}
        skipped: list[str] = []
        for m in targets:
            ru = (m.dict_ru or "").strip()
            if not row_accepts_ru(m.row, ru):
                skipped.append(m.resource_id)
                continue
            updates[m.row_id] = m.dict_ru
        if skipped:
            QMessageBox.warning(
                self,
                "Из словаря",
                "В словаре нет подходящего перевода:\n"
                + "\n".join(skipped[:12])
                + ("\n…" if len(skipped) > 12 else ""),
            )
        return updates

    def _remove_applied(self, row_ids: set[str]) -> None:
        self._mismatches = [m for m in self._mismatches if m.row_id not in row_ids]
        for row_id in row_ids:
            self._edits.pop(row_id, None)
        self._current_row_id = None
        needle = self._filter_edit.text().strip().casefold()
        if needle:
            self._filtered = [
                m
                for m in self._mismatches
                if needle in m.resource_id.casefold()
                or needle in (m.source or "").casefold()
                or needle in (m.apk_ru or "").casefold()
                or needle in (m.dict_ru or "").casefold()
                or needle in self._draft_for_mismatch(m).casefold()
                or needle in self._track_label(m).casefold()
            ]
        else:
            self._filtered = list(self._mismatches)
        self._rebuild_table(select_first=bool(self._filtered))

    def _push_undo(self, mismatches: list[ModuleDictMismatch]) -> None:
        snapshots = {m.row_id: m.apk_ru for m in mismatches}
        if not snapshots:
            return
        self._undo.push(snapshots)
        self._undo_mismatches.append(list(mismatches))
        self._update_undo_buttons()

    def _update_undo_buttons(self) -> None:
        depth = self._undo.depth()
        self._btn_undo.setEnabled(depth > 0)
        self._btn_undo.setText(f"Отменить ({depth})" if depth else "Отменить")

    def _restore_after_undo(self, snapshots: dict[str, str], items: list[ModuleDictMismatch]) -> None:
        if not snapshots:
            return
        rows = collect_all_module_rows(self._module.path)
        row_ids = {r.row_id for r in rows}
        updates = {rid: old for rid, old in snapshots.items() if rid in row_ids}
        if not updates:
            return
        list_pos = self._table.currentRow()
        backup_module_values_ru(self._module.path)
        apply_placeholder_translations(
            self._module.path,
            rows,
            updates,
            update_dictionary=False,
        )
        existing_ids = {m.row_id for m in self._mismatches}
        for m in items:
            old_ru = snapshots.get(m.row_id)
            if old_ru is None:
                continue
            restored = ModuleDictMismatch(
                row=replace(m.row, ru=old_ru),
                dict_ru=m.dict_ru,
            )
            if restored.row_id in existing_ids:
                continue
            if (restored.apk_ru or "").strip() == (restored.dict_ru or "").strip():
                continue
            self._mismatches.append(restored)
            existing_ids.add(restored.row_id)
        self._mismatches.sort(key=lambda x: (x.row.xml_file, x.resource_id))
        self._edits = {k: v for k, v in self._edits.items() if k in existing_ids}
        needle = self._filter_edit.text().strip().casefold()
        if needle:
            self._filtered = [
                m
                for m in self._mismatches
                if needle in m.resource_id.casefold()
                or needle in (m.source or "").casefold()
                or needle in (m.apk_ru or "").casefold()
                or needle in (m.dict_ru or "").casefold()
                or needle in self._draft_for_mismatch(m).casefold()
                or needle in self._track_label(m).casefold()
            ]
        else:
            self._filtered = list(self._mismatches)
        self._rebuild_table(select_first=not self._filtered)
        if self._filtered and list_pos >= 0:
            self._table.setCurrentCell(min(list_pos, len(self._filtered) - 1), _COL_TEXT)
        if self._on_saved:
            self._on_saved(self._module)
        self._update_undo_buttons()

    def _undo_last(self) -> None:
        if not self._undo.can_undo():
            return
        record = self._undo.pop()
        items = self._undo_mismatches.pop() if self._undo_mismatches else []
        if record is None:
            return
        self._restore_after_undo(record.snapshots, items)

    def _apply_updates(
        self,
        updates: dict[str, str],
        *,
        success_title: str,
        update_dictionary: bool = False,
    ) -> None:
        if not updates:
            return
        by_id = self._mismatch_by_row_id()
        undo_items = [by_id[rid] for rid in updates if rid in by_id]
        rows = [m.row for m in self._mismatches]
        _, _, applied = apply_placeholder_translations(
            self._module.path,
            rows,
            updates,
            update_dictionary=update_dictionary,
        )
        if not applied:
            QMessageBox.warning(self, success_title, "Не удалось записать в values-ru.")
            return
        applied_set = set(applied)
        self._push_undo([m for m in undo_items if m.row_id in applied_set])
        self._remove_applied(applied_set)
        if self._on_saved:
            self._on_saved(self._module)
        if not self._mismatches:
            self.accept()

    def _skip_mismatches(self, targets: list[ModuleDictMismatch]) -> None:
        if not targets:
            QMessageBox.information(self, "Оставить", "Нет выделенных строк.")
            return
        skip_ids = {m.row_id for m in targets}
        self._flush_current_edit()
        self._mismatches = [m for m in self._mismatches if m.row_id not in skip_ids]
        for row_id in skip_ids:
            self._edits.pop(row_id, None)
        self._current_row_id = None
        needle = self._filter_edit.text().strip().casefold()
        if needle:
            self._apply_filter()
        else:
            self._filtered = list(self._mismatches)
            self._rebuild_table(select_first=bool(self._mismatches))
        if not self._mismatches:
            self.accept()

    def _keep_current(self) -> None:
        m = self._current_mismatch()
        if m:
            self._skip_mismatches([m])

    def _keep_selected(self) -> None:
        self._skip_mismatches(self._selected_mismatches())

    def _apply_dictionary_current(self) -> None:
        m = self._current_mismatch()
        if not m:
            return
        updates = self._build_updates_from_dictionary([m])
        self._apply_updates(updates, success_title="Из словаря")

    def _apply_dictionary_selected(self) -> None:
        targets = self._selected_mismatches()
        if not targets:
            QMessageBox.information(self, "Из словаря", "Нет выделенных строк.")
            return
        updates = self._build_updates_from_dictionary(targets)
        self._apply_updates(updates, success_title="Из словаря")

    def _apply_new_current(self) -> None:
        m = self._current_mismatch()
        if not m:
            return
        updates = self._build_updates_from_drafts([m])
        self._apply_updates(updates, success_title="Записать новую")

    def _apply_new_with_dict_current(self) -> None:
        m = self._current_mismatch()
        if not m:
            return
        updates = self._build_updates_from_drafts([m])
        self._apply_updates(
            updates,
            success_title="Новая + словарь",
            update_dictionary=True,
        )

    def _apply_selected(self) -> None:
        targets = self._selected_mismatches()
        if not targets:
            QMessageBox.information(self, "Записать новую", "Нет выделенных строк.")
            return
        updates = self._build_updates_from_drafts(targets)
        self._apply_updates(updates, success_title="Записать новую")

    def _apply_selected_with_dict(self) -> None:
        targets = self._selected_mismatches()
        if not targets:
            QMessageBox.information(self, "Новая + словарь", "Нет выделенных строк.")
            return
        updates = self._build_updates_from_drafts(targets)
        self._apply_updates(
            updates,
            success_title="Новая + словарь",
            update_dictionary=True,
        )
