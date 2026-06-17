"""Вкладка «Конфликты» — UI и сохранение resolutions."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.config import LIBRARY_DIR, TRACKS
from gui_pkg.process import ProcessController
from gui_pkg.responsive import relayout_action_grid
from gui_pkg.scanner import ModuleInfo, modules_in_conflict, prune_conflicts_file
from gui_pkg.theme import AppTheme
from gui_pkg.widgets import ActionButton, ConflictEntryWidget


class ConflictsPanel(QWidget):
    """Панель конфликтов словаря."""

    commands_enqueued = pyqtSignal()

    def __init__(
        self,
        *,
        theme: AppTheme,
        runner: ProcessController,
        get_current_module_name: Callable[[], str | None],
        get_modules: Callable[[], dict[str, ModuleInfo]],
        update_list_item: Callable[[str], None],
        update_overview: Callable[[ModuleInfo], None],
        log_line: Callable[[str, str], None],
        on_apply_apk_sources: Callable[[set[str]], None],
        on_init_conflicts: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._runner = runner
        self._get_current_module_name = get_current_module_name
        self._get_modules = get_modules
        self._update_list_item = update_list_item
        self._update_overview = update_overview
        self._log_line = log_line
        self._on_apply_apk_sources = on_apply_apk_sources
        self._on_init_conflicts = on_init_conflicts

        self._conflict_widgets: list[ConflictEntryWidget] = []
        self._conflicts_toolbar_buttons: list[ActionButton] = []
        self.conflict_apply_pending: dict[str, set[str]] = {}
        self.conflict_apply_apk_sources: set[str] = set()
        self.pending_refresh_after_save = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        howto = QLabel(
            "<b>Как это работает</b><br>"
            "1. Выберите вариант перевода (радиокнопка) в каждом нужном конфликте.<br>"
            "2. <b>Кликните по блоку</b>, чтобы выделить его (синяя рамка) — так помечаете, "
            "что именно сохранить.<br>"
            "3. «Сохранить выделенные» — только отмеченные блоки. "
            "«Сохранить все на экране» — все видимые конфликты сразу."
        )
        howto.setObjectName("hintLabel")
        howto.setWordWrap(True)
        howto.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(howto)

        self._conflicts_summary = QLabel()
        self._conflicts_summary.setObjectName("hintLabel")
        layout.addWidget(self._conflicts_summary)

        self._chk_filter_module_conflicts = QCheckBox(
            "Показывать только конфликты выбранного модуля"
        )
        self._chk_filter_module_conflicts.setChecked(True)
        self._chk_filter_module_conflicts.stateChanged.connect(self.reload)
        layout.addWidget(self._chk_filter_module_conflicts)

        toolbar_box = QGroupBox()
        self._conflicts_toolbar_grid = QGridLayout(toolbar_box)
        self._conflicts_toolbar_grid.setSpacing(8)
        conflict_actions: list[tuple[str, str, object, bool]] = [
            ("Обновить список", "Обновить", self.reload, False),
            (
                "Подставить популярный вариант",
                "Большинство",
                self._on_init_conflicts,
                False,
            ),
            ("Выделить все", "Все", self._highlight_all, False),
            ("Снять выделение", "Снять", self._clear_highlights, False),
            (
                "Сохранить выделенные",
                "Выделен.",
                lambda: self.apply_conflicts(only_highlighted=True),
                True,
            ),
            (
                "Сохранить все на экране",
                "Все на экране",
                lambda: self.apply_conflicts(only_highlighted=False),
                False,
            ),
            (
                "Записать решения в APK (выбранный модуль)",
                "В APK",
                self.apply_to_apk_current_module,
                False,
            ),
        ]
        for full_label, short_label, handler, primary in conflict_actions:
            btn = ActionButton(full_label, short_label, primary=primary)
            btn.clicked.connect(handler)  # type: ignore[arg-type]
            self._conflicts_toolbar_buttons.append(btn)
        self._conflicts_toolbar_buttons[1].setToolTip(
            "Для каждого конфликта выбрать перевод, который встречается в большинстве модулей"
        )
        self._btn_apply_marked = self._conflicts_toolbar_buttons[4]
        self._btn_apply_marked.setToolTip(
            "Записать в словарь только блоки с синей рамкой"
        )
        self._btn_apply_all = self._conflicts_toolbar_buttons[5]
        self._btn_apply_all.setToolTip(
            "Записать в словарь все конфликты, которые сейчас видны в списке ниже "
            "(с выбранным вариантом перевода)"
        )
        layout.addWidget(toolbar_box)
        relayout_action_grid(
            self._conflicts_toolbar_grid,
            self._conflicts_toolbar_buttons,
            container_width=1200,
            max_columns=3,
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._conflicts_container = QWidget()
        self._conflicts_layout = QVBoxLayout(self._conflicts_container)
        self._conflicts_layout.setSpacing(10)
        self._conflicts_layout.setContentsMargins(0, 0, 0, 0)
        self._conflicts_layout.addStretch()
        scroll.setWidget(self._conflicts_container)
        layout.addWidget(scroll)

    @property
    def toolbar_buttons(self) -> list[ActionButton]:
        return self._conflicts_toolbar_buttons

    def apply_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        for w in self._conflict_widgets:
            w.apply_theme(theme)

    def relayout_toolbar(self, width: int) -> None:
        relayout_action_grid(
            self._conflicts_toolbar_grid,
            self._conflicts_toolbar_buttons,
            container_width=width,
            max_columns=3,
        )

    def reload(self) -> None:
        self._clear_layout()
        module_name = (
            self._get_current_module_name()
            if self._chk_filter_module_conflicts.isChecked()
            else None
        )

        for track, conflicts_path, _, resolutions_path in TRACKS:
            if not conflicts_path.is_file():
                continue
            try:
                data = json.loads(conflicts_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            conflicts = data.get("conflicts") or []
            resolutions_data: dict[str, Any] = {}
            if resolutions_path.is_file():
                try:
                    resolutions_data = json.loads(resolutions_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
            res_map = resolutions_data.get("resolutions") or {}

            for item in conflicts:
                if module_name and module_name not in modules_in_conflict(item):
                    continue
                merged = dict(item)
                src = str(item.get("source") or "")
                if src in res_map and isinstance(res_map[src], dict):
                    chosen = res_map[src].get("chosen")
                    if chosen:
                        merged["chosen"] = chosen
                widget = ConflictEntryWidget(track, merged, theme=self._theme)
                widget.chosen_changed.connect(self._update_summary)
                widget.highlight_changed.connect(self._update_summary)
                self._conflict_widgets.append(widget)
                self._conflicts_layout.insertWidget(
                    self._conflicts_layout.count() - 1, widget
                )

        if not self._conflict_widgets:
            empty = QLabel("Конфликтов нет (или не найдены для выбранного модуля).")
            empty.setObjectName("hintLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._conflicts_layout.insertWidget(0, empty)

        self._update_summary()

    def on_apply_step_finished(self, label: str) -> bool:
        """Обработать завершение apply conflicts (track). Возвращает True если обработано."""
        prefix = "apply conflicts ("
        if not label.startswith(prefix) or not label.endswith(")"):
            return False
        track = label[len(prefix) : -1]
        sources = self.conflict_apply_pending.pop(track, None)
        if not sources:
            return True
        for track_name, conflicts_path, _, _ in TRACKS:
            if track_name != track:
                continue
            removed = prune_conflicts_file(conflicts_path, sources)
            if removed:
                self._log_line(
                    f"[gui] из отчёта убрано конфликтов ({track_name}): {removed}",
                    "stdout",
                )
            break
        self.reload()
        self.refresh_badges_from_cache()
        return True

    def refresh_badges_from_cache(self) -> None:
        from gui_pkg.scanner import count_conflicts_for_module, load_conflicts_cache

        cache = load_conflicts_cache()
        modules = self._get_modules()
        for name, info in modules.items():
            if not info.stats:
                info.stats = {}
            n = count_conflicts_for_module(name, cache)
            info.stats["conflicts"] = n
            if n > 0:
                info.stats["status"] = "conflicts"
            elif info.stats.get("status") == "conflicts":
                from gui_pkg.scanner import resolve_module_status

                info.stats["status"] = resolve_module_status(
                    total=int(info.stats.get("total", 0)),
                    placeholders=int(info.stats.get("placeholders", 0)),
                    conflicts=0,
                    dict_mismatches=int(info.stats.get("dict_mismatches", 0)),
                )
            self._update_list_item(name)
        current_name = self._get_current_module_name()
        if current_name:
            info = modules.get(current_name)
            if info:
                self._update_overview(info)

    def apply_to_apk_current_module(self) -> None:
        from gui_pkg.scanner import load_conflicts_cache

        info = self._get_modules().get(self._get_current_module_name() or "")
        if not info:
            QMessageBox.information(self, "APK", "Выберите модуль слева.")
            return
        widgets = [w for w in self._conflict_widgets if w.get_chosen()]
        if not widgets:
            QMessageBox.information(
                self,
                "APK",
                "Отметьте варианты перевода (радиокнопки) в конфликтах на экране.",
            )
            return
        sources = {w.source for w in widgets}
        if self._chk_filter_module_conflicts.isChecked():
            cache = load_conflicts_cache()
            filtered: set[str] = set()
            for items in cache.values():
                for item in items:
                    src = str(item.get("source") or "")
                    if src in sources and info.name in modules_in_conflict(item):
                        filtered.add(src)
            sources = filtered
        if not sources:
            QMessageBox.information(
                self,
                "APK",
                "Нет конфликтов с выбранным переводом для этого модуля.",
            )
            return
        self._on_apply_apk_sources(sources)

    def apply_conflicts(self, *, only_highlighted: bool) -> None:
        if self._runner.is_running:
            return

        if only_highlighted:
            widgets = [w for w in self._conflict_widgets if w.is_highlighted()]
            if not widgets:
                QMessageBox.information(
                    self,
                    "Конфликты",
                    "Нет выделенных блоков.\n"
                    "Кликните по нужным карточкам — они подсветятся синей рамкой.",
                )
                return
        else:
            widgets = list(self._conflict_widgets)

        to_save = [w for w in widgets if w.get_chosen()]
        if not to_save:
            QMessageBox.information(
                self,
                "Конфликты",
                "У выбранных блоков не отмечен вариант перевода (радиокнопка).",
            )
            return

        skipped = len(widgets) - len(to_save)
        scope = "выделенных" if only_highlighted else "видимых на экране"
        extra = ""
        if skipped:
            extra = f"\n\nБез варианта перевода и будут пропущены: {skipped}."
        answer = QMessageBox.question(
            self,
            "Сохранить в словарь",
            f"Записать в общий словарь {len(to_save)} решений из {scope} блоков?{extra}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        apk_answer = QMessageBox.question(
            self,
            "Сохранить в словарь",
            "Также записать выбранные переводы в APK затронутых модулей?\n"
            "(только строки с этими исходниками, без полного fill)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        apply_apk = apk_answer == QMessageBox.StandardButton.Yes

        by_track: dict[str, dict[str, dict[str, Any]]] = {t[0]: {} for t in TRACKS}
        conflict_lookup: dict[str, dict[str, dict[str, Any]]] = {t[0]: {} for t in TRACKS}
        for track, conflicts_path, _, _ in TRACKS:
            if not conflicts_path.is_file():
                continue
            try:
                data = json.loads(conflicts_path.read_text(encoding="utf-8"))
                for c in data.get("conflicts") or []:
                    src = str(c.get("source") or "")
                    if src:
                        conflict_lookup[track][src] = c
            except (OSError, json.JSONDecodeError):
                pass

        for widget in to_save:
            chosen = widget.get_chosen()
            src = widget.source
            item: dict[str, Any] = {"chosen": chosen}
            orig = conflict_lookup.get(widget.track, {}).get(src)
            if orig and isinstance(orig.get("translations"), dict):
                item["variants"] = orig["translations"]
            by_track[widget.track][src] = item

        cmds: list[tuple[list[str], str]] = []
        for track, conflicts_path, library_path, resolutions_path in TRACKS:
            entries = by_track.get(track) or {}
            if not entries:
                continue
            self._write_resolutions(
                resolutions_path, entries, track, merge=only_highlighted
            )
            args = [
                str(LIBRARY_DIR / "apply_translation_conflict_resolutions_ru.py"),
                "--apply",
                "--conflicts",
                str(conflicts_path),
                "--resolutions",
                str(resolutions_path),
                "--library",
                str(library_path),
            ]
            cmds.append((args, f"apply conflicts ({track})"))

        self.pending_refresh_after_save = True
        self.conflict_apply_pending = {
            track: set(entries.keys()) for track, entries in by_track.items() if entries
        }
        self.conflict_apply_apk_sources = (
            {src for entries in by_track.values() for src in entries}
            if apply_apk
            else set()
        )
        for args, label in cmds:
            self._runner.enqueue(args, label)
        self.commands_enqueued.emit()

    def _write_resolutions(
        self,
        resolutions_path: Path,
        entries: dict[str, dict[str, Any]],
        track: str,
        *,
        merge: bool,
    ) -> None:
        resolutions: dict[str, Any] = {}
        if merge and resolutions_path.is_file():
            try:
                data = json.loads(resolutions_path.read_text(encoding="utf-8"))
                raw = data.get("resolutions") or {}
                if isinstance(raw, dict):
                    resolutions = dict(raw)
            except (OSError, json.JSONDecodeError):
                pass
        resolutions.update(entries)
        payload = {
            "schema_version": 1,
            "resolutions": resolutions,
            "meta": {"from_gui": True, "track": track},
        }
        resolutions_path.parent.mkdir(parents=True, exist_ok=True)
        resolutions_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _clear_layout(self) -> None:
        while self._conflicts_layout.count() > 1:
            item = self._conflicts_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._conflict_widgets.clear()

    def _highlight_all(self) -> None:
        for widget in self._conflict_widgets:
            widget.set_highlighted(True)
        self._update_summary()

    def _clear_highlights(self) -> None:
        for widget in self._conflict_widgets:
            widget.set_highlighted(False)
        self._update_summary()

    def _update_summary(self) -> None:
        total = len(self._conflict_widgets)
        ready = sum(1 for w in self._conflict_widgets if w.get_chosen())
        highlighted = sum(1 for w in self._conflict_widgets if w.is_highlighted())
        marked_ready = sum(
            1 for w in self._conflict_widgets if w.is_highlighted() and w.get_chosen()
        )
        if total == 0:
            self._conflicts_summary.setText("На экране нет конфликтов.")
            self._btn_apply_all.update_labels("Сохранить все на экране", "Все на экране")
            self._btn_apply_marked.update_labels("Сохранить выделенные", "Выделен.")
            self._btn_apply_all.setEnabled(False)
            self._btn_apply_marked.setEnabled(False)
            return
        self._btn_apply_all.setEnabled(ready > 0)
        self._btn_apply_marked.setEnabled(marked_ready > 0)
        if self._chk_filter_module_conflicts.isChecked():
            scope = "только выбранного модуля"
        else:
            scope = "всего проекта"
        self._conflicts_summary.setText(
            f"На экране: {total} ({scope}). "
            f"Выделено: {highlighted}. "
            f"Готово к сохранению: {ready} (выделенных: {marked_ready})."
        )
        self._btn_apply_marked.update_labels(
            f"Сохранить выделенные ({marked_ready})",
            f"Выделен.\n({marked_ready})",
        )
        self._btn_apply_all.update_labels(
            f"Сохранить все на экране ({ready})",
            f"Все\n({ready})",
        )
