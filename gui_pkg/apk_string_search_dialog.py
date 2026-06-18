"""Диалог поиска подстроки в values-ru по всем модулям."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.apk_string_search import ApkRuSearchHit, search_all_modules
from gui_pkg.scanner import ModuleInfo
from gui_pkg.theme import AppTheme

_COL_MODULE = 0
_COL_RESOURCE = 1
_COL_RU = 2


class _SearchWorker(QThread):
    finished_hits = pyqtSignal(list)
    progress = pyqtSignal(int, int)

    def __init__(
        self,
        modules: dict[str, ModuleInfo],
        query: str,
        *,
        case_sensitive: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._modules = modules
        self._query = query
        self._case_sensitive = case_sensitive

    def run(self) -> None:
        items = sorted(self._modules.values(), key=lambda m: m.display.lower())
        total = len(items)
        hits: list[ApkRuSearchHit] = []
        limit = 2000
        for i, info in enumerate(items, start=1):
            if self.isInterruptionRequested():
                return
            from gui_pkg.apk_string_search import search_module_values_ru

            hits.extend(
                search_module_values_ru(
                    info.path,
                    module_name=info.name,
                    module_display=info.display,
                    query=self._query,
                    case_sensitive=self._case_sensitive,
                )
            )
            self.progress.emit(i, total)
            if len(hits) >= limit:
                hits = hits[:limit]
                break
        if not self.isInterruptionRequested():
            self.finished_hits.emit(hits)


class ApkStringSearchDialog(QDialog):
    def __init__(
        self,
        *,
        modules: dict[str, ModuleInfo],
        theme: AppTheme,
        on_open_hit: Callable[[ApkRuSearchHit, str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._modules = modules
        self._theme = theme
        self._on_open_hit = on_open_hit
        self._hits: list[ApkRuSearchHit] = []
        self._worker: _SearchWorker | None = None
        self._truncated = False
        self._last_query = ""

        self.setWindowTitle("Поиск строки в values-ru")
        self.setMinimumSize(820, 480)
        self.resize(960, 560)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        hint = QLabel(
            "Ищет подстроку во всех <code>res/values-ru</code> загруженных модулей. "
            "Двойной щелчок — открыть редактор модуля."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        search_row = QHBoxLayout()
        self._query_edit = QLineEdit()
        self._query_edit.setPlaceholderText("Текст для поиска в values-ru…")
        self._query_edit.returnPressed.connect(self._run_search)
        search_row.addWidget(self._query_edit, stretch=1)
        self._btn_search = QPushButton("Поиск")
        self._btn_search.setObjectName("primaryBtn")
        self._btn_search.clicked.connect(self._run_search)
        search_row.addWidget(self._btn_search)
        root.addLayout(search_row)

        self._chk_case = QCheckBox("Учитывать регистр")
        root.addWidget(self._chk_case)

        self._summary = QLabel("Введите текст и нажмите «Поиск».")
        self._summary.setObjectName("hintLabel")
        root.addWidget(self._summary)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Модуль", "Ресурс", "values-ru"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.setWordWrap(False)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.itemDoubleClicked.connect(self._open_selected)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_MODULE, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_RESOURCE, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_RU, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self._table, stretch=1)

        btn_row = QHBoxLayout()
        self._btn_open = QPushButton("Открыть модуль")
        self._btn_open.setEnabled(False)
        self._btn_open.clicked.connect(self._open_selected)
        btn_row.addWidget(self._btn_open)
        btn_row.addStretch()
        root.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        QShortcut(QKeySequence("Ctrl+F"), self, self._query_edit.setFocus)

    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(3000)
        super().closeEvent(event)

    def _preview(self, text: str, limit: int = 80) -> str:
        one = (text or "").replace("\n", " ")
        if len(one) <= limit:
            return one
        return one[: limit - 1] + "…"

    def _run_search(self) -> None:
        query = self._query_edit.text().strip()
        if not query:
            QMessageBox.information(self, "Поиск", "Введите текст для поиска.")
            return
        self._last_query = query
        if not self._modules:
            QMessageBox.warning(self, "Поиск", "Нет загруженных модулей.")
            return
        if self._worker and self._worker.isRunning():
            return
        self._btn_search.setEnabled(False)
        self._summary.setText(f"Поиск «{query}»…")
        self._table.setRowCount(0)
        self._btn_open.setEnabled(False)
        self._worker = _SearchWorker(
            self._modules,
            query,
            case_sensitive=self._chk_case.isChecked(),
            parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_hits.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, current: int, total: int) -> None:
        self._summary.setText(f"Сканирование модулей: {current} / {total}…")

    def _on_finished(self, hits: list) -> None:
        self._btn_search.setEnabled(True)
        self._hits = [h for h in hits if isinstance(h, ApkRuSearchHit)]
        self._truncated = len(self._hits) >= 2000
        self._rebuild_table()
        n_mods = len({h.module_name for h in self._hits})
        msg = f"Найдено: <b>{len(self._hits)}</b> в <b>{n_mods}</b> модулях"
        if self._truncated:
            msg += " · показаны первые 2000"
        self._summary.setText(msg)

    def _rebuild_table(self) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        for hit in self._hits:
            row = self._table.rowCount()
            self._table.insertRow(row)
            mod_item = QTableWidgetItem(hit.module_display)
            mod_item.setData(Qt.ItemDataRole.UserRole, hit)
            mod_item.setToolTip(hit.module_name)
            self._table.setItem(row, _COL_MODULE, mod_item)
            res_item = QTableWidgetItem(hit.resource_id)
            res_item.setToolTip(hit.xml_file)
            self._table.setItem(row, _COL_RESOURCE, res_item)
            ru_item = QTableWidgetItem(self._preview(hit.ru))
            ru_item.setToolTip(hit.ru)
            self._table.setItem(row, _COL_RU, ru_item)
        self._table.setSortingEnabled(True)
        self._btn_open.setEnabled(self._table.rowCount() > 0)

    def _selected_hit(self) -> ApkRuSearchHit | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, _COL_MODULE)
        if not item:
            return None
        hit = item.data(Qt.ItemDataRole.UserRole)
        return hit if isinstance(hit, ApkRuSearchHit) else None

    def _open_selected(self, *_args) -> None:
        hit = self._selected_hit()
        if hit is None or not self._on_open_hit:
            return
        self._on_open_hit(hit, self._last_query)
        self.accept()
