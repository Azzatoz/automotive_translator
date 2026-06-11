#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сканирует каталог с Android-модулями (*_src) и собирает ДВЕ библиотеки переводов в values-ru.

Два независимых трека (ключ ресурса → исходник → русский):

  en — translation_library_ru_en.json
       Все уникальные латинские (не-CJK) тексты из values-en, values-zh*, values.

  zh — translation_library_ru_zh-rCN.json
       Все уникальные CJK-тексты из values-zh-rCN, values-zh, values-en*, values.

Сопоставление всегда по КЛЮЧУ ресурса (имя string/plurals/array, quantity, индекс item),
а не только обходом res/values. Русский берётся из res/values-ru по тому же ключу.

Дополнительно для каждого трека:
  — missing: нет перевода или ru совпадает с исходником;
  — pending (translation_library_ru_*_pending.json): исходники missing_no_ru_key с пустым ru;
  — conflicts: один исходник переведён по-разному (в отчёт; в словарь — последний по порядку скана);
  — merge с существующей библиотекой (--library-en / --library-zh): новые пары добавляются.

Пример:
  python3 tools\\ Linux/library/collect_translation_library_ru.py \\
    --root "D:/Voyah/.../On translate" \\
    --track both
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from library_persist import PENDING_KIND, order_string_map  # noqa: E402
from source_resolve import (  # noqa: E402
    PLACEHOLDER_RU,
    Track,
    canonical_variant,
    collect_source_variants,
    elements_by_key,
    find_item_quantity,
    has_cjk,
    is_placeholder_ru,
    looks_technical,
    module_values_en_coverage,
    ensure_placeholders_in_map,
    skip_for_translation_library,
    variants_for_track,
)

TRANSLATABLE_XML = ("strings.xml", "plurals.xml", "arrays.xml")

_SKIP_NAME_PREFIXES = ("agc_",)
_SKIP_NAMES = frozenset(
    {
        "ag_sdk_cbg_root",
        "rk",
        "tasktransfer_whitelist_authentication",
        "fa_auth_text",
    }
)

@dataclass
class StringOccurrence:
    module: str
    resource_id: str
    xml_file: str
    source: str
    ru: str | None
    status: str
    track: Track
    source_locale: str  # values-en | values-zh-rCN | values | ...


@dataclass
class ScanStats:
    modules_total: int = 0
    modules_with_values: int = 0
    modules_with_values_ru: int = 0
    occurrences: int = 0
    unique_sources: int = 0
    translated_pairs: int = 0
    missing_count: int = 0
    conflicts: int = 0
    placeholder_entries: int = 0
    pending_added: int = 0
    pending_promoted: int = 0
    pending_removed: int = 0


def _should_skip_name(name: str) -> bool:
    if name in _SKIP_NAMES:
        return True
    return any(name.startswith(p) for p in _SKIP_NAME_PREFIXES)


def _parse_xml(path: Path) -> ET.Element | None:
    if not path.is_file():
        return None
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as e:
        print(f"[warn] XML parse error {path}: {e}", file=sys.stderr)
        return None


_elements_by_key = elements_by_key
_find_item_quantity = find_item_quantity
_has_cjk = has_cjk
_looks_technical = looks_technical


def _collect_resource_keys(*roots: ET.Element | None) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for root in roots:
        if root is None:
            continue
        for el in root:
            name = el.attrib.get("name")
            if name and not _should_skip_name(name):
                keys.add((el.tag, name))
    return keys


def _plural_quantities(*elements: ET.Element | None) -> set[str]:
    qs: set[str] = set()
    for el in elements:
        if el is None:
            continue
        for item in el.findall("item"):
            q = item.attrib.get("quantity")
            if q:
                qs.add(q)
    return qs


def _array_item_count(*elements: ET.Element | None) -> int:
    n = 0
    for el in elements:
        if el is None:
            continue
        n = max(n, len(el.findall("item")))
    return n


def _classify_translation(source: str, ru: str | None) -> str:
    src = (source or "").strip()
    ru_s = (ru or "").strip()
    if not src:
        return "missing_empty_source"
    if ru is None:
        return "missing_no_ru_key"
    if not ru_s:
        return "missing_empty_ru"
    if ru_s == src:
        return "missing_ru_equals_source"
    if is_placeholder_ru(ru):
        return "missing_empty_ru"
    return "translated"


def _iter_pairs_for_track(
    module_name: str,
    xml_name: str,
    track: Track,
    root_def: ET.Element | None,
    root_en: ET.Element | None,
    root_zh_cn: ET.Element | None,
    root_zh: ET.Element | None,
    root_ru: ET.Element | None,
    *,
    values_ru_exists: bool,
    values_en_first: bool,
) -> list[StringOccurrence]:
    out: list[StringOccurrence] = []
    def_map = _elements_by_key(root_def)
    en_map = _elements_by_key(root_en)
    zh_cn_map = _elements_by_key(root_zh_cn)
    zh_map = _elements_by_key(root_zh)
    ru_map = _elements_by_key(root_ru)

    if track == "en":
        source_roots = (root_en, root_def, root_ru)
    else:
        source_roots = (root_zh_cn, root_zh, root_def, root_ru)

    for tag, name in sorted(_collect_resource_keys(*source_roots)):
        key = (tag, name)
        def_el = def_map.get(key)
        ru_el = ru_map.get(key)

        if tag == "string":

            def _str_text(el: ET.Element) -> str:
                return el.text or ""

            all_variants = collect_source_variants(
                def_el=def_el,
                en_el=en_map.get(key),
                zh_cn_el=zh_cn_map.get(key),
                zh_el=zh_map.get(key),
                get_text=_str_text,
            )
            track_variants = variants_for_track(all_variants, track)
            if not track_variants:
                continue

            ru_text = ru_el.text if ru_el is not None else None
            if not values_ru_exists:
                status = "missing_no_values_ru"
            else:
                primary = canonical_variant(
                    all_variants,
                    values_en_first=values_en_first,
                    track=track,
                )
                src_for_status = (
                    primary.text if primary is not None else track_variants[0].text
                )
                status = _classify_translation(src_for_status, ru_text)

            for v in track_variants:
                out.append(
                    StringOccurrence(
                        module=module_name,
                        resource_id=f"string/{name}",
                        xml_file=xml_name,
                        source=v.text,
                        ru=ru_text,
                        status=status,
                        track=track,
                        source_locale=v.locale,
                    )
                )

        elif tag == "plurals":
            quantities = _plural_quantities(
                def_el,
                en_map.get(key) if track == "en" else None,
                zh_cn_map.get(key) if track == "zh" else None,
                zh_map.get(key) if track == "zh" else None,
                ru_el,
            )
            en_node = en_map.get(key)
            zh_cn_node = zh_cn_map.get(key)
            zh_node = zh_map.get(key)

            for q in sorted(quantities):

                def _pl_text(el: ET.Element) -> str:
                    it = _find_item_quantity(el, q)
                    return (it.text if it is not None else "") or ""

                all_variants = collect_source_variants(
                    def_el=def_el,
                    en_el=en_node,
                    zh_cn_el=zh_cn_node,
                    zh_el=zh_node,
                    get_text=_pl_text,
                )
                track_variants = variants_for_track(all_variants, track)
                if not track_variants:
                    continue

                ru_item = _find_item_quantity(ru_el, q)
                ru_text = ru_item.text if ru_item is not None else None
                if not values_ru_exists:
                    status = "missing_no_values_ru"
                else:
                    primary = canonical_variant(
                        all_variants,
                        values_en_first=values_en_first,
                        track=track,
                    )
                    src_for_status = (
                        primary.text if primary is not None else track_variants[0].text
                    )
                    status = _classify_translation(src_for_status, ru_text)

                for v in track_variants:
                    out.append(
                        StringOccurrence(
                            module=module_name,
                            resource_id=f"plurals/{name}#quantity={q}",
                            xml_file=xml_name,
                            source=v.text,
                            ru=ru_text,
                            status=status,
                            track=track,
                            source_locale=v.locale,
                        )
                    )

        elif tag == "string-array":
            n_items = _array_item_count(def_el, en_map.get(key), zh_cn_map.get(key), zh_map.get(key), ru_el)
            en_node = en_map.get(key)
            zh_cn_node = zh_cn_map.get(key)
            zh_node = zh_map.get(key)
            def_items = list(def_el.findall("item")) if def_el is not None else []
            en_items = list(en_node.findall("item")) if en_node is not None else []
            zh_cn_items = list(zh_cn_node.findall("item")) if zh_cn_node is not None else []
            zh_items = list(zh_node.findall("item")) if zh_node is not None else []
            ru_items = list(ru_el.findall("item")) if ru_el is not None else []

            for i in range(n_items):

                def _arr_text(el: ET.Element) -> str:
                    items = el.findall("item")
                    return (items[i].text if i < len(items) else "") or ""

                all_variants = collect_source_variants(
                    def_el=def_el,
                    en_el=en_node,
                    zh_cn_el=zh_cn_node,
                    zh_el=zh_node,
                    get_text=_arr_text,
                )
                track_variants = variants_for_track(all_variants, track)
                if not track_variants:
                    continue

                ru_text = ru_items[i].text if i < len(ru_items) else None
                if not values_ru_exists:
                    status = "missing_no_values_ru"
                else:
                    primary = canonical_variant(
                        all_variants,
                        values_en_first=values_en_first,
                        track=track,
                    )
                    src_for_status = (
                        primary.text if primary is not None else track_variants[0].text
                    )
                    status = _classify_translation(src_for_status, ru_text)

                for v in track_variants:
                    out.append(
                        StringOccurrence(
                            module=module_name,
                            resource_id=f"array/{name}#[{i}]",
                            xml_file=xml_name,
                            source=v.text,
                            ru=ru_text,
                            status=status,
                            track=track,
                            source_locale=v.locale,
                        )
                    )

    return out


def scan_module(module_dir: Path, track: Track) -> list[StringOccurrence]:
    module_name = module_dir.name
    res = module_dir / "res"
    values_dir = res / "values"
    values_en_dir = res / "values-en"
    values_zh_cn_dir = res / "values-zh-rCN"
    values_zh_dir = res / "values-zh"
    values_ru_dir = res / "values-ru"
    values_ru_exists = values_ru_dir.is_dir()

    cov = module_values_en_coverage(module_dir)
    if cov.warning:
        print(f"[warn] {module_name}: {cov.warning}", file=sys.stderr, flush=True)

    occurrences: list[StringOccurrence] = []
    for xml_name in TRANSLATABLE_XML:
        root_def = _parse_xml(values_dir / xml_name)
        root_en = _parse_xml(values_en_dir / xml_name)
        root_zh_cn = _parse_xml(values_zh_cn_dir / xml_name)
        root_zh = _parse_xml(values_zh_dir / xml_name)
        root_ru = _parse_xml(values_ru_dir / xml_name) if values_ru_exists else None

        if track == "en":
            if root_en is None and root_def is None and root_ru is None:
                continue
        else:
            if root_zh_cn is None and root_zh is None and root_def is None and root_ru is None:
                continue

        occurrences.extend(
            _iter_pairs_for_track(
                module_name,
                xml_name,
                track,
                root_def,
                root_en,
                root_zh_cn,
                root_zh,
                root_ru,
                values_ru_exists=values_ru_exists,
                values_en_first=cov.values_en_first,
            )
        )
    return occurrences


def discover_modules(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    res = root / "res"
    if (res / "values").is_dir() or (res / "values-en").is_dir():
        return [root]
    modules: list[Path] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        eres = entry / "res"
        if (eres / "values").is_dir() or (eres / "values-en").is_dir():
            modules.append(entry)
    return modules


def _last_translated_ru(occs: list[StringOccurrence]) -> str | None:
    """Последний готовый ru по порядку сканирования модулей."""
    for occ in reversed(occs):
        if occ.status != "translated":
            continue
        ru = (occ.ru or "").strip()
        if ru:
            return ru
    return None


def build_library(
    all_occurrences: list[StringOccurrence],
    existing_map: dict[str, str],
    *,
    overwrite_library: bool = True,
) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, Any]], ScanStats]:
    stats = ScanStats()
    modules_seen: set[str] = set()
    modules_with_values: set[str] = set()

    translation_votes: dict[str, Counter[str]] = defaultdict(Counter)
    by_source: dict[str, list[StringOccurrence]] = defaultdict(list)

    for occ in all_occurrences:
        modules_seen.add(occ.module)
        modules_with_values.add(occ.module)
        stats.occurrences += 1
        src = occ.source.strip()
        if not src or skip_for_translation_library(src):
            continue
        by_source[src].append(occ)
        if occ.status == "translated" and occ.ru:
            translation_votes[src][occ.ru.strip()] += 1
        if occ.status != "translated":
            stats.missing_count += 1

    stats.modules_total = len(modules_seen)
    stats.modules_with_values = len(modules_with_values)
    stats.unique_sources = len(by_source)

    conflicts: list[dict[str, Any]] = []
    string_map: dict[str, str] = dict(existing_map)

    for src, counter in sorted(translation_votes.items(), key=lambda kv: kv[0]):
        if not counter or skip_for_translation_library(src):
            continue
        occs = by_source[src]
        if len(counter) > 1:
            stats.conflicts += 1
            variants: dict[str, list[str]] = {}
            for ru_text, _ in counter.most_common():
                mods = sorted(
                    {o.module for o in occs if (o.ru or "").strip() == ru_text}
                )
                variants[ru_text] = mods
            chosen = _last_translated_ru(occs)
            conflicts.append(
                {"source": src, "translations": variants, "chosen": chosen}
            )
            ru_text = chosen
            if ru_text is None:
                continue
        else:
            ru_text = counter.most_common(1)[0][0]
        stats.translated_pairs += 1
        if overwrite_library or src not in string_map:
            string_map[src] = ru_text

    missing: list[dict[str, Any]] = []
    seen_missing: set[tuple[str, str, str]] = set()

    for src, occs in sorted(by_source.items(), key=lambda kv: kv[0]):
        if src in string_map:
            continue
        for occ in occs:
            if occ.status == "translated":
                continue
            key = (src, occ.module, occ.resource_id)
            if key in seen_missing:
                continue
            seen_missing.add(key)
            missing.append(
                {
                    "source": src,
                    "module": occ.module,
                    "resource": occ.resource_id,
                    "xml": occ.xml_file,
                    "reason": occ.status,
                    "ru": occ.ru,
                    "source_locale": occ.source_locale,
                    "track": occ.track,
                }
            )

    return string_map, conflicts, missing, stats


def _apply_missing_placeholders(
    string_map: dict[str, str],
    sources: Iterable[str],
    placeholder_ru: str,
) -> int:
    """Заглушка для исходников APK без готового ru (новые и «битые» записи)."""
    return ensure_placeholders_in_map(
        string_map, sources, placeholder_ru=placeholder_ru
    )


def _filter_missing_in_library(
    missing: list[dict[str, Any]], string_map: dict[str, str]
) -> list[dict[str, Any]]:
    return [m for m in missing if (m.get("source") or "").strip() not in string_map]


def _no_ru_sources_from_missing(missing: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for item in missing:
        if item.get("reason") != "missing_no_ru_key":
            continue
        src = (item.get("source") or "").strip()
        if src and not looks_technical(src) and not skip_for_translation_library(src):
            out.add(src)
    return out


def update_pending_dictionary(
    missing: list[dict[str, Any]],
    pending: dict[str, str],
    string_map: dict[str, str],
    *,
    overwrite_library: bool,
) -> tuple[dict[str, str], dict[str, str], int, int, int]:
    """
    Обновить pending-словарь (missing_no_ru_key) и перенести заполненные переводы в main.

    Возвращает (pending, string_map, added, promoted, removed).
    """
    no_ru_sources = _no_ru_sources_from_missing(missing)
    new_pending: dict[str, str] = {}
    promoted = 0
    removed = 0
    added = 0

    for src, ru in pending.items():
        if looks_technical(src) or skip_for_translation_library(src):
            removed += 1
            continue
        if src in string_map and not is_placeholder_ru(string_map.get(src)):
            removed += 1
            continue
        if ru and not is_placeholder_ru(ru):
            if overwrite_library or src not in string_map:
                string_map[src] = ru
            promoted += 1
            continue
        # Пустые pending сохраняем между разными --root, пока нет перевода в APK
        new_pending[src] = ru

    for src in sorted(no_ru_sources):
        if src in string_map and not is_placeholder_ru(string_map.get(src)):
            continue
        if src in new_pending:
            continue
        new_pending[src] = ""
        if src not in pending:
            added += 1

    return new_pending, string_map, added, promoted, removed


def _load_library(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    sm = data.get("string_map")
    if not isinstance(sm, dict):
        raise ValueError(f"{path}: ожидается объект string_map")
    return {str(k): str(v) for k, v in sm.items()}


def _apply_resolutions(existing: dict[str, str], res_path: Path | None, quiet: bool) -> int:
    if res_path is None:
        return 0
    res_path = res_path.expanduser().resolve()
    res_data = json.loads(res_path.read_text(encoding="utf-8"))
    raw_res = res_data.get("resolutions") or {}
    n_res = 0
    for src, val in raw_res.items():
        if isinstance(val, str):
            chosen = val.strip()
        elif isinstance(val, dict):
            chosen = (val.get("chosen") or "").strip()
        else:
            continue
        if chosen:
            existing[src] = chosen
            n_res += 1
    if not quiet:
        print(f"[info] resolutions: {res_path} ({n_res} записей в string_map)")
    return n_res


def _load_existing_for_track(
    track: Track,
    library_arg: Path | None,
    output_path: Path,
    quiet: bool,
) -> dict[str, str]:
    existing: dict[str, str] = {}
    if library_arg is not None:
        lib_path = library_arg.expanduser().resolve()
        existing = _load_library(lib_path)
        if not quiet:
            print(f"[info][{track}] загружена библиотека: {lib_path} ({len(existing)} записей)")
    elif output_path.is_file():
        try:
            existing = _load_library(output_path.resolve())
            if not quiet:
                print(f"[info][{track}] merge с существующим {output_path} ({len(existing)} записей)")
        except (json.JSONDecodeError, ValueError):
            pass
    return existing


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_track(
    track: Track,
    modules: list[Path],
    root: Path,
    existing: dict[str, str],
    output: Path,
    missing_output: Path,
    conflicts_output: Path,
    pending_output: Path | None,
    *,
    quiet: bool,
    no_missing_file: bool,
    no_conflicts_file: bool,
    add_missing_placeholders: bool = False,
    placeholder_ru: str = " ",
    placeholder_conflicts: bool = True,
    overwrite_library: bool = True,
) -> int:
    all_occurrences: list[StringOccurrence] = []
    ru_modules = 0
    for mod in modules:
        occs = scan_module(mod, track)
        all_occurrences.extend(occs)
        if (mod / "res" / "values-ru").is_dir():
            ru_modules += 1
        if not quiet:
            n_tr = sum(1 for o in occs if o.status == "translated")
            n_miss = len(occs) - n_tr
            print(f"[scan][{track}] {mod.name}: переведено {n_tr}, без перевода {n_miss}")

    string_map, conflicts, missing, stats = build_library(
        all_occurrences, existing, overwrite_library=overwrite_library
    )
    stats.modules_with_values_ru = ru_modules
    size_after_translated = len(string_map)

    if add_missing_placeholders:
        apk_sources = {
            (occ.source or "").strip()
            for occ in all_occurrences
            if (occ.source or "").strip()
        }
        if placeholder_conflicts:
            for conflict in conflicts:
                src = (conflict.get("source") or "").strip()
                if src:
                    apk_sources.add(src)
        stats.placeholder_entries = _apply_missing_placeholders(
            string_map,
            apk_sources,
            placeholder_ru,
        )
        missing = _filter_missing_in_library(missing, string_map)
        if not quiet and stats.placeholder_entries:
            print(
                f"[placeholders][{track}] добавлено заглушек: {stats.placeholder_entries} "
                f"(ru={placeholder_ru!r})"
            )

    pending_map: dict[str, str] = {}
    if pending_output is not None:
        pending_existing = _load_library(pending_output) if pending_output.is_file() else {}
        pending_map, string_map, stats.pending_added, stats.pending_promoted, stats.pending_removed = (
            update_pending_dictionary(
                missing,
                pending_existing,
                string_map,
                overwrite_library=overwrite_library,
            )
        )
        if not quiet and (stats.pending_added or stats.pending_promoted or stats.pending_removed):
            print(
                f"[pending][{track}] +{stats.pending_added} новых, "
                f"перенесено в основной: {stats.pending_promoted}, "
                f"убрано (уже в APK): {stats.pending_removed}"
            )

    track_label = "en" if track == "en" else "zh-rCN" 
    library_payload = {
        "schema_version": 2,
        "track": track_label,
        "string_map": order_string_map(string_map),
        "meta": {
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_root": str(root),
            "track": track_label,
            "modules_scanned": len(modules),
            "stats": {
                "modules_total": stats.modules_total,
                "modules_with_values_ru": stats.modules_with_values_ru,
                "occurrences": stats.occurrences,
                "unique_sources": stats.unique_sources,
                "string_map_size": len(string_map),
                "new_entries": len(string_map) - len(existing),
                "new_translated_entries": size_after_translated - len(existing),
                "placeholder_entries": stats.placeholder_entries,
                "pending_added": stats.pending_added,
                "pending_promoted": stats.pending_promoted,
                "pending_removed": stats.pending_removed,
                "missing_entries": len(missing),
                "conflicts": stats.conflicts,
            },
        },
    }

    out_path = output.expanduser().resolve()
    _save_json(out_path, library_payload)
    print(
        f"[write][{track}] {out_path} — string_map: {len(string_map)} "
        f"(+{len(string_map) - len(existing)} новых)"
    )

    if not no_missing_file:
        missing_payload = {
            "schema_version": 2,
            "track": track_label,
            "missing": missing,
            "meta": library_payload["meta"],
        }
        miss_path = missing_output.expanduser().resolve()
        _save_json(miss_path, missing_payload)
        print(f"[write][{track}] {miss_path} — недостающих: {len(missing)}")

    if not no_conflicts_file:
        conflicts_payload = {
            "schema_version": 2,
            "track": track_label,
            "conflicts": conflicts,
            "meta": library_payload["meta"],
        }
        conf_path = conflicts_output.expanduser().resolve()
        _save_json(conf_path, conflicts_payload)
        print(f"[write][{track}] {conf_path} — конфликтов: {len(conflicts)}")

    if pending_output is not None:
        pending_payload = {
            "schema_version": 2,
            "track": track_label,
            "kind": PENDING_KIND,
            "string_map": order_string_map(pending_map),
            "meta": {
                **library_payload["meta"],
                "pending_total": len(pending_map),
                "pending_empty": sum(
                    1 for v in pending_map.values() if is_placeholder_ru(v)
                ),
            },
        }
        pend_path = pending_output.expanduser().resolve()
        _save_json(pend_path, pending_payload)
        print(
            f"[write][{track}] {pend_path} — pending: {len(pending_map)} "
            f"(пустых: {pending_payload['meta']['pending_empty']})"
        )

    print(
        f"[done][{track}] модулей {len(modules)}, уникальных исходников {stats.unique_sources}, "
        f"библиотека {len(string_map)}, без перевода {len(missing)}, "
        f"pending {len(pending_map)}, конфликтов {len(conflicts)}"
    )
    return 0


def main() -> int:
    tools_root = Path(__file__).resolve().parent.parent
    default_root = tools_root.parent / "Translated"
    reports_dir = tools_root / "reports"

    ap = argparse.ArgumentParser(
        description="Сбор библиотек переводов (треки en и zh-rCN) из res/values-* и values-ru"
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=default_root,
        help=f"Корень с модулями *_src или один модуль (по умолчанию {default_root})",
    )
    ap.add_argument(
        "--track",
        choices=("en", "zh", "both"),
        default="both",
        help="Какой трек собирать: en, zh или оба (по умолчанию both)",
    )
    ap.add_argument(
        "--output-en",
        type=Path,
        default=tools_root / "data" / "dictionaries" / "translation_library_ru_en.json",
        help="Выход: библиотека en → ru",
    )
    ap.add_argument(
        "--output-zh",
        type=Path,
        default=tools_root / "data" / "dictionaries" / "translation_library_ru_zh-rCN.json",
        help="Выход: библиотека zh-rCN → ru",
    )
    ap.add_argument(
        "--missing-output-en",
        type=Path,
        default=reports_dir / "translation_library_ru_en_missing.json",
        help="Отчёт missing для трека en",
    )
    ap.add_argument(
        "--missing-output-zh",
        type=Path,
        default=reports_dir / "translation_library_ru_zh-rCN_missing.json",
        help="Отчёт missing для трека zh",
    )
    ap.add_argument(
        "--conflicts-output-en",
        type=Path,
        default=reports_dir / "translation_library_ru_en_conflicts.json",
        help="Отчёт conflicts для трека en",
    )
    ap.add_argument(
        "--conflicts-output-zh",
        type=Path,
        default=reports_dir / "translation_library_ru_zh-rCN_conflicts.json",
        help="Отчёт conflicts для трека zh",
    )
    ap.add_argument(
        "--pending-output-en",
        type=Path,
        default=tools_root / "data" / "pending" / "translation_library_ru_en_pending.json",
        help="Очередь перевода en (missing_no_ru_key, пустой ru)",
    )
    ap.add_argument(
        "--pending-output-zh",
        type=Path,
        default=tools_root / "data" / "pending" / "translation_library_ru_zh-rCN_pending.json",
        help="Очередь перевода zh (missing_no_ru_key, пустой ru)",
    )
    ap.add_argument(
        "--no-pending-dictionary",
        action="store_true",
        help="Не обновлять translation_library_ru_*_pending.json",
    )
    ap.add_argument(
        "--library-en",
        type=Path,
        default=None,
        help="Существующая en-библиотека для merge",
    )
    ap.add_argument(
        "--library-zh",
        type=Path,
        default=None,
        help="Существующая zh-библиотека для merge",
    )
    ap.add_argument(
        "--resolutions-en",
        type=Path,
        default=None,
        help="Ручные решения конфликтов en (chosen → string_map)",
    )
    ap.add_argument(
        "--resolutions-zh",
        type=Path,
        default=None,
        help="Ручные решения конфликтов zh (chosen → string_map)",
    )
    ap.add_argument(
        "--no-missing-file",
        action="store_true",
        help="Не писать файлы missing",
    )
    ap.add_argument(
        "--no-conflicts-file",
        action="store_true",
        help="Не писать файлы conflicts",
    )
    ap.add_argument("-q", "--quiet", action="store_true", help="Только итоговая статистика")
    ap.add_argument(
        "--no-overwrite-library",
        action="store_true",
        help="Не перезаписывать уже существующие ключи в string_map (только добавлять новые)",
    )
    ap.add_argument(
        "--add-missing-placeholders",
        action="store_true",
        help="Добавить в string_map пропущенные исходники с заглушкой (см. --placeholder-ru)",
    )
    ap.add_argument(
        "--placeholder-ru",
        default=PLACEHOLDER_RU,
        help="Значение ru для пропущенных исходников (по умолчанию один пробел)",
    )
    ap.add_argument(
        "--placeholder-conflicts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="При --add-missing-placeholders также завести исходники из conflicts",
    )
    args = ap.parse_args()

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"Нет каталога: {root}", file=sys.stderr)
        return 1

    modules = discover_modules(root)
    if not modules:
        print(f"[warn] модули с res/values или res/values-en не найдены в {root}", file=sys.stderr)
        return 1

    tracks: list[Track] = []
    if args.track in ("en", "both"):
        tracks.append("en")
    if args.track in ("zh", "both"):
        tracks.append("zh")

    for track in tracks:
        if track == "en":
            existing = _load_existing_for_track(
                track, args.library_en, args.output_en.resolve(), args.quiet
            )
            _apply_resolutions(existing, args.resolutions_en, args.quiet)
            _run_track(
                track,
                modules,
                root,
                existing,
                args.output_en,
                args.missing_output_en,
                args.conflicts_output_en,
                None if args.no_pending_dictionary else args.pending_output_en,
                quiet=args.quiet,
                no_missing_file=args.no_missing_file,
                no_conflicts_file=args.no_conflicts_file,
                add_missing_placeholders=args.add_missing_placeholders,
                placeholder_ru=args.placeholder_ru,
                placeholder_conflicts=args.placeholder_conflicts,
                overwrite_library=not args.no_overwrite_library,
            )
        else:
            existing = _load_existing_for_track(
                track, args.library_zh, args.output_zh.resolve(), args.quiet
            )
            _apply_resolutions(existing, args.resolutions_zh, args.quiet)
            _run_track(
                track,
                modules,
                root,
                existing,
                args.output_zh,
                args.missing_output_zh,
                args.conflicts_output_zh,
                None if args.no_pending_dictionary else args.pending_output_zh,
                quiet=args.quiet,
                no_missing_file=args.no_missing_file,
                no_conflicts_file=args.no_conflicts_file,
                add_missing_placeholders=args.add_missing_placeholders,
                placeholder_ru=args.placeholder_ru,
                placeholder_conflicts=args.placeholder_conflicts,
                overwrite_library=not args.no_overwrite_library,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
