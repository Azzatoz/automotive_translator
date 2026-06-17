"""Панель перевода APK / пополнения словаря на вкладке «Обзор»."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.config import SCRIPTS_DIR
from gui_pkg.scanner import ModuleInfo


class TranslatePanel(QGroupBox):
    """Быстрые действия — перевод APK и словарь."""

    def __init__(
        self,
        *,
        get_root: Callable[[], Path | None],
        get_current_module: Callable[[], ModuleInfo | None],
        get_module_count: Callable[[], int],
        on_collect: Callable[[], None],
        on_run_fill: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Быстрые действия — перевод", parent)
        self._get_root = get_root
        self._get_current_module = get_current_module
        self._get_module_count = get_module_count
        self._on_collect = on_collect
        self._on_run_fill = on_run_fill

        root = QVBoxLayout(self)
        root.setSpacing(10)

        task_row = QHBoxLayout()
        task_row.addWidget(QLabel("Задача:"))
        self._task_group = QButtonGroup(self)
        self._rb_task_apk = QRadioButton("Перевести приложение (values-ru в APK)")
        self._rb_task_dict = QRadioButton("Пополнить общий словарь")
        self._rb_task_apk.setChecked(True)
        self._task_group.addButton(self._rb_task_apk, 0)
        self._task_group.addButton(self._rb_task_dict, 1)
        task_row.addWidget(self._rb_task_apk)
        task_row.addWidget(self._rb_task_dict)
        task_row.addStretch()
        root.addLayout(task_row)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Модули:"))
        self._scope_group = QButtonGroup(self)
        self._rb_scope_all = QRadioButton("Все в папке")
        self._rb_scope_one = QRadioButton("Только выбранный")
        self._rb_scope_all.setChecked(True)
        self._scope_group.addButton(self._rb_scope_all, 0)
        self._scope_group.addButton(self._rb_scope_one, 1)
        scope_row.addWidget(self._rb_scope_all)
        scope_row.addWidget(self._rb_scope_one)
        scope_row.addStretch()
        root.addLayout(scope_row)

        self._scope_label = QLabel()
        self._scope_label.setObjectName("hintLabel")
        self._scope_label.setWordWrap(True)
        root.addWidget(self._scope_label)
        self._scope_group.buttonClicked.connect(lambda: self.update_scope_label())

        self._apk_options = QWidget()
        apk_layout = QVBoxLayout(self._apk_options)
        apk_layout.setContentsMargins(0, 0, 0, 0)
        apk_layout.setSpacing(8)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Режим:"))
        self._mode_group = QButtonGroup(self)
        self._rb_normal = QRadioButton("Словарь + Google")
        self._rb_library_only = QRadioButton("Только словарь")
        self._rb_ensure_dict = QRadioButton("Заглушки в словарь")
        self._rb_normal.setChecked(True)
        for i, rb in enumerate((self._rb_normal, self._rb_library_only, self._rb_ensure_dict)):
            self._mode_group.addButton(rb, i)
            mode_row.addWidget(rb)
        mode_row.addStretch()
        apk_layout.addLayout(mode_row)
        self._rb_ensure_dict.setVisible(False)

        opts_row = QHBoxLayout()
        self._chk_no_overwrite = QCheckBox("Не трогать готовые строки")
        self._chk_no_overwrite.setChecked(True)
        self._chk_no_overwrite.setToolTip(
            "Уже переведённые строки в values-ru не перезаписывать."
        )
        self._chk_dry_run = QCheckBox("Пробный запуск")
        self._chk_strings_only = QCheckBox("Только strings.xml")
        self._chk_auto_collect = QCheckBox("После — собрать словарь из APK")
        self._chk_auto_collect.setChecked(False)
        self._chk_auto_collect.setToolTip(
            "Пересобрать общий словарь и отчёт конфликтов. "
            "Для уже переведённого проекта обычно не нужно."
        )
        for chk in (
            self._chk_no_overwrite,
            self._chk_dry_run,
            self._chk_strings_only,
            self._chk_auto_collect,
        ):
            opts_row.addWidget(chk)
        opts_row.addStretch()
        apk_layout.addLayout(opts_row)

        self._fill_mode_hint = QLabel()
        self._fill_mode_hint.setObjectName("hintLabel")
        self._fill_mode_hint.setWordWrap(True)
        apk_layout.addWidget(self._fill_mode_hint)
        self._mode_group.buttonClicked.connect(self._on_fill_mode_changed)
        root.addWidget(self._apk_options)

        self._dict_options = QWidget()
        dict_layout = QVBoxLayout(self._dict_options)
        dict_layout.setContentsMargins(0, 0, 0, 0)
        dict_hint = QLabel(
            "Добавляет в общий словарь пропущенные строки заглушкой « » и обновляет values-ru. "
            "Не путать с переводом APK: Google не вызывается. "
            "«Собрать из APK» — отдельная кнопка ниже; может показать конфликты между модулями."
        )
        dict_hint.setObjectName("hintLabel")
        dict_hint.setWordWrap(True)
        dict_layout.addWidget(dict_hint)
        dict_btn_row = QHBoxLayout()
        btn_dict_collect = QPushButton("Собрать словарь из APK")
        btn_dict_collect.clicked.connect(self._on_collect)
        dict_btn_row.addWidget(btn_dict_collect)
        dict_btn_row.addStretch()
        dict_layout.addLayout(dict_btn_row)
        self._dict_options.setVisible(False)
        root.addWidget(self._dict_options)

        self.run_fill_button = QPushButton("Перевести APK")
        self.run_fill_button.setObjectName("primaryBtn")
        self.run_fill_button.clicked.connect(self._on_run_fill)
        root.addWidget(self.run_fill_button)

        self._task_group.buttonClicked.connect(self._on_task_changed)
        self._on_task_changed()
        self._on_fill_mode_changed()
        self.update_scope_label()

    def scope_is_all_modules(self) -> bool:
        return self._rb_scope_all.isChecked()

    def is_apk_task(self) -> bool:
        return self._rb_task_apk.isChecked()

    def wants_auto_collect(self) -> bool:
        return self._chk_auto_collect.isChecked() and not self._chk_dry_run.isChecked()

    def needs_overwrite_warning(self) -> bool:
        return self.is_apk_task() and not self._chk_no_overwrite.isChecked()

    def prepare_dictionary_task(self) -> None:
        self._rb_task_dict.setChecked(True)
        self._on_task_changed()

    def set_scope_single_module(self) -> bool:
        """Временно «только выбранный». Возвращает был ли режим «все»."""
        was_all = self.scope_is_all_modules()
        self._rb_scope_one.setChecked(True)
        self.update_scope_label()
        return was_all

    def restore_scope_all(self) -> None:
        self._rb_scope_all.setChecked(True)
        self.update_scope_label()

    def update_scope_label(self) -> None:
        root = self._get_root()
        info = self._get_current_module()
        if self.scope_is_all_modules():
            if root:
                n = self._get_module_count()
                self._scope_label.setText(f"Обработка: все модули ({n})")
            else:
                self._scope_label.setText("Укажите папку проекта вверху окна.")
        elif info:
            self._scope_label.setText(f"Обработка: {info.display}")
        else:
            self._scope_label.setText(
                "Выберите модуль слева или переключитесь на «Все в папке»."
            )

    def build_fill_args(self, *, parent: QWidget) -> list[str] | None:
        root = self._get_root()
        if root is None:
            QMessageBox.warning(parent, "fill", "Укажите папку проекта.")
            return None

        args = [str(SCRIPTS_DIR / "fill_values_ru_from_library.py")]
        if not self.is_apk_task():
            args.append("--ensure-dictionary")
        else:
            mode_id = self._mode_group.checkedId()
            if mode_id == 1:
                args.append("--library-only")
            elif mode_id == 2:
                args.append("--ensure-dictionary")

        if self.scope_is_all_modules():
            args.extend(["--root", str(root)])
        else:
            info = self._get_current_module()
            if not info:
                QMessageBox.warning(
                    parent,
                    "Перевод",
                    "Выберите модуль слева или включите «Все модули в папке проекта».",
                )
                return None
            args.extend(["-m", str(info.path)])

        if self._chk_no_overwrite.isChecked():
            args.append("--no-overwrite")
        if self._chk_dry_run.isChecked():
            args.append("--dry-run")
        if self._chk_strings_only.isChecked():
            args.append("--strings-only")
        return args

    def _on_task_changed(self) -> None:
        apk = self.is_apk_task()
        self._apk_options.setVisible(apk)
        self._dict_options.setVisible(not apk)
        for chk in (
            self._chk_no_overwrite,
            self._chk_dry_run,
            self._chk_strings_only,
            self._chk_auto_collect,
        ):
            chk.setVisible(apk)
        self.setTitle(
            "Быстрые действия — перевод APK" if apk else "Быстрые действия — словарь"
        )
        self.run_fill_button.setText(
            "Перевести APK" if apk else "Дополнить словарь заглушками"
        )
        if apk and self._mode_group.checkedId() == 2:
            self._rb_normal.setChecked(True)
        self._on_fill_mode_changed()

    def _on_fill_mode_changed(self) -> None:
        if not self.is_apk_task():
            self._fill_mode_hint.setText("")
            return
        mode_id = self._mode_group.checkedId()
        hints = {
            0: (
                "Словарь en+zh, затем Google: сначала проход en→ru, потом zh→ru "
                "(нужен интернет). Переключатель языка не нужен."
            ),
            1: (
                "Подставляет в APK всё из словарей en и zh. "
                "Google не вызывается — для доводки уже переведённого проекта."
            ),
        }
        self._fill_mode_hint.setText(hints.get(mode_id, ""))
