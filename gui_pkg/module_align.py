"""Сравнение values-ru модуля с общим словарём."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gui_pkg.placeholder_editor import (
    PlaceholderRow,
    collect_all_module_rows,
    is_untranslated_ru,
    prefill_placeholders_from_library,
    row_accepts_ru,
)


@dataclass
class ModuleDictMismatch:
    row: PlaceholderRow
    dict_ru: str

    @property
    def row_id(self) -> str:
        return self.row.row_id

    @property
    def resource_id(self) -> str:
        return self.row.resource_id

    @property
    def source(self) -> str:
        return self.row.source

    @property
    def apk_ru(self) -> str:
        return self.row.ru


def collect_module_dict_mismatches(module_path: Path) -> list[ModuleDictMismatch]:
    """
    Строки, где в словаре есть применимый перевод, а в APK — другое значение
    (включая заглушки).
    """
    rows = collect_all_module_rows(module_path)
    prefill_placeholders_from_library(rows, module_path)
    out: list[ModuleDictMismatch] = []
    for row in rows:
        if not row.library_ru:
            continue
        dict_ru = row.library_ru.strip()
        if not row_accepts_ru(row, dict_ru):
            continue
        apk_ru = (row.ru or "").strip()
        if apk_ru == dict_ru:
            continue
        if not is_untranslated_ru(row.ru) and apk_ru == dict_ru:
            continue
        out.append(ModuleDictMismatch(row=row, dict_ru=dict_ru))
    return out


def count_module_dict_mismatches(module_path: Path) -> int:
    return len(collect_module_dict_mismatches(module_path))


def mismatches_to_updates(mismatches: list[ModuleDictMismatch]) -> dict[str, str]:
    return {m.row_id: m.dict_ru for m in mismatches}


def rows_for_sources(
    module_path: Path,
    sources: set[str],
) -> list[PlaceholderRow]:
    """Строки модуля, чей исходник (любой вариант) входит в sources."""
    if not sources:
        return []
    rows = collect_all_module_rows(module_path)
    prefill_placeholders_from_library(rows, module_path)
    out: list[PlaceholderRow] = []
    for row in rows:
        variant_texts = {v.text for v in row.variants} if row.variants else {row.source}
        if sources & variant_texts:
            out.append(row)
    return out


def updates_for_sources(
    module_path: Path,
    sources: set[str],
) -> dict[str, str]:
    """row_id → ru из словаря для заданных исходников."""
    updates: dict[str, str] = {}
    for row in rows_for_sources(module_path, sources):
        if row.library_ru and row_accepts_ru(row, row.library_ru.strip()):
            updates[row.row_id] = row.library_ru.strip()
    return updates
