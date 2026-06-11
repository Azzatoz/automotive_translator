from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSettings, QSize, Qt
from PyQt6.QtGui import QResizeEvent, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
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

from gui_pkg.config import (
    LAYOUT_DIR,
    LIBRARY_DIR,
    REPO_ROOT,
    ROOT_PRESETS,
    SCRIPTS_DIR,
    SETTINGS_APP,
    SETTINGS_ORG,
    TRACKS,
)
from gui_pkg.process import ProcessController
from gui_pkg.scanner import (
    ModuleInfo,
    badge_text,
    count_conflicts_for_module,
    discover_modules,
    display_module_name,
    load_conflicts_cache,
    modules_in_conflict,
    prune_conflicts_file,
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
from gui_pkg.widgets import ActionButton, ConflictEntryWidget, LogView, ModuleListRow, StatCard
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
        self._conflicts_toolbar_grid: QGridLayout | None = None
        self._conflicts_toolbar_buttons: list[ActionButton] = []
        self._btn_browse: QPushButton | None = None
        self._btn_reload: QPushButton | None = None
        self._modules: dict[str, ModuleInfo] = {}
        self._module_rows: dict[str, tuple[QListWidgetItem, ModuleListRow]] = {}
        self._scan_worker: ModuleScanWorker | None = None
        self._stats_refresh_worker: ModuleScanWorker | None = None
        self._conflict_widgets: list[ConflictEntryWidget] = []
        self._pending_refresh_after_cmd = False
        self._refresh_modules_after_cmd = True
        self._conflict_apply_pending: dict[str, set[str]] = {}
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
        self._content_panel = content
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
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

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

        quick_label = QLabel("БЫСТРЫЕ ДЕЙСТВИЯ")
        quick_label.setObjectName("sectionLabel")
        layout.addWidget(quick_label)
        quick = QGroupBox()
        self._quick_grid = QGridLayout(quick)
        self._quick_grid.setSpacing(8)
        actions: list[tuple[str, str, object, bool]] = [
            ("Дополнить словарь", "Доп.\nсловарь", self._quick_ensure_dictionary, True),
            ("Собрать из APK", "Collect\nAPK", self._quick_collect, False),
            ("Сортировать", "Сортир.", self._quick_sort, False),
            ("Проверка словаря", "Аудит", self._quick_audit, False),
            ("Формат дат", "Даты", self._quick_fix_dates, False),
            ("Шаблон конфликтов", "Шаблон\nконфл.", self._quick_init_conflicts, False),
            ("Поиск хардкода", "Скан\nlayout", self._quick_layout_scan, False),
            ("Хардкод → strings", "В\nstrings", self._quick_layout_inject, False),
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
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        intro = QLabel(
            "<b>Две отдельные операции</b><br>"
            "① <b>Перевод values-ru</b> — заполняет русские строки в XML модуля.<br>"
            "② <b>Хардкод в layout</b> — находит текст в layout-файлах и выносит в strings.xml. "
            "После шага ② обычно нужен шаг ① в режиме «Только из словаря»."
        )
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(intro)

        scope_group = QGroupBox("Область — какие модули")
        scope_layout = QVBoxLayout(scope_group)
        self._scope_group = QButtonGroup(self)
        self._rb_scope_all = QRadioButton("Все модули в папке проекта")
        self._rb_scope_one = QRadioButton("Только выбранный модуль слева")
        self._rb_scope_all.setChecked(True)
        self._scope_group.addButton(self._rb_scope_all, 0)
        self._scope_group.addButton(self._rb_scope_one, 1)
        scope_layout.addWidget(self._rb_scope_all)
        scope_layout.addWidget(self._rb_scope_one)
        self._actions_scope_label = QLabel()
        self._actions_scope_label.setObjectName("hintLabel")
        self._actions_scope_label.setWordWrap(True)
        scope_layout.addWidget(self._actions_scope_label)
        self._scope_group.buttonClicked.connect(lambda: self._update_actions_scope_label())
        layout.addWidget(scope_group)

        fill_group = QGroupBox("① Перевод values-ru")
        fill_layout = QVBoxLayout(fill_group)
        fill_layout.setSpacing(10)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Язык оригинала в APK:"))
        self._lang_group = QButtonGroup(self)
        self._rb_zh = QRadioButton("Китайский")
        self._rb_en = QRadioButton("Английский")
        self._rb_zh.setChecked(True)
        self._lang_group.addButton(self._rb_zh, 0)
        self._lang_group.addButton(self._rb_en, 1)
        lang_row.addWidget(self._rb_zh)
        lang_row.addWidget(self._rb_en)
        lang_row.addStretch()
        fill_layout.addLayout(lang_row)

        mode_label = QLabel("Режим перевода")
        mode_label.setObjectName("sectionLabel")
        fill_layout.addWidget(mode_label)
        self._mode_group = QButtonGroup(self)
        self._rb_normal = QRadioButton("Словарь + Google для пропусков")
        self._rb_library_only = QRadioButton("Только из словаря")
        self._rb_ensure_dict = QRadioButton("Дополнить словарь (заглушки)")
        self._rb_normal.setChecked(True)
        for i, rb in enumerate((self._rb_normal, self._rb_library_only, self._rb_ensure_dict)):
            self._mode_group.addButton(rb, i)
            fill_layout.addWidget(rb)
        self._fill_mode_hint = QLabel()
        self._fill_mode_hint.setObjectName("hintLabel")
        self._fill_mode_hint.setWordWrap(True)
        fill_layout.addWidget(self._fill_mode_hint)
        self._mode_group.buttonClicked.connect(self._on_fill_mode_changed)

        self._chk_dry_run = QCheckBox("Пробный запуск — ничего не записывать")
        self._chk_strings_only = QCheckBox("Только strings.xml")
        self._chk_no_overwrite = QCheckBox("Не трогать уже переведённые строки")
        self._chk_auto_collect = QCheckBox("После перевода — обновить общий словарь из APK")
        self._chk_auto_collect.setChecked(True)
        for chk in (
            self._chk_dry_run,
            self._chk_strings_only,
            self._chk_no_overwrite,
            self._chk_auto_collect,
        ):
            fill_layout.addWidget(chk)

        self._btn_run_fill = QPushButton("Начать перевод values-ru")
        self._btn_run_fill.setObjectName("primaryBtn")
        self._btn_run_fill.clicked.connect(self._run_fill)
        fill_layout.addWidget(self._btn_run_fill)
        self._action_buttons.append(self._btn_run_fill)
        layout.addWidget(fill_group)

        layout_group = QGroupBox("② Хардкод в layout-файлах")
        layout_form = QVBoxLayout(layout_group)
        layout_intro = QLabel(
            "Ищет китайский/английский текст в res/layout. "
            "Рекомендуемый путь: вынести в strings.xml → затем «Только из словаря» выше."
        )
        layout_intro.setObjectName("hintLabel")
        layout_intro.setWordWrap(True)
        layout_form.addWidget(layout_intro)

        self._layout_mode_group = QButtonGroup(self)
        self._rb_layout_report = QRadioButton("Найти и показать отчёт")
        self._rb_layout_inject = QRadioButton("Вынести в strings.xml")
        self._rb_layout_inplace = QRadioButton("Перевести прямо в layout (быстро, не рекомендуется)")
        self._rb_layout_inject.setChecked(True)
        for i, rb in enumerate(
            (self._rb_layout_report, self._rb_layout_inject, self._rb_layout_inplace)
        ):
            self._layout_mode_group.addButton(rb, i)
            layout_form.addWidget(rb)
        self._chk_layout_dry_run = QCheckBox("Пробный запуск — ничего не записывать")
        layout_form.addWidget(self._chk_layout_dry_run)
        prefix_row = QHBoxLayout()
        prefix_row.addWidget(QLabel("Префикс новых ключей:"))
        self._layout_key_prefix = QLineEdit("hw")
        self._layout_key_prefix.setMaximumWidth(120)
        prefix_row.addWidget(self._layout_key_prefix)
        prefix_row.addStretch()
        layout_form.addLayout(prefix_row)
        self._btn_run_layout = QPushButton("Обработать layout")
        self._btn_run_layout.clicked.connect(self._run_layout)
        layout_form.addWidget(self._btn_run_layout)
        self._action_buttons.append(self._btn_run_layout)
        layout.addWidget(layout_group)

        self._on_fill_mode_changed()
        self._update_actions_scope_label()
        layout.addStretch()
        scroll.setWidget(w)
        return scroll

    def _scope_is_all_modules(self) -> bool:
        return self._rb_scope_all.isChecked()

    def _update_actions_scope_label(self) -> None:
        root = self._current_root()
        info = self._current_module()
        if self._scope_is_all_modules():
            if root:
                n = len(self._modules)
                self._actions_scope_label.setText(
                    f"Будут обработаны все модули в папке ({n} шт.): {root}"
                )
            else:
                self._actions_scope_label.setText("Укажите папку проекта вверху окна.")
            self._rb_scope_one.setEnabled(True)
        else:
            if info:
                self._actions_scope_label.setText(
                    f"Будет обработан модуль: {info.display}"
                )
            else:
                self._actions_scope_label.setText(
                    "Выберите модуль в списке слева или переключитесь на «Все модули»."
                )
            self._rb_scope_one.setEnabled(True)

    def _on_fill_mode_changed(self) -> None:
        mode_id = self._mode_group.checkedId()
        hints = {
            0: (
                "Сначала подставляет перевод из словаря. Что не найдено — "
                "переводит через Google (нужен интернет)."
            ),
            1: (
                "Берёт только готовые переводы из словаря. "
                "Неизвестные строки не трогает и Google не вызывает."
            ),
            2: (
                "Добавляет в словарь пропущенные строки заглушкой и обновляет values-ru. "
                "Google не вызывается. Обычно делают перед массовым переводом."
            ),
        }
        self._fill_mode_hint.setText(hints.get(mode_id, ""))
        is_ensure = mode_id == 2
        is_library = mode_id == 1
        self._chk_no_overwrite.setVisible(is_ensure)
        self._chk_auto_collect.setVisible(not is_ensure)
        if is_library:
            self._chk_auto_collect.setChecked(True)

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

        self._chk_filter_module_conflicts = QCheckBox("Показывать только конфликты выбранного модуля")
        self._chk_filter_module_conflicts.setChecked(True)
        self._chk_filter_module_conflicts.stateChanged.connect(self._reload_conflicts_ui)
        layout.addWidget(self._chk_filter_module_conflicts)

        toolbar_box = QGroupBox()
        self._conflicts_toolbar_grid = QGridLayout(toolbar_box)
        self._conflicts_toolbar_grid.setSpacing(8)
        conflict_actions: list[tuple[str, str, object, bool]] = [
            ("Обновить список", "Обновить", self._reload_conflicts_ui, False),
            (
                "Подставить популярный вариант",
                "Большинство",
                self._quick_init_conflicts,
                False,
            ),
            ("Выделить все", "Все", self._highlight_all_conflicts, False),
            ("Снять выделение", "Снять", self._clear_conflict_highlights, False),
            (
                "Сохранить выделенные",
                "Выделен.",
                lambda: self._apply_conflicts(only_highlighted=True),
                True,
            ),
            (
                "Сохранить все на экране",
                "Все на экране",
                lambda: self._apply_conflicts(only_highlighted=False),
                False,
            ),
        ]
        self._conflicts_toolbar_buttons = []
        for full_label, short_label, handler, primary in conflict_actions:
            btn = ActionButton(full_label, short_label, primary=primary)
            btn.clicked.connect(handler)  # type: ignore[arg-type]
            self._conflicts_toolbar_buttons.append(btn)
        btn_init = self._conflicts_toolbar_buttons[1]
        btn_init.setToolTip(
            "Для каждого конфликта выбрать перевод, который встречается в большинстве модулей"
        )
        self._btn_apply_marked_conflicts = self._conflicts_toolbar_buttons[4]
        self._btn_apply_marked_conflicts.setToolTip("Записать в словарь только блоки с синей рамкой")
        self._btn_apply_conflicts = self._conflicts_toolbar_buttons[5]
        self._btn_apply_conflicts.setToolTip(
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

        self._action_buttons.extend(self._conflicts_toolbar_buttons[1:])
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
        if self._conflicts_toolbar_grid and self._conflicts_toolbar_buttons:
            relayout_action_grid(
                self._conflicts_toolbar_grid,
                self._conflicts_toolbar_buttons,
                container_width=content_w,
                max_columns=3,
            )

        compact = title_bar_compact(self.width())
        self._path_label.setVisible(not compact)
        if self._btn_browse:
            self._btn_browse.setText("Папка" if compact else "Сменить папку")
        if self._btn_reload:
            self._btn_reload.setText("↻" if compact else "Обновить")

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
            item.setSizeHint(QSize(0, 48))
            row = ModuleListRow(info.display, "…", "unprocessed", theme=self._theme)
            self._module_list.addItem(item)
            self._module_list.setItemWidget(item, row)
            self._module_rows[mod.name] = (item, row)

        self._update_path_label()
        self._update_actions_scope_label()

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
        self._update_actions_scope_label()
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
        finished_label = self._runner.current_label
        if exit_code == 0:
            self._on_apply_conflicts_step_finished(finished_label)

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
            if reload_modules:
                self._refresh_current_module_stats()
                self._reload_modules()
            else:
                self._reload_conflicts_ui()
                self._refresh_conflict_badges_from_cache()
                self._status_label.setText("Готово")
                if self._tabs.currentIndex() == 3:
                    self._tabs.setCurrentIndex(2)

    def _on_apply_conflicts_step_finished(self, label: str) -> None:
        prefix = "apply conflicts ("
        if not label.startswith(prefix) or not label.endswith(")"):
            return
        track = label[len(prefix) : -1]
        sources = self._conflict_apply_pending.pop(track, None)
        if not sources:
            return
        for track_name, conflicts_path, _, _ in TRACKS:
            if track_name != track:
                continue
            removed = prune_conflicts_file(conflicts_path, sources)
            if removed:
                self._log_view.append_line(
                    f"[gui] из отчёта убрано конфликтов ({track_name}): {removed}",
                    "stdout",
                )
            break
        self._reload_conflicts_ui()
        self._refresh_conflict_badges_from_cache()

    def _refresh_conflict_badges_from_cache(self) -> None:
        cache = load_conflicts_cache()
        for name, info in self._modules.items():
            if not info.stats:
                info.stats = {}
            n = count_conflicts_for_module(name, cache)
            info.stats["conflicts"] = n
            if n > 0:
                info.stats["status"] = "conflicts"
            elif info.stats.get("status") == "conflicts":
                if info.stats.get("placeholders", 0) > 0:
                    info.stats["status"] = "placeholders"
                elif info.stats.get("total", 0) > 0:
                    info.stats["status"] = "ready"
                else:
                    info.stats["status"] = "unprocessed"
            self._update_list_item(name)
        current = self._current_module()
        if current:
            self._update_overview(current)

    def _on_status_text(self, text: str) -> None:
        self._status_label.setText(text)

    def _on_log_line(self, line: str, stream: str) -> None:
        self._log_view.append_line(line, stream)

    def _abort_command(self) -> None:
        self._conflict_apply_pending.clear()
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

        args = [str(SCRIPTS_DIR / "fill_values_ru_from_library.py")]
        mode_id = self._mode_group.checkedId()
        if mode_id == 1:
            args.append("--library-only")
        elif mode_id == 2:
            args.append("--ensure-dictionary")

        if self._scope_is_all_modules():
            args.extend(["--root", str(root)])
        else:
            info = self._current_module()
            if not info:
                QMessageBox.warning(
                    self,
                    "Перевод",
                    "Выберите модуль слева или включите «Все модули в папке проекта».",
                )
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
                    str(LIBRARY_DIR / "collect_translation_library_ru.py"),
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
            str(LIBRARY_DIR / "collect_translation_library_ru.py"),
            "--root",
            str(root),
            "--track",
            "both",
        ]
        self._pending_refresh_after_cmd = True
        self._runner.run_single(args, "collect")
        self._tabs.setCurrentIndex(3)

    def _quick_sort(self) -> None:
        args = [str(SCRIPTS_DIR / "sort_translation_libraries.py")]
        self._runner.run_single(args, "sort")
        self._tabs.setCurrentIndex(3)

    def _quick_audit(self) -> None:
        args = [
            str(LIBRARY_DIR / "audit_translation_library.py"),
            "--min-severity",
            "medium",
        ]
        self._runner.run_single(args, "audit")
        self._tabs.setCurrentIndex(3)

    def _quick_fix_dates(self) -> None:
        args = [str(LIBRARY_DIR / "fix_library_date_formats.py")]
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

        args = [str(LAYOUT_DIR / "extract_layout_hardcode.py")]
        if mode == "inject":
            args.append("--inject-values")
        elif mode == "inplace":
            args.append("--translate-inplace")

        if self._scope_is_all_modules():
            args.extend(["--root", str(root)])
        else:
            info = self._current_module()
            if not info:
                QMessageBox.warning(
                    self,
                    "Layout",
                    "Выберите модуль слева или включите «Все модули в папке проекта».",
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
            self._btn_apply_conflicts.update_labels("Сохранить все на экране", "Все на экране")
            self._btn_apply_marked_conflicts.update_labels("Сохранить выделенные", "Выделен.")
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
        self._btn_apply_marked_conflicts.update_labels(
            f"Сохранить выделенные ({marked_ready})",
            f"Выделен.\n({marked_ready})",
        )
        self._btn_apply_conflicts.update_labels(
            f"Сохранить все на экране ({ready})",
            f"Все\n({ready})",
        )

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

        self._pending_refresh_after_cmd = True
        self._refresh_modules_after_cmd = False
        self._conflict_apply_pending = {
            track: set(entries.keys()) for track, entries in by_track.items() if entries
        }
        for args, label in cmds:
            self._runner.enqueue(args, label)
        self._tabs.setCurrentIndex(3)
