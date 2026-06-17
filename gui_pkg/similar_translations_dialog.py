"""Диалог похожих переводов из словаря."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from gui_pkg.similar_search import search_similar_in_library


class SimilarTranslationsDialog(QDialog):
    def __init__(
        self,
        query: str,
        track: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._selected_ru: str | None = None
        self.setWindowTitle("Похожие в словаре")
        self.setMinimumSize(520, 400)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Поиск по: <code>{query[:120]}</code>"))
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._accept_current)
        for src, ru in search_similar_in_library(query, track=track):
            preview = src.replace("\n", " ")
            if len(preview) > 60:
                preview = preview[:57] + "…"
            item = QListWidgetItem(f"{preview}\n→ {ru!r}")
            item.setData(Qt.ItemDataRole.UserRole, ru)
            self._list.addItem(item)
        if self._list.count() == 0:
            self._list.addItem("Ничего не найдено")
        layout.addWidget(self._list)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_current)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_current(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        ru = item.data(Qt.ItemDataRole.UserRole)
        if ru is None:
            return
        self._selected_ru = ru
        self.accept()

    def selected_ru(self) -> str | None:
        return self._selected_ru
