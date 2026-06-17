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
        on_run_fill: Callable[[], None],
        on_dict_placeholders_json: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Быстрые действия — перевод", parent)
        self._get_root = get_root
        self._get_current_module = get_current_module
        self._get_module_count = get_module_count
        self._on_run_fill = on_run_fill
        self._on_dict_placeholders_json = on_dict_placeholders_json

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

        self._mode_group = QButtonGroup(self)
        self._rb_normal = QRadioButton("Словарь + Google")
        self._rb_library_only = QRadioButton("Только словарь")
        self._rb_library_placeholders = QRadioButton("Словарь + создать заглушки")
        self._rb_normal.setChecked(True)
        for i, rb in enumerate(
            (self._rb_normal, self._rb_library_only, self._rb_library_placeholders)
        ):
            self._mode_group.addButton(rb, i)
        mode_col = QVBoxLayout()
        mode_row1 = QHBoxLayout()
        mode_row1.addWidget(self._rb_normal)
        mode_row1.addWidget(self._rb_library_only)
        mode_row1.addStretch()
        mode_row2 = QHBoxLayout()
        mode_row2.addWidget(self._rb_library_placeholders)
        mode_row2.addStretch()
        mode_col.addLayout(mode_row1)
        mode_col.addLayout(mode_row2)
        mode_outer = QHBoxLayout()
        mode_outer.addWidget(QLabel("Режим:"))
        mode_outer.addLayout(mode_col, stretch=1)
        apk_layout.addLayout(mode_outer)

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
            "Кнопка ниже: ensure-dictionary в APK и словарь, затем collect. "
            "Только заглушки в APK — «Заглушки в словарь» внизу. "
            "Только JSON без APK — «Заглушки только JSON» (учитывает «Все» / «Выбранный» слева)."
        )
        dict_hint.setObjectName("hintLabel")
        dict_hint.setWordWrap(True)
        dict_layout.addWidget(dict_hint)
        if self._on_dict_placeholders_json is not None:
            btn_json = QPushButton("Заглушки только в JSON (без APK)")
            btn_json.setToolTip(
                "collect --add-missing-placeholders — область по переключателю «Модули» выше"
            )
            btn_json.clicked.connect(self._on_dict_placeholders_json)
            dict_layout.addWidget(btn_json)
            self.dict_placeholders_json_button = btn_json
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

    def wants_dictionary_collect_chain(self) -> bool:
        """Режим «Пополнить словарь»: ensure-dictionary, затем collect."""
        return not self.is_apk_task()

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

    def build_ensure_dictionary_args(self, *, parent: QWidget) -> list[str] | None:
        """fill --ensure-dictionary: заглушки в словарь и values-ru (без collect)."""
        root = self._get_root()
        if root is None:
            QMessageBox.warning(parent, "fill", "Укажите папку проекта.")
            return None

        args = [str(SCRIPTS_DIR / "fill_values_ru_from_library.py"), "--ensure-dictionary"]

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
            "Перевести APK" if apk else "Собрать словарь из APK"
        )
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
                "Подставляет в APK только то, что уже есть в словарях en и zh. "
                "Пропуски без перевода — ошибка. Google не вызывается."
            ),
            2: (
                "Словарь en+zh в APK; для пропусков — заглушка « » в словарь и values-ru. "
                "Google не вызывается."
            ),
        }
        self._fill_mode_hint.setText(hints.get(mode_id, ""))
