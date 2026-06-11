from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSettings, QSize, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
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

from gui_pkg.config import REPO_ROOT, ROOT_PRESETS, SETTINGS_APP, SETTINGS_ORG, TRACKS
from gui_pkg.process import ProcessController
from gui_pkg.scanner import (
    ModuleInfo,
    badge_text,
    discover_modules,
    display_module_name,
    modules_in_conflict,
    scan_module,
)
from gui_pkg.theme import ThemeManager
from gui_pkg.widgets import ConflictEntryWidget, LogView, ModuleListRow, StatCard
from gui_pkg.workers import ModuleScanWorker


class MainWindow(QMainWindow):
    def __init__(self, theme_mgr: ThemeManager) -> None:
        super().__init__()
        self._theme_mgr = theme_mgr
        self._theme = theme_mgr.current
        theme_mgr.changed.connect(self._on_theme_changed)
        self.setWindowTitle("Automotive Translator")
        self.setMinimumSize(1000, 650)
        self.resize(1200, 750)

        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._modules: dict[str, ModuleInfo] = {}
        self._module_rows: dict[str, tuple[QListWidgetItem, ModuleListRow]] = {}
        self._scan_worker: ModuleScanWorker | None = None
        self._stats_refresh_worker: ModuleScanWorker | None = None
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
        central.setObjectName("centralRoot")
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 6)
        root_layout.setSpacing(8)

        title_bar = QWidget()
        title_bar.setObjectName("titleBar")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(14, 10, 14, 10)
        title_layout.setSpacing(12)
        self._btn_theme = QPushButton(self._theme_mgr.toggle_button_icon())
        self._btn_theme.setObjectName("themeToggleBtn")
        self._btn_theme.setToolTip(self._theme_mgr.toggle_button_tooltip())
        self._btn_theme.clicked.connect(self._toggle_theme)
        title_layout.addWidget(self._btn_theme)
        self._app_title = QLabel("Automotive Translator")
        self._app_title.setStyleSheet(self._theme.title_label_style())
        self._path_label = QLabel("Папка не выбрана")
        self._path_label.setStyleSheet(self._theme.path_label_style())
        title_layout.addWidget(self._app_title)
        title_layout.addWidget(self._path_label, stretch=1)
        btn_browse = QPushButton("Сменить папку")
        btn_browse.clicked.connect(self._browse_root)
        btn_reload = QPushButton("Обновить")
        btn_reload.clicked.connect(self._reload_modules)
        title_layout.addWidget(btn_browse)
        title_layout.addWidget(btn_reload)
        root_layout.addWidget(title_bar)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(4, 0, 4, 0)
        path_row.addWidget(QLabel("Папка проекта:"))
        self._root_combo = QComboBox()
        self._root_combo.setMinimumWidth(320)
        self._root_combo.setEditable(True)
        self._root_combo.currentIndexChanged.connect(self._on_root_changed)
        path_row.addWidget(self._root_combo, stretch=1)
        root_layout.addLayout(path_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        sidebar = QWidget()
        sidebar.setObjectName("sidebarPanel")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        sidebar_head = QWidget()
        sidebar_head_layout = QVBoxLayout(sidebar_head)
        sidebar_head_layout.setContentsMargins(14, 12, 14, 8)
        modules_label = QLabel("МОДУЛИ")
        modules_label.setObjectName("sectionLabel")
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Поиск…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        sidebar_head_layout.addWidget(modules_label)
        sidebar_head_layout.addWidget(self._filter_edit)
        sidebar_layout.addWidget(sidebar_head)
        self._module_list = QListWidget()
        self._module_list.currentItemChanged.connect(self._on_module_selected)
        sidebar_layout.addWidget(self._module_list)
        splitter.addWidget(sidebar)

        content = QWidget()
        content.setObjectName("contentPanel")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_overview_tab(), "Обзор")
        self._tabs.addTab(self._build_actions_tab(), "Действия")
        self._tabs.addTab(self._build_conflicts_tab(), "Конфликты")
        self._tabs.addTab(self._build_log_tab(), "Лог")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        content_layout.addWidget(self._tabs)
        splitter.addWidget(content)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 900])
        root_layout.addWidget(splitter, stretch=1)

        status = QStatusBar()
        self.setStatusBar(status)
        self._status_label = QLabel("Готово")
        self._cmd_progress = QProgressBar()
        self._cmd_progress.setObjectName("cmdProgress")
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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self._card_total = StatCard("Всего строк", theme=self._theme)
        self._card_translated = StatCard("Переведено", tone="success", theme=self._theme)
        self._card_placeholders = StatCard("Заглушек", tone="warning", theme=self._theme)
        self._card_conflicts = StatCard("Конфликтов", tone="danger", theme=self._theme)
        for card in (
            self._card_total,
            self._card_translated,
            self._card_placeholders,
            self._card_conflicts,
        ):
            cards.addWidget(card)
        layout.addLayout(cards)

        progress_row = QHBoxLayout()
        self._progress_label = QLabel("Прогресс")
        self._progress_label.setStyleSheet(self._theme.progress_label_style())
        self._overview_progress = QProgressBar()
        self._overview_progress.setFormat("%p%")
        self._overview_pct = QLabel("0%")
        self._overview_pct.setStyleSheet(self._theme.progress_pct_style())
        self._overview_pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_row.addWidget(self._progress_label)
        progress_row.addWidget(self._overview_progress, stretch=1)
        progress_row.addWidget(self._overview_pct)
        layout.addLayout(progress_row)

        self._module_title = QLabel("Модуль не выбран")
        self._module_title.setObjectName("moduleTitle")
        layout.addWidget(self._module_title)

        quick_label = QLabel("БЫСТРЫЕ ДЕЙСТВИЯ")
        quick_label.setObjectName("sectionLabel")
        layout.addWidget(quick_label)
        quick = QGroupBox()
        quick_layout = QHBoxLayout(quick)
        quick_layout.setSpacing(8)
        actions = [
            ("Дополнить словарь", self._quick_ensure_dictionary, True),
            ("Собрать из APK", self._quick_collect, False),
            ("Сортировать", self._quick_sort, False),
            ("Проверка словаря", self._quick_audit, False),
            ("Формат дат", self._quick_fix_dates, False),
            ("Шаблон конфликтов", self._quick_init_conflicts, False),
            ("Поиск хардкода", self._quick_layout_scan, False),
            ("Хардкод → strings", self._quick_layout_inject, False),
        ]
        for label, handler, primary in actions:
            btn = QPushButton(label)
            if primary:
                btn.setObjectName("primaryBtn")
            btn.clicked.connect(handler)
            quick_layout.addWidget(btn)
            self._action_buttons.append(btn)
        layout.addWidget(quick)
        layout.addStretch()
        scroll.setWidget(w)
        return scroll

    def _build_actions_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        mode_group = QGroupBox("Заполнение переводов в values-ru")
        mode_layout = QVBoxLayout(mode_group)
        self._mode_group = QButtonGroup(self)
        self._rb_normal = QRadioButton("Сначала словарь, остальное — через Google")
        self._rb_library_only = QRadioButton("Только из словаря (без Google)")
        self._rb_ensure_dict = QRadioButton("Дополнить словарь заглушками")
        self._rb_normal.setChecked(True)
        for i, rb in enumerate((self._rb_normal, self._rb_library_only, self._rb_ensure_dict)):
            self._mode_group.addButton(rb, i)
            mode_layout.addWidget(rb)
        layout.addWidget(mode_group)

        lang_group = QGroupBox("Язык оригинала в APK")
        lang_layout = QHBoxLayout(lang_group)
        self._lang_group = QButtonGroup(self)
        self._rb_zh = QRadioButton("Китайский")
        self._rb_en = QRadioButton("Английский")
        self._rb_zh.setChecked(True)
        self._lang_group.addButton(self._rb_zh, 0)
        self._lang_group.addButton(self._rb_en, 1)
        lang_layout.addWidget(self._rb_zh)
        lang_layout.addWidget(self._rb_en)
        layout.addWidget(lang_group)

        opts_group = QGroupBox("Дополнительно")
        opts_layout = QVBoxLayout(opts_group)
        self._chk_no_overwrite = QCheckBox("Не перезаписывать уже переведённое")
        self._chk_dry_run = QCheckBox("Только показать, без записи в файлы")
        self._chk_strings_only = QCheckBox("Только strings.xml (без plurals и arrays)")
        self._chk_all_modules = QCheckBox("Обработать все модули в папке")
        self._chk_all_modules.setChecked(True)
        self._chk_auto_collect = QCheckBox("После перевода обновить общий словарь")
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

        self._btn_run_fill = QPushButton("Начать перевод")
        self._btn_run_fill.setObjectName("primaryBtn")
        self._btn_run_fill.clicked.connect(self._run_fill)
        layout.addWidget(self._btn_run_fill)
        self._action_buttons.append(self._btn_run_fill)

        layout_group = QGroupBox("Текст прямо в layout-файлах")
        layout_form = QVBoxLayout(layout_group)
        self._layout_mode_group = QButtonGroup(self)
        self._rb_layout_report = QRadioButton("Найти и показать отчёт")
        self._rb_layout_inject = QRadioButton("Вынести в strings.xml (рекомендуется)")
        self._rb_layout_inplace = QRadioButton("Перевести прямо в layout")
        self._rb_layout_inject.setChecked(True)
        for i, rb in enumerate(
            (self._rb_layout_report, self._rb_layout_inject, self._rb_layout_inplace)
        ):
            self._layout_mode_group.addButton(rb, i)
            layout_form.addWidget(rb)
        self._chk_layout_dry_run = QCheckBox("Только показать, без записи в файлы")
        layout_form.addWidget(self._chk_layout_dry_run)
        prefix_row = QHBoxLayout()
        prefix_row.addWidget(QLabel("Префикс новых ключей:"))
        self._layout_key_prefix = QLineEdit("hw")
        self._layout_key_prefix.setMaximumWidth(120)
        prefix_row.addWidget(self._layout_key_prefix)
        prefix_row.addStretch()
        layout_form.addLayout(prefix_row)
        scope_note = QLabel(
            "Обрабатываются все модули в папке или только выбранный слева — "
            "см. настройку «Обработать все модули в папке» выше."
        )
        scope_note.setObjectName("hintLabel")
        scope_note.setWordWrap(True)
        layout_form.addWidget(scope_note)
        self._btn_run_layout = QPushButton("Обработать layout")
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

        toolbar = QHBoxLayout()
        self._chk_filter_module_conflicts = QCheckBox("Показывать только конфликты выбранного модуля")
        self._chk_filter_module_conflicts.setChecked(True)
        self._chk_filter_module_conflicts.stateChanged.connect(self._reload_conflicts_ui)
        toolbar.addWidget(self._chk_filter_module_conflicts)
        btn_reload = QPushButton("Обновить список")
        btn_reload.clicked.connect(self._reload_conflicts_ui)
        toolbar.addWidget(btn_reload)
        btn_init = QPushButton("Подставить популярный вариант")
        btn_init.setToolTip("Для каждого конфликта выбрать перевод, который встречается в большинстве модулей")
        btn_init.clicked.connect(self._quick_init_conflicts)
        toolbar.addWidget(btn_init)
        btn_select_all = QPushButton("Выделить все")
        btn_select_all.clicked.connect(self._highlight_all_conflicts)
        toolbar.addWidget(btn_select_all)
        btn_clear_sel = QPushButton("Снять выделение")
        btn_clear_sel.clicked.connect(self._clear_conflict_highlights)
        toolbar.addWidget(btn_clear_sel)
        toolbar.addStretch()
        btn_apply_marked = QPushButton("Сохранить выделенные")
        btn_apply_marked.setToolTip("Записать в словарь только блоки с синей рамкой")
        btn_apply_marked.setObjectName("primaryBtn")
        btn_apply_marked.clicked.connect(lambda: self._apply_conflicts(only_highlighted=True))
        self._btn_apply_marked_conflicts = btn_apply_marked
        toolbar.addWidget(btn_apply_marked)
        btn_apply = QPushButton("Сохранить все на экране")
        btn_apply.setToolTip(
            "Записать в словарь все конфликты, которые сейчас видны в списке ниже "
            "(с выбранным вариантом перевода)"
        )
        btn_apply.clicked.connect(lambda: self._apply_conflicts(only_highlighted=False))
        self._btn_apply_conflicts = btn_apply
        toolbar.addWidget(btn_apply)
        layout.addLayout(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._conflicts_container = QWidget()
        self._conflicts_layout = QVBoxLayout(self._conflicts_container)
        self._conflicts_layout.setSpacing(10)
        self._conflicts_layout.setContentsMargins(0, 0, 0, 0)
        self._conflicts_layout.addStretch()
        scroll.setWidget(self._conflicts_container)
        layout.addWidget(scroll)

        self._action_buttons.extend([btn_init, btn_apply_marked, btn_apply])
        return w

    def _build_log_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        bar = QHBoxLayout()
        btn_clear = QPushButton("Очистить")
        btn_clear.clicked.connect(lambda: self._log_view.clear())
        bar.addStretch()
        bar.addWidget(btn_clear)
        layout.addLayout(bar)
        self._log_view = LogView(theme=self._theme)
        layout.addWidget(self._log_view)
        return w

    def _toggle_theme(self) -> None:
        self._theme_mgr.toggle()

    def _on_theme_changed(self) -> None:
        self._theme = self._theme_mgr.current
        app = QApplication.instance()
        if isinstance(app, QApplication):
            self._theme_mgr.apply(app)
        self._btn_theme.setText(self._theme_mgr.toggle_button_icon())
        self._btn_theme.setToolTip(self._theme_mgr.toggle_button_tooltip())
        self._refresh_theme_styles()
        if self._tabs.currentIndex() == 2:
            self._reload_conflicts_ui()

    def _refresh_theme_styles(self) -> None:
        self._app_title.setStyleSheet(self._theme.title_label_style())
        self._path_label.setStyleSheet(self._theme.path_label_style())
        self._progress_label.setStyleSheet(self._theme.progress_label_style())
        self._overview_pct.setStyleSheet(self._theme.progress_pct_style())
        for card in (
            self._card_total,
            self._card_translated,
            self._card_placeholders,
            self._card_conflicts,
        ):
            card.apply_theme(self._theme)
        self._log_view.apply_theme(self._theme)
        for widget in self._conflict_widgets:
            widget.apply_theme(self._theme)
        self._refresh_module_selection_styles()
        info = self._current_module()
        if info:
            self._update_overview(info)

    def _update_path_label(self) -> None:
        root = self._current_root()
        if root is None:
            self._path_label.setText("Папка не выбрана")
            return
        n = len(self._modules)
        suffix = "модулей" if n != 1 else "модуль"
        self._path_label.setText(f"{root} — {n} {suffix}")

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
        self._module_rows.clear()
        self._module_list.clear()
        for mod in modules:
            info = ModuleInfo(path=mod, name=mod.name, display=display_module_name(mod.name))
            self._modules[mod.name] = info
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, mod.name)
            item.setSizeHint(QSize(0, 40))
            row = ModuleListRow(info.display, "…", "unprocessed", theme=self._theme)
            self._module_list.addItem(item)
            self._module_list.setItemWidget(item, row)
            self._module_rows[mod.name] = (item, row)

        self._update_path_label()

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
        self._update_list_item(name)
        if self._current_module_name() == name:
            self._update_overview(info)

    def _on_scan_finished(self) -> None:
        if not self._runner.is_running:
            self._status_label.setText("Готово")
        self._update_path_label()
        self._apply_filter()
        self._refresh_module_selection_styles()

    def _update_list_item(self, name: str) -> None:
        info = self._modules.get(name)
        row_data = self._module_rows.get(name)
        if not info or not row_data:
            return
        item, row = row_data
        stats = info.stats
        badge = badge_text(stats) if stats else "…"
        status = stats.get("status", "unprocessed")
        selected = self._module_list.currentItem() is item
        row.update_row(info.display, badge, status, selected=selected)

    def _refresh_module_selection_styles(self) -> None:
        current = self._current_module_name()
        for name, (_item, row) in self._module_rows.items():
            row.apply_theme(self._theme)
            info = self._modules.get(name)
            if not info:
                continue
            stats = info.stats or {}
            badge = badge_text(stats) if stats else "…"
            status = stats.get("status", "unprocessed")
            row.update_row(info.display, badge, status, selected=(name == current))

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
        self._refresh_module_selection_styles()
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
        self._overview_pct.setText(f"{pct}%")

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
        if self._stats_refresh_worker and self._stats_refresh_worker.isRunning():
            return

        worker = ModuleScanWorker([info.path], self)
        self._stats_refresh_worker = worker
        module_name = info.name

        def on_scanned(name: str, stats: dict) -> None:
            if name != module_name:
                return
            target = self._modules.get(name)
            if not target:
                return
            target.stats = stats
            self._update_list_item(name)
            if self._current_module_name() == name:
                self._update_overview(target)

        worker.module_scanned.connect(on_scanned)
        worker.finished.connect(worker.deleteLater)
        worker.start()

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

    def _write_conflict_resolutions(
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
                if module_name and module_name not in modules_in_conflict(item):
                    continue
                merged = dict(item)
                src = str(item.get("source") or "")
                if src in res_map and isinstance(res_map[src], dict):
                    chosen = res_map[src].get("chosen")
                    if chosen:
                        merged["chosen"] = chosen
                widget = ConflictEntryWidget(track, merged, theme=self._theme)
                widget.chosen_changed.connect(self._update_conflicts_summary)
                widget.highlight_changed.connect(self._update_conflicts_summary)
                self._conflict_widgets.append(widget)
                self._conflicts_layout.insertWidget(self._conflicts_layout.count() - 1, widget)

        if not self._conflict_widgets:
            empty = QLabel("Конфликтов нет (или не найдены для выбранного модуля).")
            empty.setObjectName("hintLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._conflicts_layout.insertWidget(0, empty)

        self._update_conflicts_summary()

    def _count_ready_conflicts(self) -> tuple[int, int, int]:
        """(с вариантом перевода, выделено, всего на экране)."""
        total = len(self._conflict_widgets)
        ready = sum(1 for w in self._conflict_widgets if w.get_chosen())
        highlighted = sum(1 for w in self._conflict_widgets if w.is_highlighted())
        return ready, highlighted, total

    def _highlight_all_conflicts(self) -> None:
        for widget in self._conflict_widgets:
            widget.set_highlighted(True)
        self._update_conflicts_summary()

    def _clear_conflict_highlights(self) -> None:
        for widget in self._conflict_widgets:
            widget.set_highlighted(False)
        self._update_conflicts_summary()

    def _update_conflicts_summary(self) -> None:
        ready, highlighted, total = self._count_ready_conflicts()
        marked_ready = sum(
            1 for w in self._conflict_widgets if w.is_highlighted() and w.get_chosen()
        )
        if total == 0:
            self._conflicts_summary.setText("На экране нет конфликтов.")
            self._btn_apply_conflicts.setText("Сохранить все на экране")
            self._btn_apply_marked_conflicts.setText("Сохранить выделенные")
            self._btn_apply_conflicts.setEnabled(False)
            self._btn_apply_marked_conflicts.setEnabled(False)
            return
        self._btn_apply_conflicts.setEnabled(ready > 0)
        self._btn_apply_marked_conflicts.setEnabled(marked_ready > 0)
        if self._chk_filter_module_conflicts.isChecked():
            scope = "только выбранного модуля"
        else:
            scope = "всего проекта"
        self._conflicts_summary.setText(
            f"На экране: {total} ({scope}). "
            f"Выделено: {highlighted}. "
            f"Готово к сохранению: {ready} (выделенных: {marked_ready})."
        )
        self._btn_apply_marked_conflicts.setText(f"Сохранить выделенные ({marked_ready})")
        self._btn_apply_conflicts.setText(f"Сохранить все на экране ({ready})")

    def _apply_conflicts(self, *, only_highlighted: bool) -> None:
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
            self._write_conflict_resolutions(resolutions_path, entries, track, merge=only_highlighted)
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

        self._pending_refresh_after_cmd = True
        for args, label in cmds:
            self._runner.enqueue(args, label)
        self._tabs.setCurrentIndex(3)
