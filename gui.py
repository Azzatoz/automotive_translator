#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Графическая обёртка над скриптами Automotive Translator (PyQt6)."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PyQt6.QtCore import (
    QObject,
    QProcess,
    QSettings,
    Qt,
    QThread,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

REPO_ROOT = Path(__file__).resolve().parent
SETTINGS_ORG = "AutomotiveTranslator"
SETTINGS_APP = "GUI"
TRANSLATABLE_XML = ("strings.xml", "plurals.xml", "arrays.xml")

TRACKS: list[tuple[str, Path, Path, Path]] = [
    (
        "en",
        REPO_ROOT / "reports" / "translation_library_ru_en_conflicts.json",
        REPO_ROOT / "translation_library_ru_en.json",
        REPO_ROOT / "library" / "translation_library_ru_en_resolutions.json",
    ),
    (
        "zh-CN",
        REPO_ROOT / "reports" / "translation_library_ru_zh-rCN_conflicts.json",
        REPO_ROOT / "translation_library_ru_zh-rCN.json",
        REPO_ROOT / "library" / "translation_library_ru_zh-rCN_resolutions.json",
    ),
]

ROOT_PRESETS: list[tuple[str, Path]] = [
    ("../Translated", REPO_ROOT.parent / "Translated"),
    (
        "../../Rest 4.1.1/Translated",
        REPO_ROOT.parent.parent / "Rest 4.1.1" / "Translated",
    ),
    (
        "../../Dorest 3.2.0/dorest 320",
        REPO_ROOT.parent.parent / "Dorest 3.2.0" / "dorest 320",
    ),
    (
        "D:/Voyah/Dorest translate/Translated",
        Path("D:/Voyah/Dorest translate/Translated"),
    ),
]


def display_module_name(folder_name: str) -> str:
    if folder_name.endswith("_src"):
        return folder_name[:-4]
    return folder_name


def discover_modules(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    modules: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "res").is_dir():
            modules.append(child)
    return modules


def _load_conflicts_cache() -> dict[str, list[dict[str, Any]]]:
    cache: dict[str, list[dict[str, Any]]] = {}
    for track, conflicts_path, _, _ in TRACKS:
        if not conflicts_path.is_file():
            cache[track] = []
            continue
        try:
            data = json.loads(conflicts_path.read_text(encoding="utf-8"))
            cache[track] = list(data.get("conflicts") or [])
        except (OSError, json.JSONDecodeError):
            cache[track] = []
    return cache


def _modules_in_conflict(item: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for mods in (item.get("modules") or []):
        if isinstance(mods, str):
            found.add(mods)
    translations = item.get("translations") or {}
    if isinstance(translations, dict):
        for mod_list in translations.values():
            if isinstance(mod_list, list):
                for m in mod_list:
                    if isinstance(m, str):
                        found.add(m)
    return found


def count_conflicts_for_module(
    module_folder: str, conflicts_cache: dict[str, list[dict[str, Any]]] | None = None
) -> int:
    cache = conflicts_cache if conflicts_cache is not None else _load_conflicts_cache()
    count = 0
    for items in cache.values():
        for item in items:
            if module_folder in _modules_in_conflict(item):
                count += 1
    return count


def scan_module(
    module_path: Path,
    conflicts_cache: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    values_ru = module_path / "res" / "values-ru"
    folder = module_path.name
    conflicts = count_conflicts_for_module(folder, conflicts_cache)

    if not values_ru.is_dir():
        return {
            "total": 0,
            "translated": 0,
            "placeholders": 0,
            "conflicts": conflicts,
            "status": "unprocessed",
        }

    total = 0
    placeholders = 0
    for xml_name in TRANSLATABLE_XML:
        xml_path = values_ru / xml_name
        if not xml_path.is_file():
            continue
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError:
            continue
        for el in root.iter():
            if el.tag not in ("string", "item"):
                continue
            total += 1
            text = el.text or ""
            if text.strip() == "" or text == " ":
                placeholders += 1

    translated = total - placeholders
    if conflicts > 0:
        status = "conflicts"
    elif placeholders > 0:
        status = "placeholders"
    elif total > 0:
        status = "ready"
    else:
        status = "unprocessed"

    return {
        "total": total,
        "translated": translated,
        "placeholders": placeholders,
        "conflicts": conflicts,
        "status": status,
    }


@dataclass
class ModuleInfo:
    path: Path
    name: str
    display: str
    stats: dict[str, Any] = field(default_factory=dict)


class ModuleScanWorker(QThread):
    module_scanned = pyqtSignal(str, dict)
    finished_scan = pyqtSignal()

    def __init__(self, modules: list[Path], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._modules = modules

    def run(self) -> None:
        conflicts_cache = _load_conflicts_cache()
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(scan_module, mod, conflicts_cache): mod for mod in self._modules
            }
            for fut in as_completed(futures):
                mod = futures[fut]
                try:
                    stats = fut.result()
                except Exception:
                    stats = scan_module(mod, conflicts_cache)
                self.module_scanned.emit(mod.name, stats)
        self.finished_scan.emit()


class LogView(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(mono)

    def append_line(self, text: str, stream: str = "stdout") -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        stripped = text.strip()
        if "[ok]" in stripped.lower() or "[write]" in stripped.lower():
            fmt.setForeground(QColor("#2e7d32"))
        elif "[warn]" in stripped.lower():
            fmt.setForeground(QColor("#ef6c00"))
        elif "[error]" in stripped.lower() or stream == "stderr":
            fmt.setForeground(QColor("#c62828"))
        else:
            fmt.setForeground(QColor("#616161"))
        cursor.setCharFormat(fmt)
        cursor.insertText(text.rstrip("\n") + "\n")
        self.setTextCursor(cursor)
        self.ensureCursorVisible()


class StatCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        self._title = QLabel(title)
        self._title.setStyleSheet("color: #666; font-size: 11px;")
        self._value = QLabel("—")
        self._value.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(self._title)
        layout.addWidget(self._value)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


class ConflictEntryWidget(QFrame):
    chosen_changed = pyqtSignal()

    def __init__(
        self,
        track: str,
        item: dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.track = track
        self.source = str(item.get("source") or "")
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.buttonClicked.connect(lambda: self.chosen_changed.emit())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        src_label = QLabel(f"<b>Источник ({track}):</b>")
        src_text = QLabel(self.source)
        src_text.setWordWrap(True)
        src_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(src_label)
        layout.addWidget(src_text)

        translations = item.get("translations") or {}
        chosen = str(item.get("chosen") or "")
        if not isinstance(translations, dict):
            translations = {}

        for ru_text, mod_list in translations.items():
            mods = mod_list if isinstance(mod_list, list) else []
            mod_str = ", ".join(str(m) for m in mods[:6])
            if len(mods) > 6:
                mod_str += f" … (+{len(mods) - 6})"
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            rb = QRadioButton()
            rb.setProperty("ru_value", ru_text)
            row_layout.addWidget(rb, alignment=Qt.AlignmentFlag.AlignTop)
            text = QLabel(f"{ru_text}\n<i>модули: {mod_str}</i>")
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(text, stretch=1)
            if ru_text == chosen or (not chosen and self._group.buttons() == []):
                rb.setChecked(True)
            self._group.addButton(rb)
            layout.addWidget(row)

        if not self._group.buttons() and chosen:
            rb = QRadioButton(chosen)
            rb.setProperty("ru_value", chosen)
            rb.setChecked(True)
            self._group.addButton(rb)
            layout.addWidget(rb)

    def get_chosen(self) -> str:
        btn = self._group.checkedButton()
        if btn is None:
            return ""
        return str(btn.property("ru_value") or btn.text())


class ProcessController(QObject):
    line_received = pyqtSignal(str, str)
    started = pyqtSignal(str)
    finished = pyqtSignal(int)
    status_changed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)
        self._queue: list[tuple[list[str], str]] = []
        self._running = False
        self._current_label = ""
        self._last_lines: list[str] = []

    @property
    def is_running(self) -> bool:
        return self._running

    def enqueue(self, args: list[str], label: str) -> None:
        self._queue.append((args, label))
        if not self._running:
            self._start_next()

    def run_single(self, args: list[str], label: str) -> None:
        self._queue = [(args, label)]
        if self._running:
            self.kill()
        else:
            self._start_next()

    def _start_next(self) -> None:
        if not self._queue:
            self._running = False
            self.status_changed.emit("Готово")
            return
        args, label = self._queue.pop(0)
        self._current_label = label
        self._last_lines = []
        self._running = True
        self.started.emit(label)
        self.status_changed.emit(f"Выполняется: {label}…")
        self._process.setWorkingDirectory(str(REPO_ROOT))
        self._process.start(sys.executable, args)

    def _on_stdout(self) -> None:
        data = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self._last_lines.append(line)
            if len(self._last_lines) > 50:
                self._last_lines.pop(0)
            self.line_received.emit(line, "stdout")

    def _on_stderr(self) -> None:
        data = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self._last_lines.append(line)
            if len(self._last_lines) > 50:
                self._last_lines.pop(0)
            self.line_received.emit(line, "stderr")

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self.finished.emit(exit_code)
        if self._queue:
            self._start_next()
        else:
            self._running = False
            if exit_code == 0:
                self.status_changed.emit("Готово")
            else:
                self.status_changed.emit("Ошибка")

    def kill(self) -> None:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
        self._queue.clear()
        self._running = False
        self.status_changed.emit("Прервано")

    def last_lines_text(self) -> str:
        return "\n".join(self._last_lines[-15:])


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Automotive Translator")
        self.setMinimumSize(1000, 650)
        self.resize(1200, 750)

        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._modules: dict[str, ModuleInfo] = {}
        self._scan_worker: ModuleScanWorker | None = None
        self._conflict_widgets: list[ConflictEntryWidget] = []
        self._pending_refresh_after_cmd = False
        self._action_buttons: list[QPushButton] = []

        self._runner = ProcessController(self)
        self._runner.line_received.connect(self._on_log_line)
        self._runner.started.connect(self._on_cmd_started)
        self._runner.finished.connect(self._on_cmd_finished)
        self._runner.status_changed.connect(self._on_status_text)

        self._build_ui()
        self._load_root_presets()
        self._restore_last_root()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 4)

        header = QHBoxLayout()
        header.addWidget(QLabel("Папка проекта:"))
        self._root_combo = QComboBox()
        self._root_combo.setMinimumWidth(320)
        self._root_combo.setEditable(True)
        self._root_combo.currentIndexChanged.connect(self._on_root_changed)
        header.addWidget(self._root_combo, stretch=1)
        btn_browse = QPushButton("Выбрать папку")
        btn_browse.clicked.connect(self._browse_root)
        header.addWidget(btn_browse)
        btn_reload = QPushButton("Обновить")
        btn_reload.clicked.connect(self._reload_modules)
        header.addWidget(btn_reload)
        root_layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Фильтр по имени модуля…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        left_layout.addWidget(self._filter_edit)
        self._module_list = QListWidget()
        self._module_list.currentItemChanged.connect(self._on_module_selected)
        left_layout.addWidget(self._module_list)
        splitter.addWidget(left)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_overview_tab(), "Обзор")
        self._tabs.addTab(self._build_actions_tab(), "Действия")
        self._tabs.addTab(self._build_conflicts_tab(), "Конфликты")
        self._tabs.addTab(self._build_log_tab(), "Лог")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        splitter.addWidget(self._tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        root_layout.addWidget(splitter, stretch=1)

        status = QStatusBar()
        self.setStatusBar(status)
        self._status_label = QLabel("Готово")
        self._cmd_progress = QProgressBar()
        self._cmd_progress.setMaximumWidth(200)
        self._cmd_progress.setTextVisible(False)
        self._cmd_progress.setVisible(False)
        self._btn_abort = QPushButton("Прервать")
        self._btn_abort.setEnabled(False)
        self._btn_abort.clicked.connect(self._abort_command)
        status.addWidget(self._status_label, stretch=1)
        status.addPermanentWidget(self._cmd_progress)
        status.addPermanentWidget(self._btn_abort)

    def _build_overview_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        cards = QHBoxLayout()
        self._card_total = StatCard("Всего строк")
        self._card_translated = StatCard("Переведено")
        self._card_placeholders = StatCard("Заглушек")
        self._card_conflicts = StatCard("Конфликтов")
        for card in (
            self._card_total,
            self._card_translated,
            self._card_placeholders,
            self._card_conflicts,
        ):
            cards.addWidget(card)
        layout.addLayout(cards)

        self._overview_progress = QProgressBar()
        self._overview_progress.setFormat("%p% переведено")
        layout.addWidget(self._overview_progress)

        self._module_title = QLabel("Модуль не выбран")
        self._module_title.setStyleSheet("font-size: 14px; font-weight: bold; margin-top: 8px;")
        layout.addWidget(self._module_title)

        quick = QGroupBox("Быстрые действия")
        quick_layout = QHBoxLayout(quick)
        actions = [
            ("ensure-dictionary", self._quick_ensure_dictionary),
            ("collect", self._quick_collect),
            ("sort", self._quick_sort),
            ("audit", self._quick_audit),
            ("fix dates", self._quick_fix_dates),
            ("init conflicts", self._quick_init_conflicts),
            ("layout scan", self._quick_layout_scan),
            ("layout inject", self._quick_layout_inject),
        ]
        for label, handler in actions:
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            quick_layout.addWidget(btn)
            self._action_buttons.append(btn)
        layout.addWidget(quick)
        layout.addStretch()
        return w

    def _build_actions_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        w = QWidget()
        layout = QVBoxLayout(w)

        mode_group = QGroupBox("Режим fill_values_ru_from_library.py")
        mode_layout = QVBoxLayout(mode_group)
        self._mode_group = QButtonGroup(self)
        self._rb_normal = QRadioButton("Обычный (+ Google)")
        self._rb_library_only = QRadioButton("--library-only")
        self._rb_ensure_dict = QRadioButton("--ensure-dictionary")
        self._rb_normal.setChecked(True)
        for i, rb in enumerate((self._rb_normal, self._rb_library_only, self._rb_ensure_dict)):
            self._mode_group.addButton(rb, i)
            mode_layout.addWidget(rb)
        layout.addWidget(mode_group)

        lang_group = QGroupBox("--source-lang")
        lang_layout = QHBoxLayout(lang_group)
        self._lang_group = QButtonGroup(self)
        self._rb_zh = QRadioButton("zh-CN")
        self._rb_en = QRadioButton("en")
        self._rb_zh.setChecked(True)
        self._lang_group.addButton(self._rb_zh, 0)
        self._lang_group.addButton(self._rb_en, 1)
        lang_layout.addWidget(self._rb_zh)
        lang_layout.addWidget(self._rb_en)
        layout.addWidget(lang_group)

        opts_group = QGroupBox("Опции")
        opts_layout = QVBoxLayout(opts_group)
        self._chk_no_overwrite = QCheckBox("--no-overwrite")
        self._chk_dry_run = QCheckBox("--dry-run")
        self._chk_strings_only = QCheckBox("--strings-only")
        self._chk_all_modules = QCheckBox("Все модули (--root)")
        self._chk_all_modules.setChecked(True)
        self._chk_auto_collect = QCheckBox("После fill — collect --track both")
        self._chk_auto_collect.setChecked(True)
        for chk in (
            self._chk_no_overwrite,
            self._chk_dry_run,
            self._chk_strings_only,
            self._chk_all_modules,
            self._chk_auto_collect,
        ):
            opts_layout.addWidget(chk)
        layout.addWidget(opts_group)

        self._btn_run_fill = QPushButton("Запустить fill")
        self._btn_run_fill.clicked.connect(self._run_fill)
        layout.addWidget(self._btn_run_fill)
        self._action_buttons.append(self._btn_run_fill)

        layout_group = QGroupBox("layout/extract_layout_hardcode.py")
        layout_form = QVBoxLayout(layout_group)
        self._layout_mode_group = QButtonGroup(self)
        self._rb_layout_report = QRadioButton("Только отчёт")
        self._rb_layout_inject = QRadioButton("--inject-values")
        self._rb_layout_inplace = QRadioButton("--translate-inplace")
        self._rb_layout_inject.setChecked(True)
        for i, rb in enumerate(
            (self._rb_layout_report, self._rb_layout_inject, self._rb_layout_inplace)
        ):
            self._layout_mode_group.addButton(rb, i)
            layout_form.addWidget(rb)
        self._chk_layout_dry_run = QCheckBox("--dry-run")
        layout_form.addWidget(self._chk_layout_dry_run)
        prefix_row = QHBoxLayout()
        prefix_row.addWidget(QLabel("--key-prefix:"))
        self._layout_key_prefix = QLineEdit("hw")
        self._layout_key_prefix.setMaximumWidth(120)
        prefix_row.addWidget(self._layout_key_prefix)
        prefix_row.addStretch()
        layout_form.addLayout(prefix_row)
        scope_note = QLabel(
            "Область: чекбокс «Все модули (--root)» выше; иначе — выбранный модуль (-m)."
        )
        scope_note.setWordWrap(True)
        scope_note.setStyleSheet("color: #666; font-size: 11px;")
        layout_form.addWidget(scope_note)
        self._btn_run_layout = QPushButton("Запустить layout extract")
        self._btn_run_layout.clicked.connect(self._run_layout)
        layout_form.addWidget(self._btn_run_layout)
        self._action_buttons.append(self._btn_run_layout)
        layout.addWidget(layout_group)

        layout.addStretch()
        scroll.setWidget(w)
        return scroll

    def _build_conflicts_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        toolbar = QHBoxLayout()
        self._chk_filter_module_conflicts = QCheckBox("Только для выбранного модуля")
        self._chk_filter_module_conflicts.setChecked(True)
        self._chk_filter_module_conflicts.stateChanged.connect(self._reload_conflicts_ui)
        toolbar.addWidget(self._chk_filter_module_conflicts)
        btn_reload = QPushButton("Обновить список")
        btn_reload.clicked.connect(self._reload_conflicts_ui)
        toolbar.addWidget(btn_reload)
        btn_init = QPushButton("Init (--init --majority)")
        btn_init.clicked.connect(self._quick_init_conflicts)
        toolbar.addWidget(btn_init)
        toolbar.addStretch()
        btn_apply = QPushButton("Применить выбранное")
        btn_apply.clicked.connect(self._apply_conflicts)
        toolbar.addWidget(btn_apply)
        self._btn_apply_conflicts = btn_apply
        layout.addLayout(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._conflicts_container = QWidget()
        self._conflicts_layout = QVBoxLayout(self._conflicts_container)
        self._conflicts_layout.addStretch()
        scroll.setWidget(self._conflicts_container)
        layout.addWidget(scroll)

        self._action_buttons.append(btn_init)
        self._action_buttons.append(btn_apply)
        return w

    def _build_log_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        bar = QHBoxLayout()
        btn_clear = QPushButton("Очистить")
        btn_clear.clicked.connect(lambda: self._log_view.clear())
        bar.addStretch()
        bar.addWidget(btn_clear)
        layout.addLayout(bar)
        self._log_view = LogView()
        layout.addWidget(self._log_view)
        return w

    def _load_root_presets(self) -> None:
        self._root_combo.clear()
        seen: set[str] = set()
        for label, path in ROOT_PRESETS:
            resolved = path.expanduser().resolve() if path.exists() else None
            if resolved is None:
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            self._root_combo.addItem(f"{label}  ({resolved})", key)

    def _restore_last_root(self) -> None:
        last = self._settings.value("last_root", "", str)
        if last:
            idx = self._root_combo.findData(last)
            if idx >= 0:
                self._root_combo.setCurrentIndex(idx)
            else:
                self._root_combo.setEditText(last)
            if Path(last).is_dir():
                self._reload_modules()
                return
        if self._root_combo.count() > 0:
            self._reload_modules()

    def _current_root(self) -> Path | None:
        data = self._root_combo.currentData()
        if data:
            p = Path(str(data))
            if p.is_dir():
                return p
        text = self._root_combo.currentText().strip()
        if not text:
            return None
        if "  (" in text:
            text = text.split("  (", 1)[-1].rstrip(")")
        p = Path(text).expanduser()
        if p.is_dir():
            return p.resolve()
        return None

    def _on_root_changed(self, _index: int) -> None:
        root = self._current_root()
        if root is not None:
            self._settings.setValue("last_root", str(root))

    def _on_tab_changed(self, index: int) -> None:
        if index == 2:
            self._reload_conflicts_ui()

    def _browse_root(self) -> None:
        start = str(self._current_root() or REPO_ROOT.parent)
        chosen = QFileDialog.getExistingDirectory(self, "Папка проекта", start)
        if not chosen:
            return
        path = Path(chosen)
        key = str(path.resolve())
        idx = self._root_combo.findData(key)
        if idx < 0:
            self._root_combo.addItem(key, key)
            idx = self._root_combo.findData(key)
        self._root_combo.setCurrentIndex(idx)
        self._settings.setValue("last_root", key)
        self._reload_modules()

    def _reload_modules(self) -> None:
        root = self._current_root()
        if root is None:
            QMessageBox.warning(self, "Папка проекта", "Укажите существующую папку с модулями.")
            return
        self._settings.setValue("last_root", str(root))
        modules = discover_modules(root)
        self._modules.clear()
        self._module_list.clear()
        for mod in modules:
            info = ModuleInfo(path=mod, name=mod.name, display=display_module_name(mod.name))
            self._modules[mod.name] = info
            item = QListWidgetItem(info.display)
            item.setData(Qt.ItemDataRole.UserRole, mod.name)
            self._module_list.addItem(item)

        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.terminate()
            self._scan_worker.wait(1000)

        self._scan_worker = ModuleScanWorker(modules, self)
        self._scan_worker.module_scanned.connect(self._on_module_scanned)
        self._scan_worker.finished_scan.connect(self._on_scan_finished)
        self._status_label.setText("Сканирование модулей…")
        self._scan_worker.start()

    def _on_module_scanned(self, name: str, stats: dict[str, Any]) -> None:
        info = self._modules.get(name)
        if not info:
            return
        info.stats = stats
        for i in range(self._module_list.count()):
            item = self._module_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == name:
                self._update_list_item(item, info)
                break
        current = self._current_module_name()
        if current == name:
            self._update_overview(info)

    def _on_scan_finished(self) -> None:
        if not self._runner.is_running:
            self._status_label.setText("Готово")
        self._apply_filter()

    def _badge_text(self, stats: dict[str, Any]) -> str:
        status = stats.get("status", "unprocessed")
        if status == "conflicts":
            n = stats.get("conflicts", 0)
            return f"🔴 {n} конфл."
        if status == "placeholders":
            n = stats.get("placeholders", 0)
            return f"🟡 {n} загл."
        if status == "ready":
            return "🟢 готов"
        return "⚪ не обработан"

    def _update_list_item(self, item: QListWidgetItem, info: ModuleInfo) -> None:
        stats = info.stats
        badge = self._badge_text(stats) if stats else "…"
        item.setText(f"{info.display}    {badge}")
        status = stats.get("status", "unprocessed")
        colors = {
            "ready": QColor("#e8f5e9"),
            "placeholders": QColor("#fff8e1"),
            "conflicts": QColor("#ffebee"),
            "unprocessed": QColor("#f5f5f5"),
        }
        item.setBackground(colors.get(status, QColor("#ffffff")))

    def _apply_filter(self) -> None:
        needle = self._filter_edit.text().strip().lower()
        for i in range(self._module_list.count()):
            item = self._module_list.item(i)
            if not item:
                continue
            name = item.data(Qt.ItemDataRole.UserRole) or ""
            info = self._modules.get(name)
            hay = f"{name} {info.display if info else ''}".lower()
            item.setHidden(bool(needle) and needle not in hay)

    def _current_module_name(self) -> str | None:
        item = self._module_list.currentItem()
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _current_module(self) -> ModuleInfo | None:
        name = self._current_module_name()
        if not name:
            return None
        return self._modules.get(name)

    def _on_module_selected(self, current: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if not current:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        info = self._modules.get(name)
        if info:
            self._update_overview(info)
        if self._tabs.currentIndex() == 2:
            self._reload_conflicts_ui()

    def _update_overview(self, info: ModuleInfo) -> None:
        stats = info.stats or scan_module(info.path)
        total = stats.get("total", 0)
        translated = stats.get("translated", 0)
        placeholders = stats.get("placeholders", 0)
        conflicts = stats.get("conflicts", 0)
        self._module_title.setText(f"{info.display}  ({info.name})")
        self._card_total.set_value(str(total))
        self._card_translated.set_value(str(translated))
        self._card_placeholders.set_value(str(placeholders))
        self._card_conflicts.set_value(str(conflicts))
        pct = int(round(100 * translated / total)) if total else 0
        self._overview_progress.setValue(pct)

    def _set_commands_enabled(self, enabled: bool) -> None:
        for btn in self._action_buttons:
            btn.setEnabled(enabled)
        self._btn_abort.setEnabled(not enabled)

    def _on_cmd_started(self, label: str) -> None:
        self._set_commands_enabled(False)
        self._cmd_progress.setRange(0, 0)
        self._cmd_progress.setVisible(True)
        self._status_label.setText(f"Выполняется: {label}…")

    def _on_cmd_finished(self, exit_code: int) -> None:
        if not self._runner.is_running:
            self._set_commands_enabled(True)
            self._cmd_progress.setVisible(False)
            self._cmd_progress.setRange(0, 100)
            self._cmd_progress.setValue(0)

        if exit_code != 0 and not self._runner.is_running:
            QMessageBox.warning(
                self,
                "Ошибка команды",
                f"Скрипт завершился с кодом {exit_code}.\n\n{self._runner.last_lines_text()}",
            )

        if self._pending_refresh_after_cmd and not self._runner.is_running:
            self._pending_refresh_after_cmd = False
            self._refresh_current_module_stats()
            self._reload_modules()

    def _on_status_text(self, text: str) -> None:
        self._status_label.setText(text)

    def _on_log_line(self, line: str, stream: str) -> None:
        self._log_view.append_line(line, stream)

    def _abort_command(self) -> None:
        self._runner.kill()

    def _refresh_current_module_stats(self) -> None:
        info = self._current_module()
        if not info:
            return

        def work() -> None:
            stats = scan_module(info.path)
            info.stats = stats

        import threading

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(timeout=30)
        self._update_overview(info)
        for i in range(self._module_list.count()):
            item = self._module_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == info.name:
                self._update_list_item(item, info)
                break

    def _build_fill_args(self) -> list[str] | None:
        root = self._current_root()
        if root is None:
            QMessageBox.warning(self, "fill", "Укажите папку проекта.")
            return None

        args = [str(REPO_ROOT / "fill_values_ru_from_library.py")]
        mode_id = self._mode_group.checkedId()
        if mode_id == 1:
            args.append("--library-only")
        elif mode_id == 2:
            args.append("--ensure-dictionary")

        if self._chk_all_modules.isChecked():
            args.extend(["--root", str(root)])
        else:
            info = self._current_module()
            if not info:
                QMessageBox.warning(self, "fill", "Выберите модуль или включите «Все модули».")
                return None
            args.extend(["-m", str(info.path)])

        source_lang = "en" if self._rb_en.isChecked() else "zh-CN"
        args.extend(["--source-lang", source_lang])

        if self._chk_no_overwrite.isChecked():
            args.append("--no-overwrite")
        if self._chk_dry_run.isChecked():
            args.append("--dry-run")
        if self._chk_strings_only.isChecked():
            args.append("--strings-only")
        return args

    def _run_fill(self) -> None:
        args = self._build_fill_args()
        if not args:
            return
        self._pending_refresh_after_cmd = True
        label = "fill"
        if self._chk_auto_collect.isChecked() and not self._chk_dry_run.isChecked():
            root = self._current_root()
            if root:
                collect_args = [
                    str(REPO_ROOT / "library" / "collect_translation_library_ru.py"),
                    "--root",
                    str(root),
                    "--track",
                    "both",
                ]
                self._runner.enqueue(args, label)
                self._runner.enqueue(collect_args, "collect --track both")
                self._tabs.setCurrentIndex(3)
                return
        self._runner.run_single(args, label)
        self._tabs.setCurrentIndex(3)

    def _quick_ensure_dictionary(self) -> None:
        self._rb_ensure_dict.setChecked(True)
        self._run_fill()

    def _quick_collect(self) -> None:
        root = self._current_root()
        if not root:
            QMessageBox.warning(self, "collect", "Укажите папку проекта.")
            return
        args = [
            str(REPO_ROOT / "library" / "collect_translation_library_ru.py"),
            "--root",
            str(root),
            "--track",
            "both",
        ]
        self._pending_refresh_after_cmd = True
        self._runner.run_single(args, "collect")
        self._tabs.setCurrentIndex(3)

    def _quick_sort(self) -> None:
        args = [str(REPO_ROOT / "sort_translation_libraries.py")]
        self._runner.run_single(args, "sort")
        self._tabs.setCurrentIndex(3)

    def _quick_audit(self) -> None:
        args = [
            str(REPO_ROOT / "library" / "audit_translation_library.py"),
            "--min-severity",
            "medium",
        ]
        self._runner.run_single(args, "audit")
        self._tabs.setCurrentIndex(3)

    def _quick_fix_dates(self) -> None:
        args = [str(REPO_ROOT / "library" / "fix_library_date_formats.py")]
        self._runner.run_single(args, "fix date formats")
        self._tabs.setCurrentIndex(3)

    def _build_layout_args(self, mode: str | None = None) -> list[str] | None:
        root = self._current_root()
        if root is None:
            QMessageBox.warning(self, "layout extract", "Укажите папку проекта.")
            return None

        if mode is None:
            mode_id = self._layout_mode_group.checkedId()
            mode = ("report", "inject", "inplace")[max(0, mode_id)]

        args = [str(REPO_ROOT / "layout" / "extract_layout_hardcode.py")]
        if mode == "inject":
            args.append("--inject-values")
        elif mode == "inplace":
            args.append("--translate-inplace")

        if self._chk_all_modules.isChecked():
            args.extend(["--root", str(root)])
        else:
            info = self._current_module()
            if not info:
                QMessageBox.warning(
                    self,
                    "layout extract",
                    "Выберите модуль или включите «Все модули».",
                )
                return None
            args.extend(["-m", str(info.path)])

        if self._chk_layout_dry_run.isChecked() or mode == "report":
            args.append("--dry-run")

        prefix = self._layout_key_prefix.text().strip()
        if prefix:
            args.extend(["--key-prefix", prefix])
        return args

    def _run_layout(self) -> None:
        args = self._build_layout_args()
        if not args:
            return
        mode_id = self._layout_mode_group.checkedId()
        labels = ("layout report", "layout inject", "layout inplace")
        label = labels[max(0, mode_id)]
        self._pending_refresh_after_cmd = True
        self._runner.run_single(args, label)
        self._tabs.setCurrentIndex(3)

    def _quick_layout_scan(self) -> None:
        self._rb_layout_report.setChecked(True)
        args = self._build_layout_args(mode="report")
        if not args:
            return
        self._pending_refresh_after_cmd = True
        self._runner.run_single(args, "layout scan")
        self._tabs.setCurrentIndex(3)

    def _quick_layout_inject(self) -> None:
        self._rb_layout_inject.setChecked(True)
        self._chk_layout_dry_run.setChecked(False)
        args = self._build_layout_args(mode="inject")
        if not args:
            return
        self._pending_refresh_after_cmd = True
        self._runner.run_single(args, "layout inject")
        self._tabs.setCurrentIndex(3)

    def _quick_init_conflicts(self) -> None:
        cmds: list[tuple[list[str], str]] = []
        for track, conflicts_path, library_path, resolutions_path in TRACKS:
            if not conflicts_path.is_file():
                continue
            args = [
                str(REPO_ROOT / "library" / "apply_translation_conflict_resolutions_ru.py"),
                "--init",
                "--majority",
                "--overwrite",
                "--conflicts",
                str(conflicts_path),
                "--resolutions",
                str(resolutions_path),
                "--library",
                str(library_path),
            ]
            cmds.append((args, f"init conflicts ({track})"))
        if not cmds:
            QMessageBox.information(self, "init conflicts", "Файлы конфликтов не найдены в reports/.")
            return
        for args, label in cmds:
            self._runner.enqueue(args, label)
        self._tabs.setCurrentIndex(3)

    def _clear_conflicts_layout(self) -> None:
        while self._conflicts_layout.count() > 1:
            item = self._conflicts_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._conflict_widgets.clear()

    def _reload_conflicts_ui(self) -> None:
        self._clear_conflicts_layout()
        module_name = self._current_module_name() if self._chk_filter_module_conflicts.isChecked() else None

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
                if module_name and module_name not in _modules_in_conflict(item):
                    continue
                merged = dict(item)
                src = str(item.get("source") or "")
                if src in res_map and isinstance(res_map[src], dict):
                    chosen = res_map[src].get("chosen")
                    if chosen:
                        merged["chosen"] = chosen
                widget = ConflictEntryWidget(track, merged)
                self._conflict_widgets.append(widget)
                self._conflicts_layout.insertWidget(self._conflicts_layout.count() - 1, widget)

        if not self._conflict_widgets:
            empty = QLabel("Конфликтов нет (или не найдены для выбранного модуля).")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._conflicts_layout.insertWidget(0, empty)

    def _apply_conflicts(self) -> None:
        if self._runner.is_running:
            return
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

        for widget in self._conflict_widgets:
            chosen = widget.get_chosen()
            if not chosen:
                continue
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
            payload = {
                "schema_version": 1,
                "resolutions": entries,
                "meta": {"from_gui": True, "track": track},
            }
            resolutions_path.parent.mkdir(parents=True, exist_ok=True)
            resolutions_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            args = [
                str(REPO_ROOT / "library" / "apply_translation_conflict_resolutions_ru.py"),
                "--apply",
                "--conflicts",
                str(conflicts_path),
                "--resolutions",
                str(resolutions_path),
                "--library",
                str(library_path),
            ]
            cmds.append((args, f"apply conflicts ({track})"))

        if not cmds:
            QMessageBox.information(self, "Конфликты", "Нет выбранных решений для применения.")
            return

        self._pending_refresh_after_cmd = True
        for args, label in cmds:
            self._runner.enqueue(args, label)
        self._tabs.setCurrentIndex(3)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(SETTINGS_APP)
    app.setOrganizationName(SETTINGS_ORG)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
