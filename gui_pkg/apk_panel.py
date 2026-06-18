"""Вкладка «Действия»: распаковка, сборка и push APK."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui_pkg.config import REPO_ROOT, SCRIPTS_DIR, SETTINGS_APP, SETTINGS_ORG
from gui_pkg.confirm import confirm_dangerous_action
from gui_pkg.scanner import ModuleInfo

_LIB = REPO_ROOT / "library"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from apk_toolchain import (  # noqa: E402
    find_signed_apk_for_module,
    read_package_name,
    toolchain_status,
)

_CLI = SCRIPTS_DIR / "apk_toolchain_cli.py"
_SETUP = SCRIPTS_DIR / "setup_apk_tools.py"


class ApkPanel(QGroupBox):
    def __init__(
        self,
        *,
        get_root: Callable[[], Path | None],
        get_current_module: Callable[[], ModuleInfo | None],
        get_modules: Callable[[], dict[str, ModuleInfo]],
        run_cli: Callable[[list[str], str], None],
        decompile_apk: Callable[[str], None],
        on_modules_changed: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("3.  APK: распаковка, сборка, push", parent)
        self._get_root = get_root
        self._get_current_module = get_current_module
        self._get_modules = get_modules
        self._run_cli = run_cli
        self._decompile_apk = decompile_apk
        self._on_modules_changed = on_modules_changed
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        self._status_label = QLabel()
        self._status_label.setObjectName("hintLabel")
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        self._project_hint = QLabel("Загрузите папку проекта — в списке слева появятся *_src и .apk")
        self._project_hint.setObjectName("hintLabel")
        self._project_hint.setWordWrap(True)
        root.addWidget(self._project_hint)

        setup_row = QHBoxLayout()
        self._btn_setup = QPushButton("Установить инструменты")
        self._btn_setup.setToolTip("Скопировать apktool/apksigner/ключи в vendor/apktools")
        self._btn_setup.clicked.connect(self._run_setup)
        self._btn_refresh_status = QPushButton("Проверить")
        self._btn_refresh_status.clicked.connect(self.refresh_status)
        setup_row.addWidget(self._btn_setup)
        setup_row.addWidget(self._btn_refresh_status)
        setup_row.addStretch()
        root.addLayout(setup_row)

        hint = QLabel(
            "Список модулей слева синхронизирован с папкой проекта: "
            "<b>распакованные *_src</b> и <b>APK без *_src</b> (бейдж «не распакован»). "
            "Двойной щелчок по APK — распаковка."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ── Decompile ───────────────────────────────────────────────────
        dec_row = QHBoxLayout()
        self._btn_decompile_selected = QPushButton("Распаковать выбранный APK")
        self._btn_decompile_selected.setObjectName("primaryBtn")
        self._btn_decompile_selected.clicked.connect(self._decompile_selected)
        self._btn_decompile_other = QPushButton("Другой APK…")
        self._btn_decompile_other.clicked.connect(self._decompile_other_apk)
        dec_row.addWidget(self._btn_decompile_selected)
        dec_row.addWidget(self._btn_decompile_other)
        dec_row.addStretch()
        root.addLayout(dec_row)

        # ── Build ───────────────────────────────────────────────────────
        sign_row = QHBoxLayout()
        sign_row.addWidget(QLabel("Подпись:"))
        self._sign_combo = QComboBox()
        self._sign_combo.addItem("Deepal (системные APK)", "deepal")
        self._sign_combo.addItem("Testkey", "testkey")
        self._sign_combo.addItem("Свои ключи…", "custom")
        sign_row.addWidget(self._sign_combo)
        sign_row.addStretch()
        root.addLayout(sign_row)

        custom_row = QHBoxLayout()
        self._pk8_edit = QLineEdit()
        self._pk8_edit.setPlaceholderText("Путь к .pk8 (для своих ключей)")
        self._x509_edit = QLineEdit()
        self._x509_edit.setPlaceholderText("Путь к .x509.pem")
        btn_pk8 = QPushButton("…")
        btn_pk8.setFixedWidth(36)
        btn_pk8.clicked.connect(lambda: self._pick_key(self._pk8_edit, "PK8 (*.pk8)"))
        btn_x509 = QPushButton("…")
        btn_x509.setFixedWidth(36)
        btn_x509.clicked.connect(lambda: self._pick_key(self._x509_edit, "X509 (*.pem)"))
        custom_row.addWidget(self._pk8_edit, stretch=1)
        custom_row.addWidget(btn_pk8)
        custom_row.addWidget(self._x509_edit, stretch=1)
        custom_row.addWidget(btn_x509)
        root.addLayout(custom_row)

        self._chk_remove_src = QCheckBox("Удалить папку *_src после сборки (опасно)")
        self._chk_remove_src.setToolTip("Аналог build-apk.sh — исходники будут удалены")
        root.addWidget(self._chk_remove_src)

        build_row = QHBoxLayout()
        self._btn_build_module = QPushButton("Собрать выбранный модуль")
        self._btn_build_module.clicked.connect(self._build_current_module)
        self._btn_build_folder = QPushButton("Собрать папку…")
        self._btn_build_folder.clicked.connect(self._build_folder)
        build_row.addWidget(self._btn_build_module)
        build_row.addWidget(self._btn_build_folder)
        build_row.addStretch()
        root.addLayout(build_row)

        # ── Push ────────────────────────────────────────────────────────
        push_row = QHBoxLayout()
        self._package_edit = QLineEdit()
        self._package_edit.setPlaceholderText("package (com.example.app) — из AndroidManifest")
        self._btn_pkg_from_module = QPushButton("Из модуля")
        self._btn_pkg_from_module.clicked.connect(self._fill_package_from_module)
        push_row.addWidget(self._package_edit, stretch=1)
        push_row.addWidget(self._btn_pkg_from_module)
        root.addLayout(push_row)

        push_btn_row = QHBoxLayout()
        self._btn_push_module = QPushButton("Push выбранного модуля")
        self._btn_push_module.setObjectName("primaryBtn")
        self._btn_push_module.clicked.connect(self._push_current_module)
        self._btn_push_apk = QPushButton("Push APK…")
        self._btn_push_apk.clicked.connect(self._push_apk_file)
        push_btn_row.addWidget(self._btn_push_module)
        push_btn_row.addWidget(self._btn_push_apk)
        push_btn_row.addStretch()
        root.addLayout(push_btn_row)

        self._load_settings()
        self.refresh_status()
        self.refresh_project_hint()

    def _load_settings(self) -> None:
        pk8 = self._settings.value("apk/custom_pk8", "", str)
        x509 = self._settings.value("apk/custom_x509", "", str)
        if pk8:
            self._pk8_edit.setText(pk8)
        if x509:
            self._x509_edit.setText(x509)

    def _save_custom_keys(self) -> None:
        self._settings.setValue("apk/custom_pk8", self._pk8_edit.text().strip())
        self._settings.setValue("apk/custom_x509", self._x509_edit.text().strip())

    def refresh_project_hint(self) -> None:
        modules = self._get_modules()
        src_n = sum(1 for m in modules.values() if m.is_src)
        apk_n = sum(1 for m in modules.values() if m.is_apk_only)
        paired = sum(1 for m in modules.values() if m.is_src and m.apk_path is not None)
        if not modules:
            self._project_hint.setText("Загрузите папку проекта — в списке слева появятся *_src и .apk")
            return
        parts = [f"<b>{src_n}</b> распаковано"]
        if apk_n:
            parts.append(f"<b>{apk_n}</b> APK ждут распаковки")
        if paired:
            parts.append(f"<b>{paired}</b> с исходным .apk в папке")
        self._project_hint.setText("Папка проекта: " + " · ".join(parts))

    def refresh_status(self) -> None:
        status = toolchain_status()
        if status.get("ok"):
            text = (
                f"✅ Инструменты готовы · java ✓ · adb "
                f"{'✓' if status.get('adb') else '—'} · vendor/apktools"
            )
        else:
            issues = status.get("issues") or status.get("error") or "не настроено"
            text = f"⚠️ {issues}. Нажмите «Установить инструменты»."
        self._status_label.setText(text)

    def _run_setup(self) -> None:
        self._run_cli([str(_SETUP)], "apk setup")

    def _pick_key(self, target: QLineEdit, filt: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выберите ключ", "", filt)
        if path:
            target.setText(path)

    def _pick_src_dir(self) -> Path | None:
        start = ""
        mod = self._get_current_module()
        if mod and mod.is_src:
            start = str(mod.path)
        else:
            root = self._get_root()
            if root:
                start = str(root)
        path = QFileDialog.getExistingDirectory(self, "Папка *_src", start)
        return Path(path) if path else None

    def _src_path_for_module(self, mod: ModuleInfo) -> Path | None:
        if mod.is_src:
            return mod.path
        return None

    def _build_args(self, src: Path) -> list[str] | None:
        sign = self._sign_combo.currentData()
        args = [str(_CLI), "build", str(src), "--sign", str(sign)]
        if self._chk_remove_src.isChecked():
            if not confirm_dangerous_action(
                self,
                title="Сборка APK",
                summary="Удалить папку исходников после сборки?",
                details=f"Папка {src} будет удалена после успешной подписи.",
            ):
                return None
            args.append("--remove-src")
        if sign == "custom":
            pk8 = self._pk8_edit.text().strip()
            x509 = self._x509_edit.text().strip()
            if not pk8 or not x509:
                QMessageBox.warning(self, "APK", "Укажите пути к .pk8 и .x509.pem")
                return None
            self._save_custom_keys()
            args.extend(["--pk8", pk8, "--x509", x509])
        return args

    def _decompile_apk_path(self, apk: str) -> None:
        self._decompile_apk(apk)

    def _decompile_selected(self) -> None:
        mod = self._get_current_module()
        if not mod:
            QMessageBox.warning(self, "APK", "Выберите APK в списке модулей слева.")
            return
        apk = mod.resolved_apk_path()
        if mod.is_src and apk is None:
            QMessageBox.information(self, "APK", "У выбранного модуля нет исходного .apk в папке проекта.")
            return
        if mod.is_src and apk is not None:
            QMessageBox.information(
                self,
                "APK",
                f"«{mod.display}» уже распакован.\nИсходный APK: {apk.name}",
            )
            return
        if apk is None:
            QMessageBox.warning(self, "APK", "Не удалось определить путь к APK.")
            return
        self._decompile_apk_path(str(apk))

    def _decompile_other_apk(self) -> None:
        root = self._get_root()
        start = str(root) if root else ""
        path, _ = QFileDialog.getOpenFileName(self, "Выберите APK", start, "APK (*.apk)")
        if path:
            self._decompile_apk_path(path)

    def _build_current_module(self) -> None:
        mod = self._get_current_module()
        if not mod:
            QMessageBox.warning(self, "APK", "Выберите распакованный модуль слева.")
            return
        src = self._src_path_for_module(mod)
        if src is None:
            QMessageBox.information(self, "APK", "Сначала распакуйте APK (двойной щелчок в списке).")
            return
        args = self._build_args(src)
        if args:
            self._run_cli(args, f"apk build {mod.display}")

    def _build_folder(self) -> None:
        src = self._pick_src_dir()
        if not src:
            return
        args = self._build_args(src)
        if args:
            self._run_cli(args, f"apk build {src.name}")

    def _fill_package_from_module(self) -> None:
        mod = self._get_current_module()
        if not mod or not mod.is_src:
            QMessageBox.warning(self, "APK", "Выберите распакованный модуль слева.")
            return
        pkg = read_package_name(mod.path)
        if not pkg:
            QMessageBox.warning(
                self,
                "APK",
                "package не найден в AndroidManifest.xml модуля.",
            )
            return
        self._package_edit.setText(pkg)

    def _push_current_module(self) -> None:
        mod = self._get_current_module()
        if not mod or not mod.is_src:
            QMessageBox.warning(self, "APK", "Выберите распакованный модуль слева.")
            return
        pkg = self._package_edit.text().strip() or read_package_name(mod.path) or ""
        if not pkg:
            QMessageBox.warning(self, "APK", "Укажите package name.")
            return
        apk = find_signed_apk_for_module(mod.path, pkg)
        if apk is None:
            QMessageBox.warning(
                self,
                "APK",
                f"Signed APK не найден рядом с модулем.\n"
                f"Ожидается: {mod.path.name}-signed.apk",
            )
            return
        if not confirm_dangerous_action(
            self,
            title="Push на устройство",
            summary=f"Записать {apk.name} в системный раздел?",
            details=f"package: {pkg}\nadb root + remount + push",
        ):
            return
        args = [str(_CLI), "push", "--module", str(mod.path), "--package", pkg]
        self._run_cli(args, f"apk push {mod.display}")

    def _push_apk_file(self) -> None:
        pkg = self._package_edit.text().strip()
        if not pkg:
            QMessageBox.warning(self, "APK", "Укажите package name.")
            return
        apk, _ = QFileDialog.getOpenFileName(self, "Signed APK", "", "APK (*.apk)")
        if not apk:
            return
        if not confirm_dangerous_action(
            self,
            title="Push на устройство",
            summary=f"Записать APK для {pkg}?",
            details="adb root + remount + push",
        ):
            return
        args = [str(_CLI), "push", "--apk", apk, "--package", pkg]
        self._run_cli(args, "apk push")

    def build_current_module(self) -> None:
        self._build_current_module()

    def push_current_module(self) -> None:
        self._fill_package_from_module()
        self._push_current_module()

    def on_command_finished(self, exit_code: int, label: str) -> None:
        self.refresh_status()
        if exit_code != 0:
            return
        if label.startswith("apk setup"):
            self.refresh_status()
        if label.startswith("apk decompile"):
            self.refresh_project_hint()
            if self._on_modules_changed:
                self._on_modules_changed()
