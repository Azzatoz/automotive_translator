"""Диалог настроек fill для одного модуля."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.config import SCRIPTS_DIR
from gui_pkg.scanner import ModuleInfo

FillMode = Literal["normal", "library_only", "library_placeholders"]


@dataclass
class FillModuleOptions:
    mode: FillMode = "normal"
    no_overwrite: bool = True
    dry_run: bool = False
    strings_only: bool = False
    auto_collect: bool = False

    @classmethod
    def from_translate_panel(cls, panel: QWidget) -> FillModuleOptions:
        from gui_pkg.translate_panel import TranslatePanel

        if not isinstance(panel, TranslatePanel):
            return cls()
        mode_map = {0: "normal", 1: "library_only", 2: "library_placeholders"}
        mode = mode_map.get(panel._mode_group.checkedId(), "normal")
        return cls(
            mode=mode,
            no_overwrite=panel._chk_no_overwrite.isChecked(),
            dry_run=panel._chk_dry_run.isChecked(),
            strings_only=panel._chk_strings_only.isChecked(),
            auto_collect=panel._chk_auto_collect.isChecked(),
        )


def build_fill_module_args(module_path: Path, opts: FillModuleOptions) -> list[str]:
    args = [str(SCRIPTS_DIR / "fill_values_ru_from_library.py")]
    if opts.mode == "library_only":
        args.append("--library-only")
    elif opts.mode == "library_placeholders":
        args.append("--ensure-dictionary")
    args.extend(["-m", str(module_path)])
    if opts.no_overwrite:
        args.append("--no-overwrite")
    if opts.dry_run:
        args.append("--dry-run")
    if opts.strings_only:
        args.append("--strings-only")
    return args


class FillModuleDialog(QDialog):
    def __init__(
        self,
        module: ModuleInfo,
        *,
        defaults: FillModuleOptions | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._defaults = defaults or FillModuleOptions()
        self._module = module

        self.setWindowTitle("Перевести модуль")
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        title = QLabel(f"<b>{module.display}</b>")
        title.setWordWrap(True)
        root.addWidget(title)

        hint = QLabel(
            "Запуск <code>fill_values_ru_from_library.py</code> только для выбранного модуля."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        mode_group_box = QGroupBox("Режим")
        mode_layout = QVBoxLayout(mode_group_box)
        self._mode_group = QButtonGroup(self)
        self._rb_normal = QRadioButton("Словарь + Google")
        self._rb_library_only = QRadioButton("Только словарь")
        self._rb_library_placeholders = QRadioButton("Словарь + создать заглушки")
        for i, rb in enumerate(
            (self._rb_normal, self._rb_library_only, self._rb_library_placeholders)
        ):
            self._mode_group.addButton(rb, i)
            mode_layout.addWidget(rb)
        root.addWidget(mode_group_box)

        opts_group = QGroupBox("Параметры")
        opts_layout = QVBoxLayout(opts_group)
        self._chk_no_overwrite = QCheckBox("Не трогать готовые строки")
        self._chk_no_overwrite.setToolTip(
            "Уже переведённые строки в values-ru не перезаписывать."
        )
        self._chk_dry_run = QCheckBox("Пробный запуск")
        self._chk_strings_only = QCheckBox("Только strings.xml")
        self._chk_auto_collect = QCheckBox("После — собрать словарь из APK")
        self._chk_auto_collect.setToolTip(
            "Пересобрать общий словарь по этому модулю и отчёт конфликтов."
        )
        for chk in (
            self._chk_no_overwrite,
            self._chk_dry_run,
            self._chk_strings_only,
            self._chk_auto_collect,
        ):
            opts_layout.addWidget(chk)
        root.addWidget(opts_group)

        self._mode_hint = QLabel()
        self._mode_hint.setObjectName("hintLabel")
        self._mode_hint.setWordWrap(True)
        root.addWidget(self._mode_hint)

        self._mode_group.buttonClicked.connect(self._on_mode_changed)
        self._chk_dry_run.stateChanged.connect(self._on_mode_changed)
        self._apply_defaults()
        self._on_mode_changed()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Запустить")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _apply_defaults(self) -> None:
        d = self._defaults
        mode_buttons = {
            "normal": self._rb_normal,
            "library_only": self._rb_library_only,
            "library_placeholders": self._rb_library_placeholders,
            "ensure_dictionary": self._rb_library_placeholders,
        }
        mode_buttons.get(d.mode, self._rb_normal).setChecked(True)
        self._chk_no_overwrite.setChecked(d.no_overwrite)
        self._chk_dry_run.setChecked(d.dry_run)
        self._chk_strings_only.setChecked(d.strings_only)
        self._chk_auto_collect.setChecked(d.auto_collect)

    def _on_mode_changed(self) -> None:
        dry = self._chk_dry_run.isChecked()
        self._chk_auto_collect.setEnabled(not dry)
        mode_id = self._mode_group.checkedId()
        hints = {
            0: (
                "Словарь en+zh, затем Google: сначала проход en→ru, потом zh→ru "
                "(нужен интернет)."
            ),
            1: (
                "Подставляет в APK только то, что уже есть в словарях. "
                "Пропуски — ошибка. Google не вызывается."
            ),
            2: (
                "Словарь в APK; для пропусков — заглушка « » в словарь и values-ru. "
                "Google не вызывается."
            ),
        }
        self._mode_hint.setText(hints.get(mode_id, ""))

    def options(self) -> FillModuleOptions:
        mode_map = {0: "normal", 1: "library_only", 2: "library_placeholders"}
        return FillModuleOptions(
            mode=mode_map.get(self._mode_group.checkedId(), "normal"),
            no_overwrite=self._chk_no_overwrite.isChecked(),
            dry_run=self._chk_dry_run.isChecked(),
            strings_only=self._chk_strings_only.isChecked(),
            auto_collect=self._chk_auto_collect.isChecked() and not self._chk_dry_run.isChecked(),
        )

    def wants_auto_collect(self) -> bool:
        return self.options().auto_collect

    def needs_overwrite_warning(self) -> bool:
        return not self._chk_no_overwrite.isChecked()
