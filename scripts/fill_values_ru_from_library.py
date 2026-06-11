#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Заполняет res/values-ru из res/values: сначала translation_library_ru.json,
при отсутствии — Google Translate (deep-translator).

В конце — отчёт со списком строк, переведённых через Google.

Пример (один модуль):
  python3 scripts/fill_values_ru_from_library.py \\
    -m "/path/to/AndesDLNA_src" --source-lang zh-CN

Все модули в Translated:
  python3 scripts/fill_values_ru_from_library.py \\
    --root "/path/to/Translated" --source-lang zh-CN --delay 0.2

Только отчёт без записи XML:
  python3 tools/fill_values_ru_from_library.py -m ... --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_ROOT = REPO_ROOT
sys.path.insert(0, str(REPO_ROOT / "functions"))
sys.path.insert(0, str(REPO_ROOT / "library"))

import fill_values_ru as fvr  # noqa: E402
from library_persist import load_track_map, save_track_map  # noqa: E402
from source_resolve import (  # noqa: E402
    PLACEHOLDER_RU,
    SourceVariant,
    Track,
    any_variant_in_merged_map,
    canonical_source_text,
    collect_source_variants,
    elements_by_key,
    ensure_ru_from_track_maps,
    find_item_quantity,
    is_android_resource_reference,
    is_placeholder_ru,
    is_real_translation,
    library_path_for_track,
    load_locale_roots,
    lookup_ru_in_merged_map,
    module_values_en_coverage,
    pick_android_resource_reference_from_elements,
    pick_assist_name_from_elements,
    looks_technical,
    skip_for_translation_library,
    sync_ru_to_variant_keys,
)

TRANSLATABLE_XML = ("strings.xml", "plurals.xml", "arrays.xml")
_DEFAULT_DICT = TOOLS_ROOT / "data" / "dictionaries"
DEFAULT_LIBRARY_LEGACY = _DEFAULT_DICT / "translation_library_ru.json"
DEFAULT_LIBRARY_EN = _DEFAULT_DICT / "translation_library_ru_en.json"
DEFAULT_LIBRARY_ZH = _DEFAULT_DICT / "translation_library_ru_zh-rCN.json"
DEFAULT_LIBRARY = DEFAULT_LIBRARY_ZH
DEFAULT_ROOT = TOOLS_ROOT.parent / "Translated"
_FQCN_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", re.I)
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufadf]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")


class SkipTranslation(Exception):
    """Исходник не на --source-lang: не переводить и не менять values-ru."""


def _default_library_for_source(source_lang: str) -> Path:
    sl = (source_lang or "zh-CN").lower().replace("_", "-")
    if sl.startswith("en"):
        return DEFAULT_LIBRARY_EN
    if sl.startswith("zh"):
        return DEFAULT_LIBRARY_ZH
    return DEFAULT_LIBRARY_ZH

def _copy_as_is(text: str) -> bool:
    """Классы, ссылки @android:string, шаблоны — копировать без Google."""
    s = text.strip()
    if not s:
        return True
    if skip_for_translation_library(s):
        return True
    if _FQCN_RE.match(s):
        return True
    if re.fullmatch(r"%[\d$]*[sdifuxXoeEc%./\\n\\'\"\\s-]+", s):
        return True
    return False


def _apply_android_resource_passthrough(
    tgt_el: ET.Element,
    *,
    def_el: ET.Element,
    en_el: ET.Element | None,
    zh_cn_el: ET.Element | None,
    zh_el: ET.Element | None,
    get_text: Callable[[ET.Element], str],
    dry_run: bool,
) -> bool:
    """Копирует @android:string/… в values-ru без словаря и Google."""
    ref = pick_android_resource_reference_from_elements(
        def_el=def_el,
        en_el=en_el,
        zh_cn_el=zh_cn_el,
        zh_el=zh_el,
        get_text=get_text,
    )
    if ref is None:
        return False
    if not dry_run:
        tgt_el.text = ref
    return True


def _apply_assist_name_passthrough(
    tgt_el: ET.Element,
    *,
    def_el: ET.Element,
    en_el: ET.Element | None,
    zh_cn_el: ET.Element | None,
    zh_el: ET.Element | None,
    get_text: Callable[[ET.Element], str],
    dry_run: bool,
) -> bool:
    """Копирует {assistName:…} в values-ru без словаря."""
    ref = pick_assist_name_from_elements(
        def_el=def_el,
        en_el=en_el,
        zh_cn_el=zh_cn_el,
        zh_el=zh_el,
        get_text=get_text,
    )
    if ref is None:
        return False
    if not dry_run:
        tgt_el.text = ref
    return True


def _apply_skip_passthrough(
    tgt_el: ET.Element,
    *,
    def_el: ET.Element,
    en_el: ET.Element | None,
    zh_cn_el: ET.Element | None,
    zh_el: ET.Element | None,
    get_text: Callable[[ET.Element], str],
    dry_run: bool,
) -> bool:
    """@android:string/… и {assistName:…} — копировать как есть."""
    if _apply_android_resource_passthrough(
        tgt_el,
        def_el=def_el,
        en_el=en_el,
        zh_cn_el=zh_cn_el,
        zh_el=zh_el,
        get_text=get_text,
        dry_run=dry_run,
    ):
        return True
    return _apply_assist_name_passthrough(
        tgt_el,
        def_el=def_el,
        en_el=en_el,
        zh_cn_el=zh_cn_el,
        zh_el=zh_el,
        get_text=get_text,
        dry_run=dry_run,
    )


def _matches_source_lang(text: str, source_lang: str) -> bool:
    """
    True — строку из res/values можно переводить с выбранным --source-lang.
    Иначе пропуск (не Google, не подстановка из словаря).
    """
    s = (text or "").strip()
    if not s:
        return True
    if skip_for_translation_library(s):
        return True

    sl = (source_lang or "zh-CN").lower().replace("_", "-")
    has_cjk = bool(_CJK_RE.search(s))
    has_latin = bool(_LATIN_RE.search(s))
    has_cyrillic = bool(_CYRILLIC_RE.search(s))

    if sl.startswith("zh"):
        if has_cjk:
            return True
        if has_latin and not has_cjk:
            return False
        if has_cyrillic and not has_cjk:
            return False
        return True

    if sl.startswith("en"):
        if has_cjk:
            return False
        if has_cyrillic and not has_latin:
            return False
        return has_latin

    return True


def _assert_source_lang(text: str, source_lang: str, *, lang_filter: bool) -> None:
    if lang_filter and not _matches_source_lang(text, source_lang):
        raise SkipTranslation()


@dataclass
class TranslateStats:
    library: int = 0
    google: int = 0
    unchanged: int = 0
    not_in_library: int = 0
    lang_skipped: int = 0
    registered_placeholder: int = 0
    applied_from_library: int = 0
    synced_to_dictionary: int = 0
    errors: int = 0


@dataclass
class SessionReport:
    stats: TranslateStats = field(default_factory=TranslateStats)
    google_entries: list[dict[str, Any]] = field(default_factory=list)
    library_sample: list[dict[str, Any]] = field(default_factory=list)

    def record_library(
        self, *, module: str, resource_key: str, xml_file: str, source: str, ru: str
    ) -> None:
        self.stats.library += 1
        if len(self.library_sample) < 50:
            self.library_sample.append(
                {
                    "module": module,
                    "resource": resource_key,
                    "xml": xml_file,
                    "source": source,
                    "ru": ru,
                }
            )

    def record_google(
        self, *, module: str, resource_key: str, xml_file: str, source: str, ru: str
    ) -> None:
        self.stats.google += 1
        self.google_entries.append(
            {
                "module": module,
                "resource": resource_key,
                "xml": xml_file,
                "source": source,
                "ru": ru,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )


def _load_string_maps(*paths: Path) -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        sm = data.get("string_map") or {}
        if not isinstance(sm, dict):
            raise ValueError(f"{path}: string_map должен быть объектом")
        for k, v in sm.items():
            ks = str(k)
            if ks not in merged:
                merged[ks] = str(v)
    return merged


def _discover_modules(root: Path) -> list[Path]:
    """Один модуль, если у root есть res/values; иначе — подкаталоги с res/values."""
    if not root.is_dir():
        return []
    if (root / "res" / "values").is_dir():
        return [root]
    return sorted(
        p for p in root.iterdir() if p.is_dir() and (p / "res" / "values").is_dir()
    )


def _checkpoint_path(module_dir: Path, tools_dir: Path) -> Path:
    safe = module_dir.name.replace("/", "_")
    d = tools_dir / "checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}_fill_library_ru.json"


def _load_checkpoint(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("done_keys", []))
    except (json.JSONDecodeError, OSError):
        return set()


def _log_values_en_coverage(module_dir: Path) -> bool:
    cov = module_values_en_coverage(module_dir)
    if cov.warning:
        print(f"[warn] {module_dir.name}: {cov.warning}", file=sys.stderr, flush=True)
    elif cov.values_en_first:
        print(
            f"[info] {module_dir.name}: values-en "
            f"{cov.named_in_values_en}/{cov.named_in_values} ({cov.ratio:.0%}) — "
            f"приоритет values-en",
            flush=True,
        )
    return cov.values_en_first


def _save_checkpoint(path: Path, done_keys: set[str], meta: dict[str, Any]) -> None:
    payload = {
        "done_keys": sorted(done_keys),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **meta,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def make_translator(
    string_map: dict[str, str],
    *,
    source_lang: str,
    target_lang: str,
    allow_google: bool,
    translate_delay: float,
    lang_filter: bool,
    values_en_first: bool,
    report: SessionReport,
    module_name: str,
    xml_file: str,
) -> Callable[[str, str], str]:
    """translate_fn(text, resource_key) -> ru text; бросает при ошибке Google."""

    def translate(
        text: str,
        resource_key: str,
        variants: list[SourceVariant] | None = None,
    ) -> str:
        vlist = variants or []
        ru_hit, matched_src = lookup_ru_in_merged_map(
            string_map, vlist, values_en_first=values_en_first
        )
        if ru_hit is not None and matched_src is not None:
            report.record_library(
                module=module_name,
                resource_key=resource_key,
                xml_file=xml_file,
                source=matched_src,
                ru=ru_hit,
            )
            return ru_hit

        src = text or ""
        if not src.strip() and vlist:
            src = vlist[0].text
        if not src.strip():
            return src
        if _copy_as_is(src):
            return src
        _assert_source_lang(src, source_lang, lang_filter=lang_filter)

        if src in string_map:
            ru = string_map[src]
            if is_real_translation(src, ru):
                report.record_library(
                    module=module_name,
                    resource_key=resource_key,
                    xml_file=xml_file,
                    source=src,
                    ru=ru,
                )
                return ru

        if not allow_google:
            raise RuntimeError("нет в библиотеке и Google отключён (--library-only)")

        print(
            f"  [Google] {module_name} {resource_key}",
            flush=True,
        )
        ru = fvr._translate_with_google(src, source_lang, target_lang)
        report.record_google(
            module=module_name,
            resource_key=resource_key,
            xml_file=xml_file,
            source=src,
            ru=ru,
        )
        if translate_delay > 0:
            time.sleep(translate_delay)
        return ru

    return translate


def _queue_translation(
    *,
    library_overwrite: bool,
    string_map: dict[str, str],
    skip_existing: bool,
    ru_text: str | None,
    source_text: str | None,
    resource_name: str,
    source_lang: str,
    lang_filter: bool,
    variants: list[SourceVariant] | None = None,
    values_en_first: bool = False,
) -> bool:
    """True — поставить строку в очередь на перевод."""
    if skip_for_translation_library((source_text or "").strip()):
        return False
    src = canonical_source_text(
        variants or [], source_text, values_en_first=values_en_first
    )
    if skip_for_translation_library(src):
        return False
    if lang_filter and src and not _matches_source_lang(src, source_lang):
        return False
    if library_overwrite:
        if fvr._values_ru_never_override(resource_name):
            return False
        if variants and any_variant_in_merged_map(
            string_map, variants, values_en_first=values_en_first
        ):
            return True
        if not src or _copy_as_is(src):
            return False
        ru = string_map.get(src)
        return ru is not None and is_real_translation(src, ru)
    if is_placeholder_ru(ru_text):
        return True
    return not fvr._should_skip_filled_ru(skip_existing, ru_text, source_text)


def _should_skip_ensure(
    skip_existing: bool,
    ru_text: str | None,
    source_text: str | None,
) -> bool:
    if not skip_existing:
        return False
    if is_placeholder_ru(ru_text):
        return False
    return fvr._should_skip_filled_ru(skip_existing, ru_text, source_text)


def _sync_apk_ru_to_dictionary(
    track_maps: dict[Track, dict[str, str]],
    dirty_tracks: set[Track],
    variants: list[SourceVariant],
    ru_text: str,
    report: SessionReport,
) -> None:
    """Перезаписать все варианты исходника в en/zh словарях переводом из values-ru."""
    if skip_for_translation_library(ru_text):
        return
    if any(skip_for_translation_library(v.text) for v in variants):
        return
    dirty = sync_ru_to_variant_keys(track_maps, variants, ru_text)
    if dirty:
        dirty_tracks.update(dirty)
        report.stats.synced_to_dictionary += 1


def _count_lang_skip(
    *,
    lang_filter: bool,
    source_text: str | None,
    source_lang: str,
    queued: bool,
) -> bool:
    """True, если строка пропущена из‑за несовпадения языка с --source-lang."""
    src = (source_text or "").strip()
    return bool(lang_filter and src and not queued and not _matches_source_lang(src, source_lang))


def _should_count_not_in_library(
    *,
    string_map: dict[str, str],
    source_text: str | None,
    variants: list[SourceVariant] | None,
    values_en_first: bool,
) -> bool:
    """
    True — в словаре нет применимого перевода: только заглушка или ключа нет.
    Техстроки, copy-as-is и записи ru=source / с любым ru в JSON не считаются.
    """
    canon = canonical_source_text(
        variants or [], source_text, values_en_first=values_en_first
    )
    src = (canon or (source_text or "")).strip()
    if not src:
        return False
    if skip_for_translation_library(src):
        return False
    if _copy_as_is(src) or looks_technical(src):
        return False
    ru_hit, _ = lookup_ru_in_merged_map(
        string_map, variants or [], values_en_first=values_en_first
    )
    if ru_hit is not None:
        return False

    def _dict_has_usable_entry(text: str) -> bool:
        ru = string_map.get(text)
        if ru is None:
            return False
        return not is_placeholder_ru(ru)

    if _dict_has_usable_entry(src):
        return False
    for v in variants or []:
        if _dict_has_usable_entry(v.text):
            return False
    return True


def _fill_one_xml(
    module_dir: Path,
    xml_name: str,
    *,
    translate_for_key: Callable[[str, str], str],
    done_keys: set[str],
    skip_existing: bool,
    library_overwrite: bool,
    string_map: dict[str, str],
    source_lang: str,
    lang_filter: bool,
    values_en_first: bool,
    dry_run: bool,
    report: SessionReport,
) -> tuple[int, ET.Element | None, Path | None]:
    """Возвращает (errors, merged_root или None, values_ru_path)."""
    values_default = module_dir / "res" / "values" / xml_name
    values_ru_path = module_dir / "res" / "values-ru" / xml_name
    if not values_default.is_file():
        return 0, None, None

    tree_def = ET.parse(values_default)
    root_def = tree_def.getroot()

    if values_ru_path.is_file():
        root_ru = ET.parse(values_ru_path).getroot()
    else:
        root_ru = None

    locale_roots = load_locale_roots(module_dir, xml_name)
    en_map = elements_by_key(locale_roots["en"])
    zh_cn_map = elements_by_key(locale_roots["zh_cn"])
    zh_map = elements_by_key(locale_roots["zh"])

    ru_by_key = fvr._collect_string_like_keys(root_ru) if root_ru is not None else {}
    merged_root = ET.Element("resources")
    pending: list[tuple[str, str, ET.Element, ET.Element, list[SourceVariant]]] = []

    for child in root_def:
        name = child.attrib.get("name")
        if not name:
            merged_root.append(fvr._deep_copy_el(child))
            continue

        key = (child.tag, name)
        ru_match = ru_by_key.get(key)
        ru_node = ru_match[0] if ru_match else None

        if child.tag == "string":
            new_el = ET.Element("string", child.attrib)
            if fvr._values_ru_never_override(name):
                new_el.text = child.text or ""
            else:
                new_el.text = (ru_node.text if ru_node is not None else None) or child.text or ""
            merged_root.append(new_el)
            sk = f"{xml_name}::string/{name}"
            if sk in done_keys or fvr._values_ru_never_override(name):
                continue
            if _apply_skip_passthrough(
                new_el,
                def_el=child,
                en_el=en_map.get(key),
                zh_cn_el=zh_cn_map.get(key),
                zh_el=zh_map.get(key),
                get_text=lambda e: e.text or "",
                dry_run=dry_run,
            ):
                report.stats.unchanged += 1
                continue
            variants = collect_source_variants(
                def_el=child,
                en_el=en_map.get(key),
                zh_cn_el=zh_cn_map.get(key),
                zh_el=zh_map.get(key),
                get_text=lambda e: e.text or "",
            )
            queued = _queue_translation(
                library_overwrite=library_overwrite,
                string_map=string_map,
                skip_existing=skip_existing,
                ru_text=ru_node.text if ru_node is not None else None,
                source_text=child.text,
                resource_name=name,
                source_lang=source_lang,
                lang_filter=lang_filter,
                variants=variants,
                values_en_first=values_en_first,
            )
            if not queued:
                if _count_lang_skip(
                    lang_filter=lang_filter,
                    source_text=child.text,
                    source_lang=source_lang,
                    queued=False,
                ):
                    report.stats.lang_skipped += 1
                elif library_overwrite and _should_count_not_in_library(
                    string_map=string_map,
                    source_text=child.text,
                    variants=variants,
                    values_en_first=values_en_first,
                ):
                    report.stats.not_in_library += 1
                else:
                    report.stats.unchanged += 1
                continue
            pending.append((sk, f"string/{name}", child, new_el, variants))

        elif child.tag == "plurals":
            en_node = en_map.get(key)
            zh_cn_node = zh_cn_map.get(key)
            zh_node = zh_map.get(key)
            new_pl = ET.Element("plurals", child.attrib)
            for item in child.findall("item"):
                q = item.attrib.get("quantity", "")
                ru_item = fvr._find_item_quantity(ru_node, q) if ru_node is not None else None
                ni = ET.Element("item", item.attrib)
                ni.text = (ru_item.text if ru_item else None) or item.text or ""
                new_pl.append(ni)
            merged_root.append(new_pl)
            for item in child.findall("item"):
                q = item.attrib.get("quantity", "")
                sk = f"{xml_name}::plurals/{name}#quantity={q}"
                if sk in done_keys:
                    continue
                ru_item = fvr._find_item_quantity(ru_node, q) if ru_node is not None else None
                src_it = fvr._find_item_quantity(child, q)
                tgt_it = fvr._find_item_quantity(new_pl, q)
                if src_it is None or tgt_it is None:
                    continue

                def _pl_text(el: ET.Element) -> str:
                    it = fvr._find_item_quantity(el, q)
                    return (it.text if it is not None else "") or ""

                if _apply_skip_passthrough(
                    tgt_it,
                    def_el=child,
                    en_el=en_node,
                    zh_cn_el=zh_cn_node,
                    zh_el=zh_node,
                    get_text=_pl_text,
                    dry_run=dry_run,
                ):
                    report.stats.unchanged += 1
                    continue
                variants = collect_source_variants(
                    def_el=child,
                    en_el=en_node,
                    zh_cn_el=zh_cn_node,
                    zh_el=zh_node,
                    get_text=_pl_text,
                )
                queued = _queue_translation(
                    library_overwrite=library_overwrite,
                    string_map=string_map,
                    skip_existing=skip_existing,
                    ru_text=ru_item.text if ru_item is not None else None,
                    source_text=src_it.text,
                    resource_name=name,
                    source_lang=source_lang,
                    lang_filter=lang_filter,
                    variants=variants,
                    values_en_first=values_en_first,
                )
                if not queued:
                    if _count_lang_skip(
                        lang_filter=lang_filter,
                        source_text=src_it.text,
                        source_lang=source_lang,
                        queued=False,
                    ):
                        report.stats.lang_skipped += 1
                    elif library_overwrite and _should_count_not_in_library(
                        string_map=string_map,
                        source_text=src_it.text,
                        variants=variants,
                        values_en_first=values_en_first,
                    ):
                        report.stats.not_in_library += 1
                    else:
                        report.stats.unchanged += 1
                    continue
                pending.append((sk, f"plurals/{name}#quantity={q}", src_it, tgt_it, variants))

        elif child.tag == "string-array":
            en_node = en_map.get(key)
            zh_cn_node = zh_cn_map.get(key)
            zh_node = zh_map.get(key)
            new_arr = ET.Element("string-array", child.attrib)
            ru_items = list(ru_node.findall("item")) if ru_node is not None else []
            for i, item in enumerate(child.findall("item")):
                ni = ET.Element("item")
                if i < len(ru_items) and ru_items[i].text:
                    ni.text = ru_items[i].text
                else:
                    ni.text = item.text or ""
                new_arr.append(ni)
            merged_root.append(new_arr)
            for i, item in enumerate(child.findall("item")):
                sk = f"{xml_name}::array/{name}#[{i}]"
                if sk in done_keys:
                    continue
                tgt_it = new_arr.findall("item")[i]
                ru_it = ru_items[i].text if i < len(ru_items) else None  # noqa: PLR2004

                def _arr_text(el: ET.Element) -> str:
                    items = el.findall("item")
                    return (items[i].text if i < len(items) else "") or ""

                if _apply_skip_passthrough(
                    tgt_it,
                    def_el=child,
                    en_el=en_node,
                    zh_cn_el=zh_cn_node,
                    zh_el=zh_node,
                    get_text=_arr_text,
                    dry_run=dry_run,
                ):
                    report.stats.unchanged += 1
                    continue
                variants = collect_source_variants(
                    def_el=child,
                    en_el=en_node,
                    zh_cn_el=zh_cn_node,
                    zh_el=zh_node,
                    get_text=_arr_text,
                )
                queued = _queue_translation(
                    library_overwrite=library_overwrite,
                    string_map=string_map,
                    skip_existing=skip_existing,
                    ru_text=ru_it,
                    source_text=item.text,
                    resource_name=name,
                    source_lang=source_lang,
                    lang_filter=lang_filter,
                    variants=variants,
                    values_en_first=values_en_first,
                )
                if not queued:
                    if _count_lang_skip(
                        lang_filter=lang_filter,
                        source_text=item.text,
                        source_lang=source_lang,
                        queued=False,
                    ):
                        report.stats.lang_skipped += 1
                    elif library_overwrite and _should_count_not_in_library(
                        string_map=string_map,
                        source_text=item.text,
                        variants=variants,
                        values_en_first=values_en_first,
                    ):
                        report.stats.not_in_library += 1
                    else:
                        report.stats.unchanged += 1
                    continue
                pending.append((sk, f"array/{name}#[{i}]", item, tgt_it, variants))
        else:
            merged_root.append(fvr._deep_copy_el(child))

    errors = 0
    module_name = module_dir.name
    work = [
        (sk, res_key, src_el, tgt_el, variants)
        for sk, res_key, src_el, tgt_el, variants in pending
        if variants or (src_el.text or "").strip()
    ]
    total = len(work)
    if total:
        print(f"[{module_name}] {xml_name}: {total} строк к переводу", flush=True)

    for idx, (sk, res_key, src_el, tgt_el, variants) in enumerate(work, 1):
        src_text = canonical_source_text(
            variants, src_el.text or "", values_en_first=values_en_first
        )
        try:
            new_text = translate_for_key(src_text, res_key, variants)
        except SkipTranslation:
            report.stats.lang_skipped += 1
            continue
        except Exception as e:  # noqa: BLE001
            print(f"[err] {module_name} {sk}: {e}", file=sys.stderr, flush=True)
            report.stats.errors += 1
            errors += 1
            continue
        if not dry_run:
            tgt_el.text = new_text
            done_keys.add(sk)
        if idx == 1 or idx == total or idx % 25 == 0:
            print(f"  [{idx}/{total}] {res_key}", flush=True)

    return errors, merged_root, values_ru_path


def _fill_one_xml_ensure(
    module_dir: Path,
    xml_name: str,
    *,
    track_maps: dict[Track, dict[str, str]],
    dirty_tracks: set[Track],
    skip_existing: bool,
    overwrite_apk: bool,
    sync_dictionary_from_apk: bool,
    values_en_first: bool,
    dry_run: bool,
    placeholder_ru: str,
    report: SessionReport,
) -> tuple[ET.Element | None, Path | None]:
    """Словарь en/zh + заглушка PLACEHOLDER_RU; Google не вызывается."""
    values_default = module_dir / "res" / "values" / xml_name
    values_ru_path = module_dir / "res" / "values-ru" / xml_name
    if not values_default.is_file():
        return None, None

    roots = load_locale_roots(module_dir, xml_name)
    root_def = roots["def"]
    if root_def is None:
        return None, None

    root_en = roots["en"]
    root_zh_cn = roots["zh_cn"]
    root_zh = roots["zh"]
    root_ru = roots["ru"]

    en_map = elements_by_key(root_en)
    zh_cn_map = elements_by_key(root_zh_cn)
    zh_map = elements_by_key(root_zh)
    ru_by_key = elements_by_key(root_ru)

    merged_root = ET.Element("resources")
    module_name = module_dir.name
    work = 0

    for child in root_def:
        name = child.attrib.get("name")
        if not name:
            merged_root.append(fvr._deep_copy_el(child))
            continue

        key = (child.tag, name)
        ru_match = ru_by_key.get(key)
        ru_node = ru_match if ru_match is not None else None

        if child.tag == "string":
            new_el = ET.Element("string", child.attrib)
            if fvr._values_ru_never_override(name):
                new_el.text = child.text or ""
            else:
                new_el.text = (ru_node.text if ru_node is not None else None) or child.text or ""

            merged_root.append(new_el)
            if fvr._values_ru_never_override(name):
                continue

            if _apply_skip_passthrough(
                new_el,
                def_el=child,
                en_el=en_map.get(key),
                zh_cn_el=zh_cn_map.get(key),
                zh_el=zh_map.get(key),
                get_text=lambda e: e.text or "",
                dry_run=dry_run,
            ):
                report.stats.unchanged += 1
                continue

            variants = collect_source_variants(
                def_el=child,
                en_el=en_map.get(key),
                zh_cn_el=zh_cn_map.get(key),
                zh_el=zh_map.get(key),
                get_text=lambda e: e.text or "",
            )
            if not variants:
                report.stats.unchanged += 1
                continue
            canon_src = canonical_source_text(
                variants, child.text, values_en_first=values_en_first
            )
            if skip_for_translation_library(canon_src):
                report.stats.unchanged += 1
                continue
            ru_apk = ru_node.text if ru_node is not None else None
            if sync_dictionary_from_apk and ru_apk:
                _sync_apk_ru_to_dictionary(
                    track_maps, dirty_tracks, variants, ru_apk, report
                )
            if not overwrite_apk and _should_skip_ensure(
                skip_existing, ru_apk, canon_src
            ):
                report.stats.unchanged += 1
                continue

            ru_val, dirty, from_lib = ensure_ru_from_track_maps(
                track_maps,
                variants,
                placeholder_ru=placeholder_ru,
                values_en_first=values_en_first,
            )
            dirty_tracks.update(dirty)
            if dirty:
                report.stats.registered_placeholder += 1
            if from_lib:
                report.stats.applied_from_library += 1
            if not dry_run:
                new_el.text = ru_val
            work += 1

        elif child.tag == "plurals":
            new_pl = ET.Element("plurals", child.attrib)
            en_node = en_map.get(key)
            zh_cn_node = zh_cn_map.get(key)
            zh_node = zh_map.get(key)

            for item in child.findall("item"):
                q = item.attrib.get("quantity", "")
                ru_item = find_item_quantity(ru_node, q) if ru_node is not None else None
                ni = ET.Element("item", item.attrib)
                ni.text = (ru_item.text if ru_item is not None else None) or item.text or ""
                new_pl.append(ni)

            merged_root.append(new_pl)

            for item in child.findall("item"):
                q = item.attrib.get("quantity", "")
                src_it = find_item_quantity(child, q)
                tgt_it = find_item_quantity(new_pl, q)
                if src_it is None or tgt_it is None:
                    continue
                ru_item = find_item_quantity(ru_node, q) if ru_node is not None else None

                def _pl_text(el: ET.Element) -> str:
                    it = find_item_quantity(el, q)
                    return (it.text if it is not None else "") or ""

                if _apply_skip_passthrough(
                    tgt_it,
                    def_el=child,
                    en_el=en_node,
                    zh_cn_el=zh_cn_node,
                    zh_el=zh_node,
                    get_text=_pl_text,
                    dry_run=dry_run,
                ):
                    report.stats.unchanged += 1
                    continue

                variants = collect_source_variants(
                    def_el=child,
                    en_el=en_node,
                    zh_cn_el=zh_cn_node,
                    zh_el=zh_node,
                    get_text=_pl_text,
                )
                if not variants:
                    report.stats.unchanged += 1
                    continue
                canon_src = canonical_source_text(
                    variants, src_it.text, values_en_first=values_en_first
                )
                if skip_for_translation_library(canon_src):
                    report.stats.unchanged += 1
                    continue
                ru_apk = ru_item.text if ru_item is not None else None
                if sync_dictionary_from_apk and ru_apk:
                    _sync_apk_ru_to_dictionary(
                        track_maps, dirty_tracks, variants, ru_apk, report
                    )
                if not overwrite_apk and _should_skip_ensure(
                    skip_existing, ru_apk, canon_src
                ):
                    report.stats.unchanged += 1
                    continue

                ru_val, dirty, from_lib = ensure_ru_from_track_maps(
                    track_maps,
                    variants,
                    placeholder_ru=placeholder_ru,
                    values_en_first=values_en_first,
                )
                dirty_tracks.update(dirty)
                if dirty:
                    report.stats.registered_placeholder += 1
                if from_lib:
                    report.stats.applied_from_library += 1
                if not dry_run:
                    tgt_it.text = ru_val
                work += 1

        elif child.tag == "string-array":
            new_arr = ET.Element("string-array", child.attrib)
            ru_items = list(ru_node.findall("item")) if ru_node is not None else []
            en_node = en_map.get(key)
            zh_cn_node = zh_cn_map.get(key)
            zh_node = zh_map.get(key)

            for i, item in enumerate(child.findall("item")):
                ni = ET.Element("item")
                if i < len(ru_items) and ru_items[i].text:
                    ni.text = ru_items[i].text
                else:
                    ni.text = item.text or ""
                new_arr.append(ni)
            merged_root.append(new_arr)

            for i, item in enumerate(child.findall("item")):
                tgt_it = new_arr.findall("item")[i]
                ru_it = ru_items[i].text if i < len(ru_items) else None  # noqa: PLR2004

                def _arr_text(el: ET.Element) -> str:
                    items = el.findall("item")
                    return (items[i].text if i < len(items) else "") or ""

                if _apply_skip_passthrough(
                    tgt_it,
                    def_el=child,
                    en_el=en_node,
                    zh_cn_el=zh_cn_node,
                    zh_el=zh_node,
                    get_text=_arr_text,
                    dry_run=dry_run,
                ):
                    report.stats.unchanged += 1
                    continue

                variants = collect_source_variants(
                    def_el=child,
                    en_el=en_node,
                    zh_cn_el=zh_cn_node,
                    zh_el=zh_node,
                    get_text=_arr_text,
                )
                if not variants:
                    report.stats.unchanged += 1
                    continue
                canon_src = canonical_source_text(
                    variants, item.text, values_en_first=values_en_first
                )
                if skip_for_translation_library(canon_src):
                    report.stats.unchanged += 1
                    continue
                if sync_dictionary_from_apk and ru_it:
                    _sync_apk_ru_to_dictionary(
                        track_maps, dirty_tracks, variants, ru_it, report
                    )
                if not overwrite_apk and _should_skip_ensure(
                    skip_existing, ru_it, canon_src
                ):
                    report.stats.unchanged += 1
                    continue

                ru_val, dirty, from_lib = ensure_ru_from_track_maps(
                    track_maps,
                    variants,
                    placeholder_ru=placeholder_ru,
                    values_en_first=values_en_first,
                )
                dirty_tracks.update(dirty)
                if dirty:
                    report.stats.registered_placeholder += 1
                if from_lib:
                    report.stats.applied_from_library += 1
                if not dry_run:
                    tgt_it.text = ru_val
                work += 1
        else:
            merged_root.append(fvr._deep_copy_el(child))

    if work:
        print(f"[{module_name}] {xml_name}: обработано {work} (словарь/заглушка)", flush=True)

    return merged_root, values_ru_path


def fill_module_ensure_dictionary(
    module_dir: Path,
    *,
    track_maps: dict[Track, dict[str, str]],
    library_paths: dict[Track, Path],
    skip_existing: bool,
    overwrite_apk: bool,
    sync_dictionary_from_apk: bool,
    dry_run: bool,
    placeholder_ru: str,
    xml_files: tuple[str, ...],
    report: SessionReport,
) -> None:
    dirty_tracks: set[Track] = set()
    reg0 = report.stats.registered_placeholder
    app0 = report.stats.applied_from_library
    sync0 = report.stats.synced_to_dictionary

    merged_by_xml: dict[str, tuple[ET.Element, Path]] = {}
    values_en_first = _log_values_en_coverage(module_dir)

    for xml_name in xml_files:
        merged_root, ru_path = _fill_one_xml_ensure(
            module_dir,
            xml_name,
            track_maps=track_maps,
            dirty_tracks=dirty_tracks,
            skip_existing=skip_existing,
            overwrite_apk=overwrite_apk,
            sync_dictionary_from_apk=sync_dictionary_from_apk,
            values_en_first=values_en_first,
            dry_run=dry_run,
            placeholder_ru=placeholder_ru,
            report=report,
        )
        if merged_root is not None and ru_path is not None:
            merged_by_xml[xml_name] = (merged_root, ru_path)

    if not dry_run:
        for _xml, (merged_root, ru_path) in merged_by_xml.items():
            ET.indent(merged_root, space="    ")
            ru_path.parent.mkdir(parents=True, exist_ok=True)
            with open(ru_path, "wb") as f:
                f.write('<?xml version="1.0" encoding="utf-8"?>\n'.encode("utf-8"))
            ET.ElementTree(merged_root).write(ru_path, encoding="utf-8", xml_declaration=False)
            print(f"[save] {ru_path}", flush=True)

        for track in sorted(dirty_tracks):
            save_track_map(library_paths[track], track, track_maps[track])
            print(f"[save] словарь [{track}] {library_paths[track]}", flush=True)

    reg_n = report.stats.registered_placeholder - reg0
    app_n = report.stats.applied_from_library - app0
    sync_n = report.stats.synced_to_dictionary - sync0
    if reg_n == 0 and app_n == 0 and sync_n == 0:
        print(f"[ok] нечего индексировать в {module_dir.name}")
    else:
        print(
            f"[done] {module_dir.name}: новых заглушек {reg_n}, "
            f"в словарь из APK {sync_n}, в APK из словаря {app_n} "
            f"(Google не использовался)",
            flush=True,
        )


def fill_module(
    module_dir: Path,
    *,
    string_map: dict[str, str],
    source_lang: str,
    target_lang: str,
    tools_dir: Path,
    report: SessionReport,
    resume: bool,
    skip_existing: bool,
    save_every: int,
    translate_delay: float,
    library_only: bool,
    library_overwrite: bool,
    lang_filter: bool,
    dry_run: bool,
    xml_files: tuple[str, ...],
) -> int:
    cp_path = _checkpoint_path(module_dir, tools_dir)
    done_keys: set[str] = _load_checkpoint(cp_path) if resume else set()
    stats_lib0 = report.stats.library
    stats_google0 = report.stats.google
    lang_skipped0 = report.stats.lang_skipped
    if library_overwrite:
        library_only = True
    allow_google = not library_only and fvr.GoogleTranslator is not None

    if not library_only and fvr.GoogleTranslator is None:
        print(
            "Ошибка: нужен deep-translator для fallback.\n"
            "  pip install deep-translator\n"
            "  или bash scripts/run_fill_values_ru_from_library.sh (из корня репозитория)\n"
            "  или --library-only",
            file=sys.stderr,
        )
        return 1

    merged_by_xml: dict[str, tuple[ET.Element, Path]] = {}
    total_errors = 0
    changed_since_save = 0
    translated_total = 0
    values_en_first = _log_values_en_coverage(module_dir)

    def flush_all() -> None:
        nonlocal changed_since_save
        for _xml, (merged_root, ru_path) in merged_by_xml.items():
            if dry_run:
                continue
            ET.indent(merged_root, space="    ")
            ru_path.parent.mkdir(parents=True, exist_ok=True)
            with open(ru_path, "wb") as f:
                f.write('<?xml version="1.0" encoding="utf-8"?>\n'.encode("utf-8"))
            ET.ElementTree(merged_root).write(ru_path, encoding="utf-8", xml_declaration=False)
            print(f"[save] {ru_path}")
        if not dry_run and merged_by_xml:
            _save_checkpoint(
                cp_path,
                done_keys,
                {"module": str(module_dir), "checkpoint": str(cp_path)},
            )
        changed_since_save = 0

    for xml_name in xml_files:
        tr = make_translator(
            string_map,
            source_lang=source_lang,
            target_lang=target_lang,
            allow_google=allow_google,
            translate_delay=translate_delay,
            lang_filter=lang_filter,
            values_en_first=values_en_first,
            report=report,
            module_name=module_dir.name,
            xml_file=xml_name,
        )

        before_keys = len(done_keys)
        errs, merged_root, ru_path = _fill_one_xml(
            module_dir,
            xml_name,
            translate_for_key=tr,
            done_keys=done_keys,
            skip_existing=skip_existing,
            library_overwrite=library_overwrite,
            string_map=string_map,
            source_lang=source_lang,
            lang_filter=lang_filter,
            values_en_first=values_en_first,
            dry_run=dry_run,
            report=report,
        )
        total_errors += errs
        n_new = len(done_keys) - before_keys
        if merged_root is not None and ru_path is not None:
            merged_by_xml[xml_name] = (merged_root, ru_path)
            translated_total += n_new
            changed_since_save += n_new
            if changed_since_save >= save_every:
                flush_all()

    if changed_since_save > 0:
        flush_all()

    module_work = (report.stats.library - stats_lib0) + (report.stats.google - stats_google0)
    lang_skip_n = report.stats.lang_skipped - lang_skipped0
    if module_work == 0 and lang_skip_n == 0:
        print(f"[ok] нечего переводить в {module_dir.name}")
    else:
        print(
            f"[done] {module_dir.name}: библиотека {report.stats.library - stats_lib0}, "
            f"Google {report.stats.google - stats_google0}"
            + (f", другой язык (пропуск): {lang_skip_n}" if lang_skip_n else "")
        )

    return 0 if total_errors == 0 else 2


def write_report(path: Path, report: SessionReport, *, meta: dict[str, Any]) -> None:
    payload = {
        "schema_version": 1,
        "summary": {
            "library": report.stats.library,
            "google": report.stats.google,
            "unchanged_skipped": report.stats.unchanged,
            "not_in_library": report.stats.not_in_library,
            "lang_skipped": report.stats.lang_skipped,
            "registered_placeholder": report.stats.registered_placeholder,
            "applied_from_library": report.stats.applied_from_library,
            "synced_to_dictionary": report.stats.synced_to_dictionary,
            "errors": report.stats.errors,
        },
        "google_translations": report.google_entries,
        "library_sample": report.library_sample,
        "meta": meta,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="values-ru: библиотека → Google; отчёт по строкам Google"
    )
    ap.add_argument("-m", "--module", action="append", dest="modules", help="Каталог модуля")
    ap.add_argument("--root", type=Path, default=None, help="Модуль (res/values) или родитель с *_src")
    ap.add_argument(
        "--library",
        type=Path,
        default=None,
        help="JSON string_map (по умолчанию en или zh-rCN по --source-lang)",
    )
    ap.add_argument(
        "--legacy-library",
        action="store_true",
        help="Дополнительно подмешать translation_library_ru.json (старая общая)",
    )
    ap.add_argument(
        "--extra-library",
        type=Path,
        action="append",
        default=[],
        help="Доп. JSON со string_map (напр. translate_functions.json)",
    )
    ap.add_argument("--source-lang", default="zh-CN")
    ap.add_argument("--target-lang", default="ru")
    ap.add_argument("--delay", type=float, default=0.2, help="Пауза после каждой строки Google")
    ap.add_argument("--save-every", type=int, default=25, help="(зарезервировано)")
    ap.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Перезаписать строки, где ru уже отличается от source",
    )
    ap.add_argument("--no-resume", action="store_true", help="Игнорировать checkpoint")
    ap.add_argument(
        "--library-only",
        action="store_true",
        help="Только библиотека, без Google",
    )
    ap.add_argument(
        "--library-overwrite",
        action="store_true",
        help="Перезаписать values-ru только там, где исходник есть в string_map; без Google",
    )
    ap.add_argument(
        "--no-lang-filter",
        action="store_true",
        help="Не пропускать строки, если язык текста в values не совпадает с --source-lang",
    )
    ap.add_argument(
        "--ensure-dictionary",
        action="store_true",
        help=(
            "Два словаря (en/zh): дописать пропуски заглушкой, обновить values-ru; "
            "Google не вызывается"
        ),
    )
    ap.add_argument(
        "--placeholder-ru",
        default=PLACEHOLDER_RU,
        help="Заглушка для новых записей в словаре (режим --ensure-dictionary)",
    )
    ap.add_argument(
        "--no-overwrite",
        action="store_true",
        help=(
            "Только с --ensure-dictionary: не перезаписывать values-ru и словарь "
            "(пропускать уже переведённые строки)"
        ),
    )
    ap.add_argument("--dry-run", action="store_true", help="Не писать XML")
    ap.add_argument(
        "--report-output",
        type=Path,
        default=TOOLS_ROOT / "reports" / "fill_values_ru_google_report.json",
    )
    ap.add_argument(
        "--strings-only",
        action="store_true",
        help="Только strings.xml (по умолчанию strings + plurals + arrays)",
    )
    ap.add_argument("--tools-dir", type=Path, default=TOOLS_ROOT)
    args = ap.parse_args()

    if args.ensure_dictionary:
        args.library_only = True

    primary_lib = (
        args.library.expanduser().resolve()
        if args.library is not None
        else _default_library_for_source(args.source_lang)
    )
    lib_paths = [primary_lib]
    if args.legacy_library and DEFAULT_LIBRARY_LEGACY.is_file():
        lib_paths.append(DEFAULT_LIBRARY_LEGACY.resolve())
    lib_paths.extend(p.resolve() for p in args.extra_library)

    if args.ensure_dictionary:
        tools_dir = args.tools_dir.resolve()
        library_paths: dict[Track, Path] = {
            "en": library_path_for_track(tools_dir, "en"),
            "zh": library_path_for_track(tools_dir, "zh"),
        }
        track_maps: dict[Track, dict[str, str]] = {
            "en": load_track_map(library_paths["en"]),
            "zh": load_track_map(library_paths["zh"]),
        }
        print(
            f"[info] --ensure-dictionary: en={len(track_maps['en'])}, "
            f"zh={len(track_maps['zh'])}, заглушка={args.placeholder_ru!r}",
            flush=True,
        )
        string_map = {}
    else:
        library_paths = {}
        track_maps = {}
        tools_dir = args.tools_dir.resolve()
        both_libs = [
            library_path_for_track(tools_dir, "en"),
            library_path_for_track(tools_dir, "zh"),
        ]
        string_map = _load_string_maps(*both_libs, *lib_paths)
        if not string_map:
            print(f"Пустая библиотека: {both_libs + lib_paths}", file=sys.stderr)
            return 1
        print(
            f"[info] string_map: {len(string_map)} записей "
            f"(en+zh словари; основная: {primary_lib.name})",
            flush=True,
        )
        print(
            "[info] подстановка по любому тексту из values / values-en / values-zh*",
            flush=True,
        )

    if args.root is not None:
        modules = _discover_modules(args.root.expanduser().resolve())
    elif args.modules:
        modules = [Path(m).expanduser().resolve() for m in args.modules]
    else:
        modules = _discover_modules(DEFAULT_ROOT.resolve())
        if modules:
            print(f"[info] --root не указан, используем {DEFAULT_ROOT}")

    if not modules:
        print("Нет модулей для обработки", file=sys.stderr)
        return 1

    if args.library_overwrite and not args.ensure_dictionary:
        args.library_only = True
        print(
            "[info] режим --library-overwrite: перезапись из словаря по точному тексту source",
            flush=True,
        )

    if args.ensure_dictionary:
        if args.no_overwrite:
            print(
                "[info] --ensure-dictionary без перезаписи: только новые ключи в словаре",
                flush=True,
            )
        else:
            print(
                "[info] --ensure-dictionary: перезапись values-ru из словаря; "
                "готовый ru в APK → перезапись словаря; Google отключён",
                flush=True,
            )
        print(
            "[info] все варианты исходника из values / values-en / values-zh*; "
            "поиск и запись в en- и zh-словари",
            flush=True,
        )

    lang_filter = not args.no_lang_filter and not args.ensure_dictionary
    if lang_filter:
        print(
            f"[info] фильтр языка: при --source-lang {args.source_lang} "
            "чужие строки (латиница в zh / иероглифы в en) не переводятся",
            flush=True,
        )
    print(
        f"[info] модулей: {len(modules)}; пауза после Google: {args.delay}s "
        "(строки из библиотеки — без паузы)",
        flush=True,
    )

    xml_files: tuple[str, ...] = ("strings.xml",) if args.strings_only else TRANSLATABLE_XML
    report = SessionReport()
    rc = 0

    for mod in modules:
        print(f"[module] {mod.name}", flush=True)
        if args.ensure_dictionary:
            overwrite = not args.no_overwrite
            fill_module_ensure_dictionary(
                mod,
                track_maps=track_maps,
                library_paths=library_paths,
                skip_existing=not args.no_skip_existing,
                overwrite_apk=overwrite,
                sync_dictionary_from_apk=overwrite,
                dry_run=args.dry_run,
                placeholder_ru=args.placeholder_ru,
                xml_files=xml_files,
                report=report,
            )
            continue
        r = fill_module(
            mod,
            string_map=string_map,
            source_lang=args.source_lang,
            target_lang=args.target_lang,
            tools_dir=args.tools_dir.resolve(),
            report=report,
            resume=not args.no_resume,
            skip_existing=not args.no_skip_existing,
            save_every=max(1, args.save_every),
            translate_delay=max(0.0, args.delay),
            library_only=args.library_only,
            library_overwrite=args.library_overwrite,
            lang_filter=lang_filter,
            dry_run=args.dry_run,
            xml_files=xml_files,
        )
        rc = max(rc, r)

    write_report(
        args.report_output.resolve(),
        report,
        meta={
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "modules": [p.name for p in modules],
            "libraries": (
                [str(p) for p in library_paths.values()]
                if args.ensure_dictionary
                else [str(p) for p in lib_paths]
            ),
            "dry_run": args.dry_run,
            "library_only": args.library_only,
            "library_overwrite": args.library_overwrite,
            "ensure_dictionary": args.ensure_dictionary,
        },
    )

    s = report.stats
    print(
        f"[report] {args.report_output}\n"
        f"  библиотека: {s.library}, Google: {s.google}, "
        f"пропущено (уже ок): {s.unchanged}, другой язык: {s.lang_skipped}, "
        f"заглушек в словарь: {s.registered_placeholder}, APK→словарь: {s.synced_to_dictionary}, "
        f"словарь→APK: {s.applied_from_library}, "
        f"ожидают перевода (нет ключа/заглушка): {s.not_in_library}, ошибок: {s.errors}"
    )
    if report.google_entries:
        print(f"  строк через Google: {len(report.google_entries)} (полный список в отчёте)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
