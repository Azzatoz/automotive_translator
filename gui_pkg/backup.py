"""Резервное копирование values-ru перед массовой записью."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def backup_module_values_ru(module_path: Path) -> Path | None:
    """
    Скопировать res/values-ru в <module>/.backup/values-ru_YYYY-MM-DD_HHMMSS/.
    Возвращает путь к копии или None, если исходника нет.
    """
    src = module_path / "res" / "values-ru"
    if not src.is_dir():
        return None
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = module_path / ".backup" / f"values-ru_{stamp}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    return dest


def backup_modules_values_ru(module_paths: list[Path]) -> list[Path]:
    """Бэкап для нескольких модулей; пропускает отсутствующие values-ru."""
    out: list[Path] = []
    for path in module_paths:
        backup = backup_module_values_ru(path)
        if backup is not None:
            out.append(backup)
    return out
