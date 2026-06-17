"""Панель обработки хардкода в layout на вкладке «Действия»."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.config import LAYOUT_DIR
from gui_pkg.scanner import ModuleInfo


class LayoutPanel(QGroupBox):
    """Хардкод в layout-файлах: отчёт, inject в strings.xml, inplace."""

    def __init__(
        self,
        *,
        get_root: Callable[[], Path | None],
        get_current_module: Callable[[], ModuleInfo | None],
        scope_is_all_modules: Callable[[], bool],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("1.  Хардкод в layout-файлах", parent)
        self._get_root = get_root
        self._get_current_module = get_current_module
        self._scope_is_all_modules = scope_is_all_modules

        layout_form = QVBoxLayout(self)
        layout_form.setSpacing(10)

        flow_label = QLabel(
            "Порядок работы:  "
            "<b>Найти</b> → <b>Вынести в strings.xml</b> → "
            "на вкладке <b>Обзор</b> нажать «Только словарь»"
        )
        flow_label.setObjectName("hintLabel")
        flow_label.setWordWrap(True)
        flow_label.setTextFormat(Qt.TextFormat.RichText)
        layout_form.addWidget(flow_label)

        self._mode_group = QButtonGroup(self)
        _modes = [
            (
                "Найти и показать отчёт",
                "Ничего не меняет. В логе появится список файлов и атрибутов с хардкодом.",
            ),
            (
                "Вынести в strings.xml  ✓  (рекомендуется)",
                "Добавляет строку в res/values/strings.xml и заменяет хардкод на @string/hw_…  "
                "После — запустите «Только словарь» на вкладке Обзор.",
            ),
            (
                "Перевести прямо в layout  ⚠  (не рекомендуется)",
                "Быстро, но нарушает Android-архитектуру. "
                "Подходит только если модуль не будет обновляться.",
            ),
        ]

        self._rb_report = QRadioButton()
        self._rb_inject = QRadioButton()
        self._rb_inplace = QRadioButton()
        rbs = [self._rb_report, self._rb_inject, self._rb_inplace]
        self._rb_inject.setChecked(True)

        for i, (rb, (title, hint)) in enumerate(zip(rbs, _modes)):
            self._mode_group.addButton(rb, i)

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(10)

            rb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            row_layout.addWidget(rb, 0, Qt.AlignmentFlag.AlignTop)

            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-weight: 500;")
            hint_lbl = QLabel(hint)
            hint_lbl.setObjectName("hintLabel")
            hint_lbl.setWordWrap(True)
            text_col.addWidget(title_lbl)
            text_col.addWidget(hint_lbl)
            row_layout.addLayout(text_col, 1)

            rb_ref = rb
            row_widget.mousePressEvent = (  # type: ignore[method-assign]
                lambda _evt, r=rb_ref: r.setChecked(True)
            )
            row_widget.setObjectName("radioCard")
            row_widget.setCursor(Qt.CursorShape.PointingHandCursor)
            layout_form.addWidget(row_widget)

        self._chk_dry_run = QCheckBox(
            "Пробный запуск — показать что изменится, ничего не записывать"
        )
        layout_form.addWidget(self._chk_dry_run)

        prefix_row = QHBoxLayout()
        prefix_lbl = QLabel("Префикс новых ключей:")
        prefix_lbl.setToolTip(
            "Новые строки получат имена вида <префикс>_<слово> или <префикс>_0001.\n"
            "Например, префикс «hw» → hw_settings, hw_0001."
        )
        prefix_row.addWidget(prefix_lbl)
        self._key_prefix = QLineEdit("hw")
        self._key_prefix.setMaximumWidth(100)
        self._key_prefix.setToolTip("Только латинские буквы, цифры и подчёркивание.")
        prefix_row.addWidget(self._key_prefix)
        example_lbl = QLabel("→ hw_settings, hw_0001…")
        example_lbl.setObjectName("hintLabel")
        prefix_row.addWidget(example_lbl)
        prefix_row.addStretch()
        layout_form.addLayout(prefix_row)

        btn_row = QHBoxLayout()
        self.run_button = QPushButton("Обработать layout")
        self.run_button.setObjectName("primaryBtn")
        btn_row.addWidget(self.run_button)

        self.scan_button = QPushButton("Только найти (отчёт)")
        self.scan_button.setToolTip("Быстрый скан без изменений — режим «Найти и показать отчёт».")
        btn_row.addWidget(self.scan_button)
        btn_row.addStretch()
        layout_form.addLayout(btn_row)

    def mode_label(self) -> str:
        labels = ("layout report", "layout inject", "layout inplace")
        return labels[max(0, self._mode_group.checkedId())]

    def prepare_report(self) -> None:
        self._rb_report.setChecked(True)

    def prepare_inject(self, *, dry_run: bool = False) -> None:
        self._rb_inject.setChecked(True)
        self._chk_dry_run.setChecked(dry_run)

    def build_args(
        self,
        *,
        parent: QWidget,
        mode: str | None = None,
    ) -> list[str] | None:
        root = self._get_root()
        if root is None:
            QMessageBox.warning(parent, "layout extract", "Укажите папку проекта.")
            return None

        if mode is None:
            mode_id = self._mode_group.checkedId()
            mode = ("report", "inject", "inplace")[max(0, mode_id)]

        args = [str(LAYOUT_DIR / "extract_layout_hardcode.py")]
        if mode == "inject":
            args.append("--inject-values")
        elif mode == "inplace":
            args.append("--translate-inplace")

        if self._scope_is_all_modules():
            args.extend(["--root", str(root)])
        else:
            info = self._get_current_module()
            if not info:
                QMessageBox.warning(
                    parent,
                    "Layout",
                    "Выберите модуль слева или включите «Все модули в папке проекта».",
                )
                return None
            args.extend(["-m", str(info.path)])

        if self._chk_dry_run.isChecked() or mode == "report":
            args.append("--dry-run")

        prefix = self._key_prefix.text().strip()
        if prefix:
            args.extend(["--key-prefix", prefix])
        return args
