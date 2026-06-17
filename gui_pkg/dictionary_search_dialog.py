"""Окно поиска и правки словаря."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QClipboard, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
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

from gui_pkg.dictionary_search import (
    DictSearchHit,
    build_module_index_from_reports,
    filter_hits,
    load_dictionary_hits,
    merge_module_indexes,
    save_dictionary_translation,
    scan_project_module_index,
)
from gui_pkg.theme import AppTheme

_COL_TRACK = 0
_COL_SOURCE = 1
_COL_RU = 2
_COL_MODULES = 3


def _preview(text: str, limit: int = 72) -> str:
    one = text.replace("\n", " ")
    if len(one) <= limit:
        return one
    return one[: limit - 1] + "…"


class _ModuleIndexWorker(QThread):
    finished_index = pyqtSignal(dict)

    def __init__(self, project_root: Path | None, parent=None) -> None:
        super().__init__(parent)
        self._project_root = project_root

    def run(self) -> None:
        base = build_module_index_from_reports()
        if self._project_root and self._project_root.is_dir():
            apk = scan_project_module_index(self._project_root)
            base = merge_module_indexes(base, apk)
        self.finished_index.emit(base)


class DictionarySearchDialog(QDialog):
    def __init__(
        self,
        *,
        project_root: Path | None = None,
        theme: AppTheme,
        on_saved: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_root = project_root
        self._theme = theme
        self._on_saved = on_saved
        self._hits: list[DictSearchHit] = []
        self._filtered: list[DictSearchHit] = []
        self._module_index: dict[str, set[str]] = build_module_index_from_reports()
        self._current: DictSearchHit | None = None
        self._loading_detail = False
        self._index_worker: _ModuleIndexWorker | None = None

        self.setWindowTitle("Поиск в словаре")
        self.setMinimumSize(900, 560)
        self.resize(1040, 680)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        hint = QLabel(
            "Поиск по исходнику, переводу и модулям. Выберите строку — справа можно "
            "отредактировать перевод и сохранить в JSON-словарь."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        filter_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск…")
        self._search.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._search, stretch=2)

        self._track_combo = QComboBox()
        self._track_combo.addItem("Все треки", "all")
        self._track_combo.addItem("en", "en")
        self._track_combo.addItem("zh-CN", "zh-CN")
        self._track_combo.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self._track_combo)

        self._field_combo = QComboBox()
        self._field_combo.addItem("Везде", "all")
        self._field_combo.addItem("Исходник", "source")
        self._field_combo.addItem("Перевод", "ru")
        self._field_combo.addItem("Модули", "module")
        self._field_combo.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self._field_combo)

        self._chk_placeholders = QCheckBox("Только заглушки")
        self._chk_placeholders.stateChanged.connect(self._apply_filter)
        filter_row.addWidget(self._chk_placeholders)
        root.addLayout(filter_row)

        self._summary = QLabel()
        self._summary.setObjectName("hintLabel")
        root.addWidget(self._summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Трек", "Исходник", "Перевод", "Модули"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.setWordWrap(False)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_TRACK, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_SOURCE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_RU, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_MODULES, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self._table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(8, 0, 0, 0)

        detail_layout.addWidget(QLabel("Исходник"))
        self._source_view = QPlainTextEdit()
        self._source_view.setReadOnly(True)
        detail_layout.addWidget(self._source_view, stretch=1)

        detail_layout.addWidget(QLabel("Перевод (редактируемый)"))
        self._ru_edit = QPlainTextEdit()
        self._ru_edit.textChanged.connect(self._on_ru_edited)
        detail_layout.addWidget(self._ru_edit, stretch=2)

        self._modules_label = QLabel("Модули: —")
        self._modules_label.setObjectName("hintLabel")
        self._modules_label.setWordWrap(True)
        detail_layout.addWidget(self._modules_label)

        btn_row = QHBoxLayout()
        self._btn_save = QPushButton("Сохранить в словарь")
        self._btn_save.setObjectName("primaryBtn")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._save_current)
        btn_row.addWidget(self._btn_save)
        btn_copy = QPushButton("Копировать исходник")
        btn_copy.clicked.connect(self._copy_source)
        btn_row.addWidget(btn_copy)
        btn_row.addStretch()
        detail_layout.addLayout(btn_row)

        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, stretch=1)

        bottom = QHBoxLayout()
        self._index_status = QLabel()
        self._index_status.setObjectName("hintLabel")
        bottom.addWidget(self._index_status)
        bottom.addStretch()
        btn_reload = QPushButton("Обновить словарь")
        btn_reload.clicked.connect(self._reload_dictionary)
        bottom.addWidget(btn_reload)
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(btn_close)
        root.addLayout(bottom)

        QShortcut(QKeySequence("Ctrl+F"), self, self._search.setFocus)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_current)

        self._reload_dictionary()
        self._start_module_index_build()

    def closeEvent(self, event) -> None:
        if self._index_worker and self._index_worker.isRunning():
            self._index_worker.requestInterruption()
            self._index_worker.wait(2000)
        super().closeEvent(event)

    def _start_module_index_build(self) -> None:
        if self._project_root and self._project_root.is_dir():
            self._index_status.setText("Индекс модулей: отчёты загружены, сканируем APK проекта…")
        else:
            self._index_status.setText("Индекс модулей: отчёты конфликтов и Google fill.")
            return
        self._index_worker = _ModuleIndexWorker(self._project_root, self)
        self._index_worker.finished_index.connect(self._on_module_index_ready)
        self._index_worker.start()

    def _on_module_index_ready(self, index: dict) -> None:
        self._module_index = index
        self._hits = load_dictionary_hits(self._module_index)
        self._index_status.setText(
            f"Индекс модулей: {len(index)} исходников с привязкой к модулям "
            f"(отчёты + APK проекта)."
        )
        self._apply_filter()

    def _reload_dictionary(self) -> None:
        self._hits = load_dictionary_hits(self._module_index)
        self._apply_filter()

    def _apply_filter(self) -> None:
        track = str(self._track_combo.currentData() or "all")
        field = str(self._field_combo.currentData() or "all")
        query = self._search.text()
        limit = 500
        self._filtered = filter_hits(
            self._hits,
            query,
            track=track,
            field=field,
            placeholders_only=self._chk_placeholders.isChecked(),
            limit=limit,
        )
        self._rebuild_table()
        total = len(self._hits)
        shown = len(self._filtered)
        if query.strip() or track != "all" or self._chk_placeholders.isChecked():
            msg = f"Найдено: {shown}"
            if shown >= limit:
                msg += f" (показаны первые {limit})"
            msg += f" · всего в словарях: {total}"
        else:
            msg = f"Записей в словарях: {total}"
            if shown >= limit:
                msg += f" · показаны первые {limit}"
        self._summary.setText(msg)

    def _rebuild_table(self) -> None:
        sorting = self._table.isSortingEnabled()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        for hit in self._filtered:
            row = self._table.rowCount()
            self._table.insertRow(row)
            track_item = QTableWidgetItem(hit.track)
            track_item.setData(Qt.ItemDataRole.UserRole, hit)
            self._table.setItem(row, _COL_TRACK, track_item)
            src_item = QTableWidgetItem(_preview(hit.source))
            src_item.setToolTip(hit.source)
            self._table.setItem(row, _COL_SOURCE, src_item)
            ru_item = QTableWidgetItem(_preview(hit.ru))
            ru_item.setToolTip(hit.ru)
            if hit.is_placeholder:
                ru_item.setForeground(QColor(self._theme.text_warning))
            self._table.setItem(row, _COL_RU, ru_item)
            mods = ", ".join(hit.modules[:4])
            if len(hit.modules) > 4:
                mods += f" +{len(hit.modules) - 4}"
            mod_item = QTableWidgetItem(mods or "—")
            if hit.modules:
                mod_item.setToolTip("\n".join(hit.modules))
            self._table.setItem(row, _COL_MODULES, mod_item)
        self._table.setSortingEnabled(sorting)
        if self._table.rowCount() > 0 and self._current is None:
            self._table.selectRow(0)

    def _selected_hit(self) -> DictSearchHit | None:
        items = self._table.selectedItems()
        if not items:
            return None
        hit = items[0].data(Qt.ItemDataRole.UserRole)
        return hit if isinstance(hit, DictSearchHit) else None

    def _on_selection_changed(self) -> None:
        hit = self._selected_hit()
        self._current = hit
        self._loading_detail = True
        if hit is None:
            self._source_view.clear()
            self._ru_edit.clear()
            self._modules_label.setText("Модули: —")
            self._btn_save.setEnabled(False)
        else:
            self._source_view.setPlainText(hit.source)
            self._ru_edit.setPlainText(hit.ru)
            if hit.modules:
                self._modules_label.setText("Модули:\n" + "\n".join(hit.modules))
            else:
                self._modules_label.setText("Модули: не найдены в отчётах и проекте")
            self._btn_save.setEnabled(False)
        self._loading_detail = False

    def _on_ru_edited(self) -> None:
        if self._loading_detail or self._current is None:
            return
        changed = self._ru_edit.toPlainText() != self._current.ru
        self._btn_save.setEnabled(changed)

    def _save_current(self) -> None:
        hit = self._current
        if hit is None:
            return
        new_ru = self._ru_edit.toPlainText()
        if new_ru == hit.ru:
            return
        try:
            save_dictionary_translation(hit, new_ru)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Словарь", f"Не удалось сохранить:\n{exc}")
            return
        updated = DictSearchHit(
            track=hit.track,
            source=hit.source,
            ru=new_ru,
            modules=hit.modules,
            is_placeholder=new_ru.strip() == "" or new_ru == " ",
        )
        self._current = updated
        for i, h in enumerate(self._hits):
            if h.track == hit.track and h.source == hit.source:
                self._hits[i] = updated
                break
        for i, h in enumerate(self._filtered):
            if h.track == hit.track and h.source == hit.source:
                self._filtered[i] = updated
                break
        row = self._table.currentRow()
        if row >= 0:
            self._loading_detail = True
            ru_item = QTableWidgetItem(_preview(updated.ru))
            ru_item.setToolTip(updated.ru)
            if updated.is_placeholder:
                ru_item.setForeground(QColor(self._theme.text_warning))
            self._table.setItem(row, _COL_RU, ru_item)
            track_item = self._table.item(row, _COL_TRACK)
            if track_item:
                track_item.setData(Qt.ItemDataRole.UserRole, updated)
            self._ru_edit.setPlainText(updated.ru)
            self._loading_detail = False
        self._btn_save.setEnabled(False)
        if self._on_saved:
            self._on_saved()

    def _copy_source(self) -> None:
        if not self._current or not self._current.source:
            return
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self._current.source, QClipboard.Mode.Clipboard)
