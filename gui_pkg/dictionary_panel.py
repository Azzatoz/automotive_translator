"""Вкладка «Словарь» — заглушки, pending, отчёт Google."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QClipboard
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.config import LIBRARY_DIR
from gui_pkg.dictionary_data import (
    DictListRow,
    dictionary_path_for_track,
    is_placeholder_ru,
    load_dictionary_placeholders,
    load_google_fill_index,
    load_google_rows,
    load_pending_rows,
    open_path_in_system,
    PENDING_FILES,
)
from gui_pkg.process import ProcessController
from gui_pkg.theme import AppTheme


class DictionaryPanel(QWidget):
    merge_requested = pyqtSignal()

    def __init__(
        self,
        *,
        runner: ProcessController,
        theme: AppTheme,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._runner = runner
        self._theme = theme
        self._rows: list[DictListRow] = []
        self._google_index = load_google_fill_index()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        hint = QLabel(
            "<b>Словарь</b> — заглушки в JSON, очередь pending и строки из последнего "
            "отчёта Google fill. Двойной щелчок — копировать исходник."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(hint)

        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("Показать:"))
        self._view_combo = QComboBox()
        self._view_combo.addItem("Заглушки в словаре", "placeholders")
        self._view_combo.addItem("Pending (очередь)", "pending")
        self._view_combo.addItem("Переведено Google", "google")
        self._view_combo.currentIndexChanged.connect(self.reload)
        view_row.addWidget(self._view_combo, stretch=1)
        layout.addLayout(view_row)

        self._summary = QLabel()
        self._summary.setObjectName("hintLabel")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._copy_source)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._list, stretch=1)

        bar = QHBoxLayout()
        btn_refresh = QPushButton("Обновить")
        btn_refresh.clicked.connect(self.reload)
        bar.addWidget(btn_refresh)
        self._btn_open_dict = QPushButton("Открыть словарь")
        self._btn_open_dict.setToolTip("Открыть JSON основного словаря (en или zh)")
        self._btn_open_dict.clicked.connect(self._open_dictionary_menu)
        bar.addWidget(self._btn_open_dict)
        btn_open_pending = QPushButton("Открыть pending")
        btn_open_pending.clicked.connect(lambda: self._open_track_file("pending"))
        bar.addWidget(btn_open_pending)
        self._btn_merge = QPushButton("Перенести pending → словарь")
        self._btn_merge.setToolTip("merge_pending_library_ru.py --track both")
        self._btn_merge.clicked.connect(self._merge_pending)
        bar.addWidget(self._btn_merge)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.reload()

    @property
    def google_module_names(self) -> set[str]:
        return set(self._google_index.modules)

    def reload(self) -> None:
        self._google_index = load_google_fill_index()
        mode = str(self._view_combo.currentData() or "placeholders")
        if mode == "pending":
            self._rows = load_pending_rows()
            self._btn_merge.setVisible(True)
        elif mode == "google":
            self._rows = load_google_rows(self._google_index)
            self._btn_merge.setVisible(False)
        else:
            self._rows = load_dictionary_placeholders()
            self._btn_merge.setVisible(False)
        self._rebuild_list(mode)

    def _rebuild_list(self, mode: str) -> None:
        self._list.clear()
        for row in self._rows:
            preview = row.source.replace("\n", " ")
            if len(preview) > 72:
                preview = preview[:69] + "…"
            if mode == "google":
                label = f"[{row.track}] {preview}"
                if row.ru:
                    ru_p = row.ru.replace("\n", " ")
                    if len(ru_p) > 40:
                        ru_p = ru_p[:37] + "…"
                    label += f"\n  → {ru_p}"
            elif mode == "pending":
                mark = " " if is_placeholder_ru(row.ru) else "✓ "
                label = f"[{row.track}] {mark}{preview}"
            else:
                label = f"[{row.track}] {preview}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, row)
            self._list.addItem(item)

        total = len(self._rows)
        if mode == "placeholders":
            self._summary.setText(f"Заглушек « » в словарях en+zh: {total}")
        elif mode == "pending":
            waiting = sum(1 for r in self._rows if is_placeholder_ru(r.ru))
            ready = total - waiting
            self._summary.setText(
                f"Pending: {total} · без перевода: {waiting} · готово к переносу: {ready}"
            )
        else:
            mods = len(self._google_index.modules)
            self._summary.setText(
                f"Строк через Google в отчёте: {total} · модулей: {mods}"
            )

    def _selected_row(self) -> DictListRow | None:
        item = self._list.currentItem()
        if not item:
            return None
        row = item.data(Qt.ItemDataRole.UserRole)
        return row if isinstance(row, DictListRow) else None

    def _copy_source(self, _item: QListWidgetItem) -> None:
        row = self._selected_row()
        if not row or not row.source:
            return
        cb = QApplication.clipboard()
        if cb:
            cb.setText(row.source, QClipboard.Mode.Clipboard)

    def _context_menu(self, pos) -> None:
        row = self._selected_row()
        if row is None:
            return
        menu = QMenu(self)
        act_copy = menu.addAction("Копировать исходник")
        act_open = menu.addAction("Открыть словарь (трек строки)")
        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen == act_copy:
            self._copy_source(self._list.currentItem())
        elif chosen == act_open:
            self._open_dictionary_for_track(row.track)

    def _open_dictionary_menu(self) -> None:
        row = self._selected_row()
        track = row.track if row and row.kind != "google" else "en"
        if row and row.kind == "google":
            menu = QMenu(self)
            for label, t in (("Словарь en", "en"), ("Словарь zh-CN", "zh-CN")):
                act = menu.addAction(label)
                act.setData(t)
            chosen = menu.exec(self._btn_open_dict.mapToGlobal(self._btn_open_dict.rect().bottomLeft()))
            if chosen:
                self._open_dictionary_for_track(str(chosen.data() or "en"))
            return
        menu = QMenu(self)
        act_en = menu.addAction("Словарь en (translation_library_ru_en.json)")
        act_en.setData("en")
        act_zh = menu.addAction("Словарь zh-CN (translation_library_ru_zh-rCN.json)")
        act_zh.setData("zh-CN")
        chosen = menu.exec(self._btn_open_dict.mapToGlobal(self._btn_open_dict.rect().bottomLeft()))
        if chosen:
            self._open_dictionary_for_track(str(chosen.data() or track))

    def _open_dictionary_for_track(self, track: str) -> None:
        path = dictionary_path_for_track(track)
        if not open_path_in_system(path):
            QMessageBox.information(self, "Словарь", f"Файл не найден:\n{path}")

    def _open_track_file(self, kind: str) -> None:
        row = self._selected_row()
        track = "en"
        if row and row.kind != "google":
            track = row.track
        if kind == "pending":
            path = next((p for t, p in PENDING_FILES if t == track), PENDING_FILES[0][1])
        else:
            path = dictionary_path_for_track(track)
        if not open_path_in_system(path):
            QMessageBox.information(self, "Файл", f"Не найден:\n{path}")

    def _merge_pending(self) -> None:
        args = [
            str(LIBRARY_DIR / "merge_pending_library_ru.py"),
            "--track",
            "both",
        ]
        self._runner.enqueue(args, "merge pending")
        self.merge_requested.emit()
