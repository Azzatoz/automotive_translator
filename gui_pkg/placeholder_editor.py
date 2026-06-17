"""Сбор и запись заглушек values-ru для быстрого редактирования в GUI."""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from gui_pkg.config import DICT_EN, DICT_ZH, REPO_ROOT, TRANSLATABLE_XML

sys.path.insert(0, str(REPO_ROOT / "library"))
from library_persist import load_track_map, save_track_map  # noqa: E402
from source_resolve import (  # noqa: E402
    SourceVariant,
    canonical_variant,
    collect_source_variants,
    elements_by_key,
    find_item_quantity,
    is_placeholder_ru,
    is_real_translation,
    is_usable_library_ru,
    load_locale_roots,
    lookup_library_ru_for_apply,
    module_values_en_coverage,
    sync_ru_to_variant_keys,
)

Track = Literal["en", "zh"]


def is_untranslated_ru(ru: str | None) -> bool:
    return ru is None or is_placeholder_ru(ru)


@dataclass
class PlaceholderRow:
    row_id: str
    xml_file: str
    resource_id: str
    tag: str
    name: str
    sub_key: str | None
    source: str
    track: str
    ru: str
    variants: list[SourceVariant] = field(default_factory=list)
    library_ru: str | None = None


def _array_get_text(el: ET.Element, index: int) -> str:
    items = el.findall("item")
    if index < len(items):
        return items[index].text or ""
    return ""


def _plural_get_text(el: ET.Element, quantity: str) -> str:
    it = find_item_quantity(el, quantity)
    return (it.text if it is not None else "") or ""


def _write_resources_xml(path: Path, root: ET.Element) -> None:
    ET.indent(root, space="    ")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        ET.ElementTree(root).write(f, encoding="utf-8", xml_declaration=False)
        f.flush()
    tmp.replace(path)
    try:
        with open(path, "rb") as f:
            os.fsync(f.fileno())
    except OSError:
        pass


def _iter_module_translatable_rows(
    module_path: Path,
    *,
    placeholders_only: bool = True,
) -> tuple[list[PlaceholderRow], int, int]:
    """Строки values-ru (+ опционально только заглушки) + (всего переводимых, переведено)."""
    rows: list[PlaceholderRow] = []
    total = 0
    translated = 0
    coverage = module_values_en_coverage(module_path)
    values_en_first = coverage.values_en_first

    for xml_name in TRANSLATABLE_XML:
        ru_path = module_path / "res" / "values-ru" / xml_name
        if not ru_path.is_file():
            continue
        try:
            ru_root = ET.parse(ru_path).getroot()
        except ET.ParseError:
            continue

        locales = load_locale_roots(module_path, xml_name)
        def_map = elements_by_key(locales["def"])
        en_map = elements_by_key(locales["en"])
        zh_cn_map = elements_by_key(locales["zh_cn"])
        zh_map = elements_by_key(locales["zh"])

        for child in ru_root:
            name = child.attrib.get("name")
            if not name:
                continue
            key = (child.tag, name)

            if child.tag == "string":
                def_el = def_map.get(key)
                variants = collect_source_variants(
                    def_el=def_el,
                    en_el=en_map.get(key),
                    zh_cn_el=zh_cn_map.get(key),
                    zh_el=zh_map.get(key),
                    get_text=lambda e: e.text or "",
                )
                if not variants:
                    continue
                total += 1
                ru_text = child.text or ""
                if not is_untranslated_ru(ru_text):
                    translated += 1
                    if placeholders_only:
                        continue
                canon = canonical_variant(variants, values_en_first=values_en_first)
                rows.append(
                    PlaceholderRow(
                        row_id=f"{xml_name}::string/{name}",
                        xml_file=xml_name,
                        resource_id=f"string/{name}",
                        tag="string",
                        name=name,
                        sub_key=None,
                        source=canon.text if canon else "",
                        track=canon.track if canon else "zh",
                        ru=ru_text,
                        variants=variants,
                    )
                )
                continue

            elif child.tag == "plurals":
                def_pl = def_map.get(key)
                en_pl = en_map.get(key)
                zh_cn_pl = zh_cn_map.get(key)
                zh_pl = zh_map.get(key)
                for item in child.findall("item"):
                    q = item.attrib.get("quantity", "")
                    get_text = lambda e, qty=q: _plural_get_text(e, qty)
                    variants = collect_source_variants(
                        def_el=def_pl,
                        en_el=en_pl,
                        zh_cn_el=zh_cn_pl,
                        zh_el=zh_pl,
                        get_text=get_text,
                    )
                    if not variants:
                        continue
                    total += 1
                    ru_text = item.text or ""
                    if not is_untranslated_ru(ru_text):
                        translated += 1
                        if placeholders_only:
                            continue
                    canon = canonical_variant(variants, values_en_first=values_en_first)
                    rows.append(
                        PlaceholderRow(
                            row_id=f"{xml_name}::plurals/{name}#q={q}",
                            xml_file=xml_name,
                            resource_id=f"plurals/{name} ({q})",
                            tag="plurals",
                            name=name,
                            sub_key=q,
                            source=canon.text if canon else "",
                            track=canon.track if canon else "zh",
                            ru=ru_text,
                            variants=variants,
                        )
                    )
                    continue

            elif child.tag == "string-array":
                def_arr = def_map.get(key)
                en_arr = en_map.get(key)
                zh_cn_arr = zh_cn_map.get(key)
                zh_arr = zh_map.get(key)
                for idx, item in enumerate(child.findall("item")):
                    get_text = lambda e, i=idx: _array_get_text(e, i)
                    variants = collect_source_variants(
                        def_el=def_arr,
                        en_el=en_arr,
                        zh_cn_el=zh_cn_arr,
                        zh_el=zh_arr,
                        get_text=get_text,
                    )
                    if not variants:
                        continue
                    total += 1
                    ru_text = item.text or ""
                    if not is_untranslated_ru(ru_text):
                        translated += 1
                        if placeholders_only:
                            continue
                    canon = canonical_variant(variants, values_en_first=values_en_first)
                    rows.append(
                        PlaceholderRow(
                            row_id=f"{xml_name}::array/{name}#[{idx}]",
                            xml_file=xml_name,
                            resource_id=f"array/{name} [{idx}]",
                            tag="string-array",
                            name=name,
                            sub_key=str(idx),
                            source=canon.text if canon else "",
                            track=canon.track if canon else "zh",
                            ru=ru_text,
                            variants=variants,
                        )
                    )

    rows.sort(key=lambda r: (r.xml_file, r.resource_id))
    return rows, total, translated


def collect_module_placeholders(module_path: Path) -> list[PlaceholderRow]:
    """Все строки values-ru с заглушкой или пустым ru."""
    rows, _, _ = _iter_module_translatable_rows(module_path, placeholders_only=True)
    return rows


def collect_all_module_rows(module_path: Path) -> list[PlaceholderRow]:
    """Все переводимые строки values-ru (включая уже переведённые)."""
    rows, _, _ = _iter_module_translatable_rows(module_path, placeholders_only=False)
    return rows


def row_accepts_ru(row: PlaceholderRow, ru: str | None) -> bool:
    """Можно ли записать ru для строки (проверка по всем вариантам исходника)."""
    if not row.variants:
        return is_usable_library_ru(row.source, ru)
    return any(is_usable_library_ru(v.text, ru) for v in row.variants)


def prefill_placeholders_from_library(
    rows: list[PlaceholderRow],
    module_path: Path,
) -> int:
    """Подставить переводы из общего словаря (en/zh) для строк с заглушкой в APK."""
    track_maps: dict[Track, dict[str, str]] = {
        "en": load_track_map(DICT_EN) if DICT_EN.is_file() else {},
        "zh": load_track_map(DICT_ZH) if DICT_ZH.is_file() else {},
    }
    values_en_first = module_values_en_coverage(module_path).values_en_first
    found = 0
    for row in rows:
        if not row.variants:
            continue
        ru, _ = lookup_library_ru_for_apply(
            track_maps,
            row.variants,
            values_en_first=values_en_first,
        )
        if ru:
            row.library_ru = ru
            if is_untranslated_ru(row.ru) and row_accepts_ru(row, ru):
                found += 1
    return found


def library_placeholder_updates(rows: list[PlaceholderRow]) -> dict[str, str]:
    """Готовые пары row_id → ru из словаря (только где APK ещё с заглушкой)."""
    out: dict[str, str] = {}
    for row in rows:
        if not row.library_ru or not is_untranslated_ru(row.ru):
            continue
        if row_accepts_ru(row, row.library_ru):
            out[row.row_id] = row.library_ru.strip()
    return out


def placeholder_dialog_stats(
    rows: list[PlaceholderRow],
    dirty: dict[str, str],
) -> dict[str, int]:
    """Счётчики для окна заглушек: всего, из словаря, в полях, без словаря."""
    row_ids = {r.row_id for r in rows}
    from_library = library_placeholder_updates(rows)
    staged = sum(1 for row_id in dirty if row_id in row_ids)
    total = len(rows)
    manual = sum(
        1
        for row in rows
        if row.row_id not in from_library and row.row_id not in dirty
    )
    return {
        "total": total,
        "from_library": len(from_library),
        "staged": staged,
        "manual": manual,
    }


def module_translation_stats(module_path: Path) -> tuple[int, int, int]:
    """(всего переводимых, переведено, заглушек) — та же логика, что в редакторе заглушек."""
    rows, total, translated = _iter_module_translatable_rows(module_path)
    return total, translated, len(rows)


def _apply_row_to_xml(root: ET.Element, row: PlaceholderRow, ru_text: str) -> bool:
    for child in root:
        if child.attrib.get("name") != row.name or child.tag != row.tag:
            continue
        if row.tag == "string":
            child.text = ru_text
            return True
        if row.tag == "plurals" and row.sub_key:
            it = find_item_quantity(child, row.sub_key)
            if it is not None:
                it.text = ru_text
                return True
            return False
        if row.tag == "string-array" and row.sub_key is not None:
            items = child.findall("item")
            idx = int(row.sub_key)
            if idx < len(items):
                items[idx].text = ru_text
                return True
            return False
    return False


def apply_placeholder_translations(
    module_path: Path,
    rows: list[PlaceholderRow],
    updates: dict[str, str],
    *,
    update_dictionary: bool = True,
) -> tuple[int, int, frozenset[str]]:
    """
    Записать переводы в values-ru и при необходимости в словари.
    updates: row_id → новый ru.
    Возвращает (число строк в XML, число обновлённых ключей словаря, применённые row_id).
    """
    if not updates:
        return 0, 0, frozenset()

    by_row = {r.row_id: r for r in rows}
    by_xml: dict[str, list[tuple[PlaceholderRow, str]]] = {}
    for row_id, ru_text in updates.items():
        row = by_row.get(row_id)
        if row is None:
            continue
        ru_raw = ru_text if ru_text is not None else ""
        if not row_accepts_ru(row, ru_raw.strip()):
            continue
        by_xml.setdefault(row.xml_file, []).append((row, ru_raw))

    applied: set[str] = set()
    xml_count = 0
    for xml_name, pairs in by_xml.items():
        ru_path = module_path / "res" / "values-ru" / xml_name
        if not ru_path.is_file():
            continue
        try:
            root = ET.parse(ru_path).getroot()
        except ET.ParseError:
            continue
        changed = False
        for row, ru_text in pairs:
            if _apply_row_to_xml(root, row, ru_text):
                xml_count += 1
                applied.add(row.row_id)
                changed = True
        if changed:
            _write_resources_xml(ru_path, root)

    if not update_dictionary:
        return xml_count, 0, frozenset(applied)

    track_maps: dict[Track, dict[str, str]] = {
        "en": load_track_map(DICT_EN) if DICT_EN.is_file() else {},
        "zh": load_track_map(DICT_ZH) if DICT_ZH.is_file() else {},
    }
    dict_paths = {"en": DICT_EN, "zh": DICT_ZH}
    dict_keys = 0
    dirty_tracks: set[Track] = set()

    for row_id, ru_text in updates.items():
        if row_id not in applied:
            continue
        row = by_row.get(row_id)
        if row is None or not row.variants:
            continue
        ru_s = (ru_text or "").strip()
        if not is_real_translation(row.source, ru_s):
            continue
        dirty = sync_ru_to_variant_keys(track_maps, row.variants, ru_s)
        dict_keys += len(dirty)
        dirty_tracks |= dirty

    for track in sorted(dirty_tracks):
        save_track_map(dict_paths[track], track, track_maps[track])

    return xml_count, dict_keys, frozenset(applied)
