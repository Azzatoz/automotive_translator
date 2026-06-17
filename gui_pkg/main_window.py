from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSettings, QSize, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QResizeEvent, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.backup import backup_module_values_ru, backup_modules_values_ru
from gui_pkg.confirm import confirm_dangerous_action
from gui_pkg.faq import show_faq
from gui_pkg.fill_module_dialog import (
    FillModuleDialog,
    FillModuleOptions,
    build_fill_module_args,
)
from gui_pkg.module_align import (
    collect_module_dict_mismatches,
    updates_for_sources,
)
from gui_pkg.module_align_dialog import ModuleAlignDialog
from gui_pkg.placeholders_dialog import PlaceholdersDialog
from gui_pkg.config import (
    LIBRARY_DIR,
    REPO_ROOT,
    RESOLUTIONS_EN,
    RESOLUTIONS_ZH,
    ROOT_PRESETS,
    SCRIPTS_DIR,
    SETTINGS_APP,
    SETTINGS_ORG,
    TAB_CONFLICTS,
    TAB_LOG,
    TAB_PENDING,
    TRACKS,
)
from gui_pkg.conflicts_panel import ConflictsPanel
from gui_pkg.module_sidebar import ModuleSidebar
from gui_pkg.dictionary_panel import DictionaryPanel
from gui_pkg.dictionary_search_dialog import DictionarySearchDialog
from gui_pkg.translate_panel import TranslatePanel
from gui_pkg.layout_panel import LayoutPanel
from gui_pkg.placeholder_editor import apply_placeholder_translations
from gui_pkg.process import ProcessController
from gui_pkg.scanner import (
    ModuleInfo,
    aggregate_project_stats,
    discover_modules,
    display_module_name,
    load_conflicts_cache,
    modules_in_conflict,
    scan_module,
)
from gui_pkg.responsive import (
    BREAKPOINT_NARROW,
    SIDEBAR_MODE_FULL,
    SIDEBAR_MODE_HIDDEN,
    SIDEBAR_MODE_OPEN,
    SIDEBAR_OPEN_WIDTH,
    next_sidebar_mode,
    normalize_sidebar_mode,
    relayout_action_grid,
    relayout_grid,
    sidebar_mode_button_icon,
    sidebar_mode_tooltip,
    title_bar_compact,
)
from gui_pkg.theme import ThemeManager
from gui_pkg.widgets import ActionButton, LogView, StatCard
from gui_pkg.workers import ModuleScanWorker


class MainWindow(QMainWindow):
    def __init__(self, theme_mgr: ThemeManager) -> None:
        super().__init__()
        self._theme_mgr = theme_mgr
        self._theme = theme_mgr.current
        theme_mgr.changed.connect(self._on_theme_changed)
        self.setWindowTitle("Automotive Translator")
        self.setMinimumSize(880, 620)
        self.resize(1320, 800)

        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._sidebar_mode = normalize_sidebar_mode(
            str(self._settings.value("sidebar_mode", SIDEBAR_MODE_OPEN))
        )
        self._splitter: QSplitter | None = None
        self._sidebar: QWidget | None = None
        self._content_panel: QWidget | None = None
        self._btn_sidebar_mode: QPushButton | None = None
        self._overview_content: QWidget | None = None
        self._stats_grid: QGridLayout | None = None
        self._stats_cards: list[StatCard] = []
        self._quick_grid: QGridLayout | None = None
        self._quick_buttons: list[ActionButton] = []
        self._conflicts_panel: ConflictsPanel | None = None
        self._module_sidebar: ModuleSidebar | None = None
        self._translate_panel: TranslatePanel | None = None
        self._layout_panel: LayoutPanel | None = None
        self._btn_browse: QPushButton | None = None
        self._btn_reload: QPushButton | None = None
        self._modules: dict[str, ModuleInfo] = {}
        self._scan_worker: ModuleScanWorker | None = None
        self._stats_refresh_worker: ModuleScanWorker | None = None
        self._pending_stats_modules: set[str] = set()
        self._pending_refresh_after_cmd = False
        self._refresh_modules_after_cmd = True
        self._action_buttons: list[QPushButton] = []

        self._runner = ProcessController(self)
        self._runner.line_received.connect(self._on_log_line)
        self._runner.started.connect(self._on_cmd_started)
        self._runner.finished.connect(self._on_cmd_finished)
        self._runner.status_changed.connect(self._on_status_text)

        self._build_ui()
        self._load_root_presets()
        self._restore_last_root()
        self._refresh_google_module_filter()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("centralRoot")
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 6)
        root_layout.setSpacing(8)

        self._title_bar = QWidget()
        self._title_bar.setObjectName("titleBar")
        title_bar = self._title_bar
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(14, 10, 14, 10)
        title_layout.setSpacing(12)
        self._btn_theme = QPushButton(self._theme_mgr.toggle_button_icon())
        self._btn_theme.setObjectName("themeToggleBtn")
        self._btn_theme.setToolTip(self._theme_mgr.toggle_button_tooltip())
        self._btn_theme.clicked.connect(self._toggle_theme)
        title_layout.addWidget(self._btn_theme)
        self._btn_faq = QPushButton("?")
        self._btn_faq.setObjectName("faqBtn")
        self._btn_faq.setFixedWidth(36)
        self._btn_faq.setToolTip("Справка (FAQ)")
        self._btn_faq.clicked.connect(self._show_faq)
        title_layout.addWidget(self._btn_faq)
        self._btn_sidebar_mode = QPushButton(sidebar_mode_button_icon(self._sidebar_mode))
        self._btn_sidebar_mode.setObjectName("sidebarModeBtn")
        self._btn_sidebar_mode.setToolTip(sidebar_mode_tooltip(self._sidebar_mode))
        self._btn_sidebar_mode.clicked.connect(self._cycle_sidebar_mode)
        title_layout.addWidget(self._btn_sidebar_mode)
        self._app_title = QLabel("Automotive Translator")
        self._app_title.setStyleSheet(self._theme.title_label_style())
        self._path_label = QLabel("Папка не выбрана")
        self._path_label.setStyleSheet(self._theme.path_label_style())
        title_layout.addWidget(self._app_title)
        title_layout.addWidget(self._path_label, stretch=1)
        self._btn_browse = QPushButton("Сменить папку")
        self._btn_browse.clicked.connect(self._browse_root)
        self._btn_reload = QPushButton("Обновить")
        self._btn_reload.clicked.connect(self._reload_modules)
        title_layout.addWidget(self._btn_browse)
        title_layout.addWidget(self._btn_reload)
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

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter = self._splitter
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        sidebar = QWidget()
        self._sidebar = sidebar
        sidebar.setObjectName("sidebarPanel")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        self._module_sidebar = ModuleSidebar(theme=self._theme)
        self._module_sidebar.module_selected.connect(self._on_sidebar_module_selected)
        self._module_sidebar.module_double_clicked.connect(self._on_sidebar_module_double_clicked)
        self._module_sidebar.context_menu_requested.connect(self._on_sidebar_context_menu)
        sidebar_layout.addWidget(self._module_sidebar)
        self._module_list = self._module_sidebar.list_widget
        splitter.addWidget(sidebar)

        content = QWidget()
        self._content_panel = content
        content.setObjectName("contentPanel")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self._translate_panel = TranslatePanel(
            get_root=self._current_root,
            get_current_module=self._current_module,
            get_module_count=lambda: len(self._modules),
            on_run_fill=self._run_fill,
            on_dict_placeholders_json=self._quick_dict_placeholders_json,
            parent=self,
        )
        self._action_buttons.append(self._translate_panel.run_fill_button)
        if hasattr(self._translate_panel, "dict_placeholders_json_button"):
            self._action_buttons.append(self._translate_panel.dict_placeholders_json_button)
        self._layout_panel = LayoutPanel(
            get_root=self._current_root,
            get_current_module=self._current_module,
            scope_is_all_modules=lambda: (
                self._translate_panel.scope_is_all_modules()
                if self._translate_panel
                else True
            ),
            parent=self,
        )
        self._layout_panel.run_button.clicked.connect(self._run_layout)
        self._layout_panel.scan_button.clicked.connect(self._quick_layout_scan)
        self._action_buttons.extend(
            (self._layout_panel.run_button, self._layout_panel.scan_button)
        )
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_overview_tab(), "Обзор")
        self._tabs.addTab(self._build_actions_tab(), "Действия")
        self._conflicts_panel = ConflictsPanel(
            theme=self._theme,
            runner=self._runner,
            get_current_module_name=self._current_module_name,
            get_modules=lambda: self._modules,
            update_list_item=self._update_list_item,
            update_overview=self._update_overview,
            log_line=self._on_log_line,
            on_apply_apk_sources=self._apply_sources_to_apk_modules,
            on_init_conflicts=self._quick_init_conflicts,
        )
        self._conflicts_panel.commands_enqueued.connect(self._on_conflicts_commands_enqueued)
        self._tabs.addTab(self._conflicts_panel, "Конфликты")
        self._action_buttons.extend(self._conflicts_panel.toolbar_buttons[1:])
        self._dictionary_panel = DictionaryPanel(runner=self._runner, theme=self._theme)
        self._dictionary_panel.merge_requested.connect(self._on_pending_merge_requested)
        self._dictionary_panel.search_requested.connect(self._open_dictionary_search)
        self._tabs.addTab(self._dictionary_panel, "Словарь")
        self._tabs.addTab(self._build_log_tab(), "Лог")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        content_layout.addWidget(self._tabs)
        splitter.addWidget(content)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root_layout.addWidget(splitter, stretch=1)
        self._apply_sidebar_mode()

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
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._project_summary = QLabel("Проект: загрузите папку и нажмите «Обновить»")
        self._project_summary.setObjectName("hintLabel")
        self._project_summary.setWordWrap(True)
        layout.addWidget(self._project_summary)

        self._project_progress = QProgressBar()
        self._project_progress.setFormat("Проект %p%")
        layout.addWidget(self._project_progress)

        mod_label = QLabel("ВЫБРАННЫЙ МОДУЛЬ")
        mod_label.setObjectName("sectionLabel")
        layout.addWidget(mod_label)

        self._stats_grid = QGridLayout()
        self._stats_grid.setSpacing(10)
        self._card_total = StatCard("Всего строк", theme=self._theme)
        self._card_translated = StatCard("Переведено", tone="success", theme=self._theme)
        self._card_placeholders = StatCard("Заглушек", tone="warning", theme=self._theme)
        self._card_conflicts = StatCard("Конфликтов", tone="danger", theme=self._theme)
        self._stats_cards = [
            self._card_total,
            self._card_translated,
            self._card_placeholders,
            self._card_conflicts,
        ]
        layout.addLayout(self._stats_grid)

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

        layout.addWidget(self._translate_panel)

        maint_label = QLabel("БЫСТРЫЕ ДЕЙСТВИЯ")
        maint_label.setObjectName("sectionLabel")
        layout.addWidget(maint_label)
        quick = QGroupBox()
        self._quick_grid = QGridLayout(quick)
        self._quick_grid.setSpacing(8)
        actions: list[tuple[str, str, object, bool]] = [
            (
                "Добавить в словарь пропущенные строки с заглушкой « »",
                "Заглушки\nв словарь",
                self._quick_placeholders,
                True,
            ),
            (
                "Добавить пропуски только в JSON-словарь, APK не меняется "
                "(collect --add-missing-placeholders; область — переключатель «Модули» выше)",
                "Заглушки\nтолько JSON",
                self._quick_dict_placeholders_json,
                False,
            ),
            (
                "Исправить в словарях шаблоны дат (月/年/日 → dd.MM.yyyy и плейсхолдеры)",
                "Формат\nдат",
                self._quick_fix_dates,
                False,
            ),
            (
                "Создать resolutions.json из conflicts — вариант с большинством модулей",
                "Шаблон\nконфл.",
                self._quick_init_conflicts,
                False,
            ),
            ("Поиск хардкода", "Скан\nlayout", self._quick_layout_scan, False),
            ("Перенести хардкод в strings", "В\nstrings", self._quick_layout_inject, False),
        ]
        self._quick_buttons = []
        for full_label, short_label, handler, primary in actions:
            btn = ActionButton(full_label, short_label, primary=primary)
            btn.clicked.connect(handler)  # type: ignore[arg-type]
            self._quick_buttons.append(btn)
            self._action_buttons.append(btn)
        layout.addWidget(quick)
        layout.addStretch()
        self._overview_content = w
        scroll.setWidget(w)
        relayout_grid(
            self._stats_grid,
            self._stats_cards,
            container_width=1200,
            wide_columns=4,
            narrow_columns=2,
            breakpoint=BREAKPOINT_NARROW,
        )
        relayout_action_grid(
            self._quick_grid,
            self._quick_buttons,
            container_width=1200,
            max_columns=4,
        )
        return scroll

    def _build_actions_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        layout.addWidget(self._layout_panel)

        # ── 2. Обслуживание словаря ───────────────────────────────────────
        dict_group = QGroupBox("2.  Обслуживание словаря")
        dict_form = QVBoxLayout(dict_group)
        dict_form.setSpacing(10)

        dict_hint = QLabel(
            "<b>Сортировать</b> — расставляет ключи A–Z, заглушки переносит в конец. "
            "Запускайте после массовых правок JSON.<br>"
            "<b>Аудит</b> — ищет подозрительные строки (Win→Победа, незакрытые теги). "
            "Только отчёт, ничего не меняет.<br>"
            "<b>Исправить даты</b> — заменяет «ММ месяц» на d.M.y и аналогичные шаблоны."
        )
        dict_hint.setObjectName("hintLabel")
        dict_hint.setWordWrap(True)
        dict_hint.setTextFormat(Qt.TextFormat.RichText)
        dict_form.addWidget(dict_hint)

        util_row = QHBoxLayout()
        btn_dict_search = QPushButton("Поиск в словаре…")
        btn_dict_search.setToolTip("Поиск по исходнику, переводу и модулям с правкой JSON")
        btn_dict_search.clicked.connect(self._open_dictionary_search)
        self._action_buttons.append(btn_dict_search)

        btn_sort = QPushButton("Сортировать словарь")
        btn_sort.setToolTip("sort_translation_libraries.py")
        btn_sort.clicked.connect(self._quick_sort)
        self._action_buttons.append(btn_sort)

        btn_audit = QPushButton("Аудит переводов")
        btn_audit.setToolTip("audit_translation_library.py --min-severity medium")
        btn_audit.clicked.connect(self._quick_audit)
        self._action_buttons.append(btn_audit)

        btn_fix = QPushButton("Исправить даты")
        btn_fix.setToolTip("fix_library_date_formats.py")
        btn_fix.clicked.connect(self._quick_fix_dates)
        self._action_buttons.append(btn_fix)

        for btn in (btn_dict_search, btn_sort, btn_audit, btn_fix):
            util_row.addWidget(btn)
        util_row.addStretch()
        dict_form.addLayout(util_row)

        layout.addWidget(dict_group)

        layout.addStretch()
        scroll.setWidget(w)
        return scroll

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

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._apply_sidebar_mode()
        self._apply_responsive_layout()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_sidebar_mode()
        self._apply_responsive_layout()

    def _cycle_sidebar_mode(self) -> None:
        self._sidebar_mode = next_sidebar_mode(self._sidebar_mode)
        self._settings.setValue("sidebar_mode", self._sidebar_mode)
        self._apply_sidebar_mode()
        if self._btn_sidebar_mode:
            self._btn_sidebar_mode.setText(sidebar_mode_button_icon(self._sidebar_mode))
            self._btn_sidebar_mode.setToolTip(sidebar_mode_tooltip(self._sidebar_mode))

    def _apply_sidebar_mode(self) -> None:
        if not self._splitter or not self._sidebar or not self._content_panel:
            return

        mode = self._sidebar_mode
        sidebar = self._sidebar
        content = self._content_panel
        splitter = self._splitter
        total = max(splitter.width(), 1)
        handle = splitter.handle(1)
        open_width = min(SIDEBAR_OPEN_WIDTH, max(280, total - 320))

        handle.setEnabled(False)
        sidebar.setMinimumWidth(0)
        sidebar.setMaximumWidth(16777215)
        content.setMinimumWidth(0)

        if mode == SIDEBAR_MODE_HIDDEN:
            sidebar.setVisible(False)
            content.setVisible(True)
        elif mode == SIDEBAR_MODE_OPEN:
            sidebar.setVisible(True)
            content.setVisible(True)
            sidebar.setMinimumWidth(open_width)
            sidebar.setMaximumWidth(open_width)
            content.setMinimumWidth(320)
            splitter.setSizes([open_width, max(1, total - open_width)])
        else:  # SIDEBAR_MODE_FULL
            sidebar.setVisible(True)
            content.setVisible(False)
            sidebar.setMinimumWidth(280)

    def _content_area_width(self) -> int:
        if self._sidebar_mode == SIDEBAR_MODE_FULL:
            return BREAKPOINT_NARROW
        if self._tabs and self._tabs.width() > 0:
            return self._tabs.width()
        if self._overview_content and self._overview_content.width() > 0:
            return self._overview_content.width()
        if self._sidebar_mode == SIDEBAR_MODE_HIDDEN:
            return max(self.width() - 40, 320)
        return max(self.width() - SIDEBAR_OPEN_WIDTH, 320)

    def _apply_responsive_layout(self) -> None:
        content_w = self._content_area_width()
        if self._stats_grid and self._stats_cards:
            relayout_grid(
                self._stats_grid,
                self._stats_cards,
                container_width=content_w,
                wide_columns=4,
                narrow_columns=2,
                breakpoint=BREAKPOINT_NARROW,
            )
        if self._quick_grid and self._quick_buttons:
            relayout_action_grid(
                self._quick_grid,
                self._quick_buttons,
                container_width=content_w,
                max_columns=4,
            )
        if self._conflicts_panel:
            self._conflicts_panel.relayout_toolbar(content_w)

        compact = title_bar_compact(self.width())
        self._path_label.setVisible(not compact)
        if self._btn_browse:
            self._btn_browse.setText("Папка" if compact else "Сменить папку")
        if self._btn_reload:
            self._btn_reload.setText("↻" if compact else "Обновить")

    def _on_conflicts_commands_enqueued(self) -> None:
        self._pending_refresh_after_cmd = True
        self._refresh_modules_after_cmd = False
        self._show_log_tab()

    def _show_log_tab(self) -> None:
        self._tabs.setCurrentIndex(TAB_LOG)

    def _toggle_theme(self) -> None:
        self._theme_mgr.toggle()

    def _show_faq(self) -> None:
        show_faq(self)

    def _open_dictionary_search(self) -> None:
        dlg = DictionarySearchDialog(
            project_root=self._current_root(),
            theme=self._theme,
            on_saved=self._on_dictionary_search_saved,
            parent=self,
        )
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()

    def _on_dictionary_search_saved(self) -> None:
        if hasattr(self, "_dictionary_panel"):
            self._dictionary_panel.reload()

    def _on_theme_changed(self) -> None:
        self._theme = self._theme_mgr.current
        app = QApplication.instance()
        if isinstance(app, QApplication):
            self._theme_mgr.apply(app)
        self._btn_theme.setText(self._theme_mgr.toggle_button_icon())
        self._btn_theme.setToolTip(self._theme_mgr.toggle_button_tooltip())
        self._refresh_theme_styles()
        if self._tabs.currentIndex() == TAB_CONFLICTS and self._conflicts_panel:
            self._conflicts_panel.reload()

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
        if self._conflicts_panel:
            self._conflicts_panel.apply_theme(self._theme)
        if self._module_sidebar:
            self._module_sidebar.apply_theme(self._theme)
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
        if index == TAB_CONFLICTS and self._conflicts_panel:
            self._conflicts_panel.reload()
        if index == TAB_PENDING and hasattr(self, "_dictionary_panel"):
            self._dictionary_panel.reload()
            self._refresh_google_module_filter()

    def _refresh_google_module_filter(self) -> None:
        if not self._module_sidebar or not hasattr(self, "_dictionary_panel"):
            return
        self._module_sidebar.set_google_modules(self._dictionary_panel.google_module_names)

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

    def _stop_module_scan_workers(self) -> None:
        if self._stats_refresh_worker and self._stats_refresh_worker.isRunning():
            self._stats_refresh_worker.requestInterruption()
            self._stats_refresh_worker.wait(2000)
        self._stats_refresh_worker = None
        self._pending_stats_modules.clear()
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.requestInterruption()
            self._scan_worker.wait(2000)

    def _reload_modules(self) -> None:
        root = self._current_root()
        if root is None:
            QMessageBox.warning(self, "Папка проекта", "Укажите существующую папку с модулями.")
            return
        self._settings.setValue("last_root", str(root))
        selected_name = self._current_module_name()
        self._stop_module_scan_workers()
        modules = discover_modules(root)
        self._modules.clear()
        for mod in modules:
            info = ModuleInfo(path=mod, name=mod.name, display=display_module_name(mod.name))
            self._modules[mod.name] = info

        self._update_path_label()
        if self._translate_panel:
            self._translate_panel.update_scope_label()
        if self._module_sidebar:
            self._module_sidebar.set_modules(self._modules)
        self._update_project_summary()

        if selected_name and self._module_sidebar:
            self._module_sidebar.set_current_module(selected_name)

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
        self._update_project_summary()
        if self._current_module_name() == name:
            self._update_overview(info)

    def _on_scan_finished(self) -> None:
        if not self._runner.is_running:
            self._status_label.setText("Готово")
        self._update_path_label()
        if self._module_sidebar:
            self._module_sidebar.rebuild_list(preserve_selection=self._current_module_name())
        self._update_project_summary()
        self._refresh_module_selection_styles()

    def _update_project_summary(self) -> None:
        agg = aggregate_project_stats(self._modules)
        total = agg["total"]
        translated = agg["translated"]
        pct = int(round(100 * translated / total)) if total else 0
        self._project_progress.setValue(pct)
        drift_note = ""
        if agg.get("ready_drift_modules", 0) > 0:
            drift_note = (
                f" ({agg['ready_drift_modules']} с расхождениями values-ru↔словарь, "
                f"всего {agg['dict_mismatches']})"
            )
        self._project_summary.setText(
            f"<b>Проект:</b> {agg['modules']} модулей · "
            f"переведено {translated}/{total} ({pct}%) · "
            f"заглушек {agg['placeholders']} · конфликтов в словаре {agg['conflicts']} · "
            f"готовых модулей {agg['ready_modules']}{drift_note}"
        )

    def _update_list_item(self, name: str) -> None:
        if self._module_sidebar:
            self._module_sidebar.update_list_item(name)

    def _refresh_module_selection_styles(self) -> None:
        if self._module_sidebar:
            self._module_sidebar.refresh_selection_styles()

    def _current_module_name(self) -> str | None:
        if self._module_sidebar:
            return self._module_sidebar.current_module_name()
        return None

    def _current_module(self) -> ModuleInfo | None:
        name = self._current_module_name()
        if not name:
            return None
        return self._modules.get(name)

    def _open_placeholders_dialog(self, info: ModuleInfo) -> None:
        dlg = PlaceholdersDialog(
            info,
            theme=self._theme,
            on_saved=self._refresh_module_stats,
            find_next_module=self._find_next_module_with_placeholders,
            parent=self,
        )
        while True:
            result = dlg.exec()
            next_info = dlg.take_next_module()
            if next_info is None:
                break
            dlg = PlaceholdersDialog(
                next_info,
                theme=self._theme,
                on_saved=self._refresh_module_stats,
                find_next_module=self._find_next_module_with_placeholders,
                parent=self,
            )

    def _find_next_module_with_placeholders(
        self, after_name: str | None
    ) -> ModuleInfo | None:
        names = (
            self._module_sidebar.sorted_module_names()
            if self._module_sidebar
            else list(self._modules.keys())
        )
        start = 0
        if after_name and after_name in names:
            start = names.index(after_name) + 1
        for name in names[start:] + names[:start]:
            if after_name and name == after_name:
                continue
            info = self._modules.get(name)
            if not info:
                continue
            ph = int((info.stats or {}).get("placeholders", 0))
            if ph > 0:
                return info
        return None

    def _on_sidebar_module_selected(self, name: str) -> None:
        self._refresh_module_selection_styles()
        info = self._modules.get(name)
        if info:
            self._update_overview(info)
        if self._translate_panel:
            self._translate_panel.update_scope_label()
        if self._tabs.currentIndex() == TAB_CONFLICTS and self._conflicts_panel:
            self._conflicts_panel.reload()

    def _on_sidebar_module_double_clicked(self, name: str) -> None:
        info = self._modules.get(name)
        if info:
            self._open_placeholders_dialog(info)

    def _on_sidebar_context_menu(self, pos, item: QListWidgetItem) -> None:
        self._on_module_context_menu(pos, item)

    def _locale_values_dir(self, info: ModuleInfo) -> Path:
        en = info.path / "res" / "values-en"
        if en.is_dir():
            return en
        return info.path / "res" / "values"

    def _open_module_align_dialog(self, info: ModuleInfo) -> None:
        mismatches = collect_module_dict_mismatches(info.path)
        if not mismatches:
            QMessageBox.information(
                self,
                "Подстановка из словаря",
                "Расхождений нет: values-ru совпадает со словарём или в словаре нет перевода.",
            )
            return
        backup_module_values_ru(info.path)
        dlg = ModuleAlignDialog(
            info,
            mismatches,
            theme=self._theme,
            on_saved=self._refresh_module_stats,
            parent=self,
        )
        dlg.exec()

    def _fill_single_module(self, info: ModuleInfo) -> None:
        panel = self._translate_panel
        defaults = (
            FillModuleOptions.from_translate_panel(panel)
            if panel
            else FillModuleOptions()
        )
        dlg = FillModuleDialog(info, defaults=defaults, parent=self)
        if dlg.exec() != FillModuleDialog.DialogCode.Accepted:
            return
        opts = dlg.options()
        if not opts.no_overwrite:
            if not confirm_dangerous_action(
                self,
                title="Перевести модуль",
                summary=f"Запустить fill для «{info.display}» без «Не трогать готовые строки»?",
                details="Уже переведённые строки в values-ru могут быть перезаписаны из словаря.",
            ):
                return
        backup_module_values_ru(info.path)
        args = build_fill_module_args(info.path, opts)
        self._pending_refresh_after_cmd = True
        label = "fill"
        if opts.auto_collect:
            collect_args = self._build_collect_args(module_path=info.path)
            if not collect_args:
                return
            self._runner.enqueue(args, label)
            self._runner.enqueue(collect_args, "collect --track both")
        else:
            self._runner.run_single(args, label)
        self._show_log_tab()

    def _on_module_context_menu(self, pos, item: QListWidgetItem | None = None) -> None:
        if item is None:
            item = self._module_list.itemAt(pos)
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        info = self._modules.get(name) if name else None
        if not info:
            return
        self._module_list.setCurrentItem(item)
        menu = QMenu(self)
        act_placeholders = menu.addAction("Открыть заглушки")
        act_fill = menu.addAction("Перевести модуль…")
        act_align = menu.addAction("Подставить из словаря в APK…")
        menu.addSeparator()
        act_values = menu.addAction("Открыть values")
        act_values_ru = menu.addAction("Открыть values-ru")
        act_explorer = menu.addAction("Открыть в проводнике")
        chosen = menu.exec(self._module_list.mapToGlobal(pos))
        if chosen == act_placeholders:
            self._open_placeholders_dialog(info)
        elif chosen == act_fill:
            self._fill_single_module(info)
        elif chosen == act_align:
            self._open_module_align_dialog(info)
        elif chosen == act_values:
            self._open_path_in_explorer(self._locale_values_dir(info))
        elif chosen == act_values_ru:
            self._open_path_in_explorer(info.path / "res" / "values-ru")
        elif chosen == act_explorer:
            self._open_module_in_explorer(info)

    def _open_path_in_explorer(self, path: Path) -> None:
        resolved = path.resolve()
        if not resolved.is_dir():
            QMessageBox.warning(self, "Проводник", f"Папка не найдена:\n{resolved}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved))):
            QMessageBox.warning(self, "Проводник", f"Не удалось открыть:\n{resolved}")

    def _open_module_in_explorer(self, info: ModuleInfo) -> None:
        path = info.path.resolve()
        if not path.is_dir():
            QMessageBox.warning(
                self,
                "Проводник",
                f"Папка модуля не найдена:\n{path}",
            )
            return
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        if not opened:
            QMessageBox.warning(
                self,
                "Проводник",
                f"Не удалось открыть папку:\n{path}",
            )

    def _apply_module_stats(self, name: str, stats: dict) -> None:
        target = self._modules.get(name)
        if not target:
            return
        target.stats = stats
        self._update_list_item(name)
        if self._current_module_name() == name:
            self._update_overview(target)

    def _start_stats_refresh_worker(self, module_names: list[str]) -> None:
        paths: list[Path] = []
        for name in module_names:
            info = self._modules.get(name)
            if info:
                paths.append(info.path)
        if not paths:
            return

        worker = ModuleScanWorker(paths, self)
        self._stats_refresh_worker = worker
        pending = set(module_names)

        def on_scanned(name: str, stats: dict) -> None:
            if name in pending:
                pending.discard(name)
                self._apply_module_stats(name, stats)

        def on_finished() -> None:
            self._stats_refresh_worker = None
            worker.deleteLater()
            if self._pending_stats_modules:
                names = sorted(self._pending_stats_modules)
                self._pending_stats_modules.clear()
                self._start_stats_refresh_worker(names)

        worker.module_scanned.connect(on_scanned)
        worker.finished.connect(on_finished)
        worker.start()

    def _refresh_module_stats(self, info: ModuleInfo) -> None:
        if self._stats_refresh_worker and self._stats_refresh_worker.isRunning():
            self._pending_stats_modules.add(info.name)
            return
        self._start_stats_refresh_worker([info.name])

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
        finished_label = self._runner.current_label
        if exit_code == 0 and self._conflicts_panel:
            self._conflicts_panel.on_apply_step_finished(finished_label)

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
            reload_modules = self._refresh_modules_after_cmd
            self._refresh_modules_after_cmd = True
            apk_sources: set[str] = set()
            if self._conflicts_panel:
                apk_sources = set(self._conflicts_panel.conflict_apply_apk_sources)
                self._conflicts_panel.conflict_apply_apk_sources = set()
            if reload_modules:
                self._reload_modules()
            else:
                if self._conflicts_panel:
                    self._conflicts_panel.reload()
                    self._conflicts_panel.refresh_badges_from_cache()
                self._status_label.setText("Готово")
                if self._tabs.currentIndex() == TAB_LOG:
                    self._tabs.setCurrentIndex(TAB_CONFLICTS)
            if apk_sources:
                self._apply_sources_to_apk_modules(apk_sources)
            if hasattr(self, "_dictionary_panel"):
                self._dictionary_panel.reload()
                self._refresh_google_module_filter()

    def _on_status_text(self, text: str) -> None:
        self._status_label.setText(text)

    def _on_log_line(self, line: str, stream: str) -> None:
        self._log_view.append_line(line, stream)

    def _abort_command(self) -> None:
        if self._conflicts_panel:
            self._conflicts_panel.conflict_apply_pending.clear()
        self._runner.kill()

    def _refresh_current_module_stats(self) -> None:
        info = self._current_module()
        if info:
            self._refresh_module_stats(info)

    def _build_collect_args(
        self,
        *,
        add_missing_placeholders: bool = False,
        module_path: Path | None = None,
    ) -> list[str] | None:
        root = self._current_root()
        if root is None:
            QMessageBox.warning(self, "collect", "Укажите папку проекта.")
            return None
        collect_root = module_path if module_path is not None else root
        args = [
            str(LIBRARY_DIR / "collect_translation_library_ru.py"),
            "--root",
            str(collect_root),
            "--track",
            "both",
            "--resolutions-en",
            str(RESOLUTIONS_EN),
            "--resolutions-zh",
            str(RESOLUTIONS_ZH),
        ]
        if add_missing_placeholders:
            args.append("--add-missing-placeholders")
        return args

    def _collect_scope_label(self) -> tuple[str, Path | None]:
        """Подпись области и путь для collect (--root = модуль или вся папка)."""
        panel = self._translate_panel
        if panel and not panel.scope_is_all_modules():
            info = self._current_module()
            if not info:
                return "", None
            return f"модуля «{info.display}»", info.path
        n_mod = len(self._modules)
        return f"всех {n_mod} модулей", None

    def _run_fill(self) -> None:
        panel = self._translate_panel
        if not panel:
            return
        if panel.needs_overwrite_warning():
            if not confirm_dangerous_action(
                self,
                title="Перевести APK",
                summary="Запустить fill без «Не трогать готовые строки»?",
                details="Уже переведённые строки в APK могут быть перезаписаны из словаря.",
            ):
                return
        if panel.wants_dictionary_collect_chain():
            root = self._current_root()
            if root is None:
                QMessageBox.warning(self, "fill", "Укажите папку проекта.")
                return
            scope, module_path = self._collect_scope_label()
            if panel.scope_is_all_modules() is False and module_path is None:
                QMessageBox.warning(
                    self,
                    "Словарь",
                    "Выберите модуль слева или включите «Все в папке».",
                )
                return
            collect_note = (
                ""
                if module_path is None
                else "\n3. Collect по выбранному модулю; остальные модули в словарь не сканируются."
            )
            if not confirm_dangerous_action(
                self,
                title="Словарь из APK",
                summary=f"Заглушки + collect для {scope}?",
                details=(
                    "1. Дополнит словарь пропущенными строками (« ») и обновит values-ru.\n"
                    "2. Соберёт готовые пары из APK в общий словарь и отчёты конфликтов."
                    f"{collect_note}"
                ),
            ):
                return
        args = panel.build_fill_args(parent=self)
        if not args:
            return
        self._pending_refresh_after_cmd = True
        label = "fill"
        if panel.wants_dictionary_collect_chain():
            scope, module_path = self._collect_scope_label()
            if panel.scope_is_all_modules() is False and module_path is None:
                return
            collect_args = self._build_collect_args(module_path=module_path)
            if not collect_args:
                return
            self._runner.enqueue(args, label)
            self._runner.enqueue(collect_args, "collect --track both")
            self._show_log_tab()
            return
        if panel.wants_auto_collect():
            root = self._current_root()
            if root:
                collect_args = self._build_collect_args()
                if not collect_args:
                    return
                self._runner.enqueue(args, label)
                self._runner.enqueue(collect_args, "collect --track both")
                self._show_log_tab()
                return
        self._runner.run_single(args, label)
        self._show_log_tab()

    def _run_ensure_dictionary_only(self) -> None:
        panel = self._translate_panel
        if not panel:
            return
        scope, _ = self._collect_scope_label()
        if not panel.scope_is_all_modules() and self._current_module() is None:
            QMessageBox.warning(
                self,
                "Заглушки",
                "Выберите модуль слева или включите «Все в папке».",
            )
            return
        if not confirm_dangerous_action(
            self,
            title="Заглушки в словарь",
            summary=f"ensure-dictionary для {scope or 'выбранной области'}?",
            details=(
                "Добавит пропуски заглушкой « » в словарь en/zh и обновит values-ru в APK.\n"
                "Collect не запускается. Google не вызывается."
            ),
        ):
            return
        args = panel.build_ensure_dictionary_args(parent=self)
        if not args:
            return
        self._pending_refresh_after_cmd = True
        self._runner.run_single(args, "fill ensure-dictionary")
        self._show_log_tab()

    def _quick_placeholders(self) -> None:
        self._run_ensure_dictionary_only()

    def _quick_dict_placeholders_json(self) -> None:
        panel = self._translate_panel
        if self._current_root() is None:
            QMessageBox.warning(self, "Словарь", "Укажите папку проекта.")
            return
        scope, module_path = self._collect_scope_label()
        if panel and not panel.scope_is_all_modules() and module_path is None:
            QMessageBox.warning(
                self,
                "Словарь",
                "Выберите модуль слева или включите «Все в папке».",
            )
            return
        if not confirm_dangerous_action(
            self,
            title="Заглушки только в словарь",
            summary=f"Добавить пропуски в JSON для {scope}?",
            details=(
                "Запуск collect --add-missing-placeholders.\n"
                "Файлы values-ru в модулях не изменяются.\n"
                "Новые исходники из сканирования получат ru = « » в словаре en/zh."
            ),
        ):
            return
        args = self._build_collect_args(
            add_missing_placeholders=True,
            module_path=module_path,
        )
        if not args:
            return
        self._pending_refresh_after_cmd = True
        label = "collect placeholders"
        self._runner.run_single(args, label)
        self._show_log_tab()

    def _quick_sort(self) -> None:
        args = [str(SCRIPTS_DIR / "sort_translation_libraries.py")]
        self._runner.run_single(args, "sort")
        self._show_log_tab()

    def _quick_audit(self) -> None:
        args = [
            str(LIBRARY_DIR / "audit_translation_library.py"),
            "--min-severity",
            "medium",
        ]
        self._runner.run_single(args, "audit")
        self._show_log_tab()

    def _quick_fix_dates(self) -> None:
        args = [str(LIBRARY_DIR / "fix_library_date_formats.py")]
        self._runner.run_single(args, "fix date formats")
        self._show_log_tab()

    def _run_layout(self) -> None:
        panel = self._layout_panel
        if not panel:
            return
        args = panel.build_args(parent=self)
        if not args:
            return
        self._pending_refresh_after_cmd = True
        self._runner.run_single(args, panel.mode_label())
        self._show_log_tab()

    def _quick_layout_scan(self) -> None:
        panel = self._layout_panel
        if not panel:
            return
        panel.prepare_report()
        args = panel.build_args(parent=self, mode="report")
        if not args:
            return
        self._pending_refresh_after_cmd = True
        self._runner.run_single(args, "layout scan")
        self._show_log_tab()

    def _quick_layout_inject(self) -> None:
        panel = self._layout_panel
        if not panel:
            return
        panel.prepare_inject(dry_run=False)
        args = panel.build_args(parent=self, mode="inject")
        if not args:
            return
        self._pending_refresh_after_cmd = True
        self._runner.run_single(args, "layout inject")
        self._show_log_tab()

    def _quick_init_conflicts(self) -> None:
        cmds: list[tuple[list[str], str]] = []
        for track, conflicts_path, library_path, resolutions_path in TRACKS:
            if not conflicts_path.is_file():
                continue
            args = [
                str(LIBRARY_DIR / "apply_translation_conflict_resolutions_ru.py"),
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
        self._show_log_tab()

    def _module_names_for_sources(self, sources: set[str]) -> set[str]:
        names: set[str] = set()
        if not sources:
            return names
        cache = load_conflicts_cache()
        for items in cache.values():
            for item in items:
                src = str(item.get("source") or "")
                if src in sources:
                    names |= modules_in_conflict(item)
        return names

    def _apply_sources_to_apk_modules(self, sources: set[str]) -> None:
        if not sources:
            return
        module_names = self._module_names_for_sources(sources)
        if not module_names:
            QMessageBox.information(
                self,
                "APK",
                "Не найдены модули для выбранных исходников.",
            )
            return
        paths: list[Path] = []
        for name in sorted(module_names):
            info = self._modules.get(name)
            if info:
                paths.append(info.path)
        if not paths:
            return
        if not confirm_dangerous_action(
            self,
            title="Записать в APK",
            summary=f"Применить {len(sources)} переводов к {len(paths)} модулям?",
            details="Будет создан бэкап values-ru. Меняются только строки с выбранными исходниками.",
        ):
            return
        backup_modules_values_ru(paths)
        total = 0
        from gui_pkg.placeholder_editor import collect_all_module_rows

        for name in sorted(module_names):
            info = self._modules.get(name)
            if not info:
                continue
            updates = updates_for_sources(info.path, sources)
            if not updates:
                continue
            rows = collect_all_module_rows(info.path)
            _, _, applied = apply_placeholder_translations(info.path, rows, updates)
            total += len(applied)
            self._refresh_module_stats(info)
        QMessageBox.information(
            self,
            "APK",
            f"Записано в APK: {total} строк в {len(paths)} модулях.",
        )

    def _on_pending_merge_requested(self) -> None:
        self._pending_refresh_after_cmd = True
        self._show_log_tab()
