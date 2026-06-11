#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ищет хардкод (китайский/английский текст) в res/layout/**/*.xml и либо:
  A) --inject-values : добавляет строки в res/values/strings.xml и заменяет
     атрибуты на @string/hw_XXXX (рекомендуется).
  B) --translate-inplace : переводит атрибут прямо в layout (быстро, но
     нарушает Android-архитектуру; используйте осторожно).

Режимы запуска:
  # Только отчёт, ничего не писать:
  python3 layout/extract_layout_hardcode.py --root "/path/to/Translated" --dry-run

  # Вынести в values и перевести через библиотеку (рекомендуется):
  python3 layout/extract_layout_hardcode.py --root "/path/to/Translated" --inject-values

  # Перевести прямо в layout (быстро, без изменения values):
  python3 layout/extract_layout_hardcode.py --root "/path/to/Translated" --translate-inplace

  # Один модуль:
  python3 layout/extract_layout_hardcode.py -m "/path/to/com.deepal.launcher_src" --inject-values

Ключи для новых строк:
  По умолчанию генерируются читабельные ключи через библиотеку переводов:
    "设置" → hw_settings  (из перевода «Настройки»)
    "请输入密码" → hw_enter_password
  Если перевод не найден — числовой ключ: hw_0001, hw_0002 …
  Префикс можно изменить через --key-prefix.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT / "library"))

from library_persist import load_track_map  # noqa: E402
from source_resolve import has_cjk, skip_for_translation_library  # noqa: E402

# ---------------------------------------------------------------------------
# Атрибуты которые могут содержать видимый пользователю текст
# ---------------------------------------------------------------------------
TEXT_ATTRS = frozenset(
    {
        "android:text",
        "android:hint",
        "android:contentDescription",
        "android:title",
        "android:summary",
        "android:dialogTitle",
        "android:dialogMessage",
        "android:positiveButtonText",
        "android:negativeButtonText",
        "android:neutralButtonText",
        "app:title",
        "app:summary",
        "tools:text",  # только превью, не трогаем в inplace-режиме
    }
)
# tools:text — только репортим, никогда не пишем
READONLY_ATTRS = frozenset({"tools:text"})

# Атрибуты, которые не трогаем в --translate-inplace
INPLACE_SKIP_ATTRS = READONLY_ATTRS

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufadf]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_REF_RE = re.compile(r"^[@?]")          # @string/… ?attr/… — ссылки
_FORMAT_ONLY_RE = re.compile(r"^%[\w$]+$")  # чистый форматный placeholder
_DIGITS_ONLY_RE = re.compile(r"^\d[\d\s.,:/%-]*$")

DEFAULT_KEY_PREFIX = "hw"
NAMESPACE_ANDROID = "http://schemas.android.com/apk/res/android"
NAMESPACE_APP = "http://schemas.android.com/apk/res-auto"
NAMESPACE_TOOLS = "http://schemas.android.com/tools"

ET.register_namespace("android", NAMESPACE_ANDROID)
ET.register_namespace("app", NAMESPACE_APP)
ET.register_namespace("tools", NAMESPACE_TOOLS)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class HardcodeHit:
    module: str
    layout_file: str        # относительный путь от res/
    xml_tag: str
    attr: str
    text: str
    line: int               # приблизительно (ET не хранит номера строк)


@dataclass
class ExtractStats:
    modules_scanned: int = 0
    layout_files_scanned: int = 0
    hits_found: int = 0
    keys_new: int = 0
    keys_reused: int = 0
    values_updated: int = 0
    layouts_patched: int = 0
    translated_inplace: int = 0
    errors: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_hardcode(text: str) -> bool:
    """True если текст — хардкод, который стоит переводить."""
    s = (text or "").strip()
    if not s:
        return False
    if _REF_RE.match(s):        # @string/…, ?attr/…
        return False
    if skip_for_translation_library(s):
        return False
    if _FORMAT_ONLY_RE.match(s):
        return False
    if _DIGITS_ONLY_RE.match(s):
        return False
    # Оставляем только строки с CJK или латиницей (не чисто цифры/символы)
    return bool(_CJK_RE.search(s) or _LATIN_RE.search(s))


def _slugify(text: str) -> str:
    """Превращает русский/английский перевод в snake_case ключ."""
    # Нормализуем unicode → ASCII где возможно
    s = unicodedata.normalize("NFKD", text.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    # Оставляем только буквы, цифры и пробелы
    s = re.sub(r"[^\w\s]", " ", s, flags=re.ASCII)
    s = re.sub(r"\s+", "_", s.strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:40] if s else ""


def _make_key(
    text: str,
    string_map_en: dict[str, str],
    string_map_zh: dict[str, str],
    existing_keys: set[str],
    counter: list[int],   # mutable counter [next_n]
    prefix: str,
) -> str:
    """
    Генерирует читабельный ключ для хардкода через библиотеку переводов,
    либо числовой hw_XXXX если перевод не найден.
    """
    ru = string_map_zh.get(text) or string_map_en.get(text) or ""
    slug = _slugify(ru) if ru and ru.strip() and ru.strip() != " " else ""

    if slug:
        candidate = f"{prefix}_{slug}"
        # Если ключ уже занят другим текстом — добавляем суффикс
        base = candidate
        n = 2
        while candidate in existing_keys:
            candidate = f"{base}_{n}"
            n += 1
        return candidate

    # Числовой fallback
    while True:
        candidate = f"{prefix}_{counter[0]:04d}"
        counter[0] += 1
        if candidate not in existing_keys:
            return candidate


# ---------------------------------------------------------------------------
# XML-парсинг layout
# ---------------------------------------------------------------------------

def _iter_layout_hits(layout_path: Path, module_name: str) -> list[HardcodeHit]:
    """Возвращает все хардкоды в одном layout-файле."""
    try:
        tree = ET.parse(layout_path)
    except ET.ParseError as e:
        print(f"[warn] XML parse error {layout_path}: {e}", file=sys.stderr)
        return []

    rel = str(layout_path).replace("\\", "/")
    # Относительный путь от res/
    try:
        res_idx = rel.rindex("/res/")
        rel_from_res = rel[res_idx + 1:]
    except ValueError:
        rel_from_res = layout_path.name

    hits: list[HardcodeHit] = []
    ns_map = {
        "android": NAMESPACE_ANDROID,
        "app": NAMESPACE_APP,
        "tools": NAMESPACE_TOOLS,
    }

    for elem in tree.iter():
        tag = elem.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]

        for raw_attr, value in elem.attrib.items():
            # Нормализуем атрибут к короткому виду
            short_attr = raw_attr
            for ns_uri, ns_prefix in [
                (f"{{{NAMESPACE_ANDROID}}}", "android:"),
                (f"{{{NAMESPACE_APP}}}", "app:"),
                (f"{{{NAMESPACE_TOOLS}}}", "tools:"),
            ]:
                if raw_attr.startswith(ns_uri):
                    short_attr = ns_prefix + raw_attr[len(ns_uri):]
                    break

            if short_attr not in TEXT_ATTRS:
                continue
            if not _is_hardcode(value):
                continue

            hits.append(
                HardcodeHit(
                    module=module_name,
                    layout_file=rel_from_res,
                    xml_tag=tag,
                    attr=short_attr,
                    text=value,
                    line=0,
                )
            )

    return hits


# ---------------------------------------------------------------------------
# values/strings.xml — чтение и запись
# ---------------------------------------------------------------------------

def _load_strings_xml(path: Path) -> tuple[ET.Element | None, dict[str, str]]:
    """Возвращает (root, {name: text})."""
    if not path.is_file():
        return None, {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        print(f"[warn] XML parse error {path}: {e}", file=sys.stderr)
        return None, {}
    mapping: dict[str, str] = {}
    for el in root:
        if el.tag == "string":
            name = el.attrib.get("name")
            if name:
                mapping[name] = el.text or ""
    return root, mapping


def _save_strings_xml(path: Path, root: ET.Element) -> None:
    ET.indent(root, space="    ")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=False)


def _ensure_resources_root(path: Path) -> ET.Element:
    """Создаёт пустой <resources> если файл не существует."""
    if path.is_file():
        root, _ = _load_strings_xml(path)
        if root is not None:
            return root
    root = ET.Element("resources")
    return root


# ---------------------------------------------------------------------------
# Inject-values mode
# ---------------------------------------------------------------------------

def _inject_into_values(
    module_dir: Path,
    hits: list[HardcodeHit],
    string_map_en: dict[str, str],
    string_map_zh: dict[str, str],
    *,
    key_prefix: str,
    dry_run: bool,
    stats: ExtractStats,
) -> dict[str, str]:
    """
    Добавляет строки в res/values/strings.xml.
    Возвращает {text → key} для последующей замены в layout.
    """
    values_dir = module_dir / "res" / "values"
    strings_path = values_dir / "strings.xml"

    root = _ensure_resources_root(strings_path)
    _, existing_by_name = _load_strings_xml(strings_path)

    # Инвертированный индекс: text → существующий ключ
    text_to_key: dict[str, str] = {v: k for k, v in existing_by_name.items()}
    # Множество уже занятых ключей (включая hw_*)
    existing_keys: set[str] = set(existing_by_name.keys())

    counter = [1]
    result: dict[str, str] = {}     # text → key (новые + переиспользованные)

    unique_texts = dict.fromkeys(h.text for h in hits)  # сохраняем порядок

    for text in unique_texts:
        if text in text_to_key:
            key = text_to_key[text]
            stats.keys_reused += 1
            print(f"  [reuse] уже есть: {key!r} = {text!r}")
        else:
            key = _make_key(
                text, string_map_en, string_map_zh, existing_keys, counter, key_prefix
            )
            existing_keys.add(key)
            text_to_key[text] = key
            stats.keys_new += 1
            print(f"  [new]   {key!r} ← {text!r}")

            if not dry_run:
                el = ET.SubElement(root, "string", name=key)
                el.text = text

        result[text] = key

    if stats.keys_new > 0 and not dry_run:
        _save_strings_xml(strings_path, root)
        print(f"  [write] {strings_path} (+{stats.keys_new} строк)")
        stats.values_updated += 1

    return result


# ---------------------------------------------------------------------------
# Patching layouts
# ---------------------------------------------------------------------------

_NS_SHORT = {
    NAMESPACE_ANDROID: "android",
    NAMESPACE_APP: "app",
    NAMESPACE_TOOLS: "tools",
}


def _short_to_clark(attr: str) -> str:
    """'android:text' → '{http://...android...}text'"""
    for ns_uri, prefix in [
        (NAMESPACE_ANDROID, "android:"),
        (NAMESPACE_APP, "app:"),
        (NAMESPACE_TOOLS, "tools:"),
    ]:
        if attr.startswith(prefix):
            return f"{{{ns_uri}}}{attr[len(prefix):]}"
    return attr


def _patch_layout_inject(
    layout_path: Path,
    text_to_key: dict[str, str],
    *,
    dry_run: bool,
    stats: ExtractStats,
) -> int:
    """Заменяет значения атрибутов на @string/key в одном layout-файле."""
    try:
        tree = ET.parse(layout_path)
    except ET.ParseError:
        return 0

    changed = 0
    for elem in tree.iter():
        for raw_attr in list(elem.attrib):
            value = elem.attrib[raw_attr]
            if value not in text_to_key:
                continue

            # Нормализуем к короткому виду чтобы проверить READONLY_ATTRS
            short_attr = raw_attr
            for ns_uri, prefix in [
                (f"{{{NAMESPACE_ANDROID}}}", "android:"),
                (f"{{{NAMESPACE_APP}}}", "app:"),
                (f"{{{NAMESPACE_TOOLS}}}", "tools:"),
            ]:
                if raw_attr.startswith(ns_uri):
                    short_attr = prefix + raw_attr[len(ns_uri):]
                    break

            if short_attr in READONLY_ATTRS:
                continue

            key = text_to_key[value]
            if not dry_run:
                elem.attrib[raw_attr] = f"@string/{key}"
            changed += 1

    if changed > 0:
        if not dry_run:
            ET.indent(tree.getroot(), space="    ")
            with open(layout_path, "wb") as f:
                f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
            tree.write(layout_path, encoding="utf-8", xml_declaration=False)
        stats.layouts_patched += 1
        print(f"  [patch] {layout_path.name} ({changed} замен)")

    return changed


def _patch_layout_inplace(
    layout_path: Path,
    hits_for_file: list[HardcodeHit],
    string_map_en: dict[str, str],
    string_map_zh: dict[str, str],
    *,
    dry_run: bool,
    stats: ExtractStats,
) -> int:
    """Переводит текст прямо в атрибуте layout, без изменения values."""
    try:
        tree = ET.parse(layout_path)
    except ET.ParseError:
        return 0

    # Собираем {(tag_path_or_attr, text) → ru} из hits
    texts_needed = {h.text for h in hits_for_file if h.attr not in INPLACE_SKIP_ATTRS}
    text_to_ru: dict[str, str] = {}
    for text in texts_needed:
        ru = string_map_zh.get(text) or string_map_en.get(text) or ""
        if ru and ru.strip() and ru.strip() != " ":
            text_to_ru[text] = ru

    changed = 0
    for elem in tree.iter():
        for raw_attr in list(elem.attrib):
            value = elem.attrib[raw_attr]
            if value not in text_to_ru:
                continue

            short_attr = raw_attr
            for ns_uri, prefix in [
                (f"{{{NAMESPACE_ANDROID}}}", "android:"),
                (f"{{{NAMESPACE_APP}}}", "app:"),
                (f"{{{NAMESPACE_TOOLS}}}", "tools:"),
            ]:
                if raw_attr.startswith(ns_uri):
                    short_attr = prefix + raw_attr[len(ns_uri):]
                    break

            if short_attr in INPLACE_SKIP_ATTRS:
                continue

            if not dry_run:
                elem.attrib[raw_attr] = text_to_ru[value]
            changed += 1

    if changed > 0:
        if not dry_run:
            ET.indent(tree.getroot(), space="    ")
            with open(layout_path, "wb") as f:
                f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
            tree.write(layout_path, encoding="utf-8", xml_declaration=False)
        stats.translated_inplace += changed
        print(f"  [inplace] {layout_path.name} ({changed} переводов)")

    return changed


# ---------------------------------------------------------------------------
# Сканирование модуля
# ---------------------------------------------------------------------------

def _find_layout_dirs(module_dir: Path) -> list[Path]:
    """Все res/layout*/ папки в модуле (layout, layout-land, layout-v21…)."""
    res = module_dir / "res"
    if not res.is_dir():
        return []
    return [d for d in res.iterdir() if d.is_dir() and d.name.startswith("layout")]


def process_module(
    module_dir: Path,
    string_map_en: dict[str, str],
    string_map_zh: dict[str, str],
    *,
    mode: str,          # "report" | "inject" | "inplace"
    key_prefix: str,
    dry_run: bool,
    stats: ExtractStats,
) -> list[HardcodeHit]:
    layout_dirs = _find_layout_dirs(module_dir)
    if not layout_dirs:
        return []

    all_hits: list[HardcodeHit] = []
    layout_files: list[Path] = []
    for ld in layout_dirs:
        layout_files.extend(ld.glob("*.xml"))

    if not layout_files:
        return []

    stats.modules_scanned += 1
    print(f"[module] {module_dir.name} — layout-файлов: {len(layout_files)}")

    hits_by_file: dict[str, list[HardcodeHit]] = {}
    for lf in sorted(layout_files):
        stats.layout_files_scanned += 1
        hits = _iter_layout_hits(lf, module_dir.name)
        if hits:
            hits_by_file[str(lf)] = hits
            all_hits.extend(hits)
            stats.hits_found += len(hits)

    if not all_hits:
        print(f"  [ok] хардкода не найдено")
        return []

    for lf_str, hits in hits_by_file.items():
        for h in hits:
            print(
                f"  [hit] {h.layout_file}  <{h.xml_tag}> {h.attr}={h.text!r}"
            )

    if mode == "report":
        return all_hits

    if mode == "inject":
        text_to_key = _inject_into_values(
            module_dir,
            all_hits,
            string_map_en,
            string_map_zh,
            key_prefix=key_prefix,
            dry_run=dry_run,
            stats=stats,
        )
        for lf_str, hits in hits_by_file.items():
            _patch_layout_inject(
                Path(lf_str),
                text_to_key,
                dry_run=dry_run,
                stats=stats,
            )

    elif mode == "inplace":
        for lf_str, hits in hits_by_file.items():
            _patch_layout_inplace(
                Path(lf_str),
                hits,
                string_map_en,
                string_map_zh,
                dry_run=dry_run,
                stats=stats,
            )

    return all_hits


# ---------------------------------------------------------------------------
# Обнаружение модулей (аналогично другим скриптам)
# ---------------------------------------------------------------------------

def _discover_modules(root: Path) -> list[Path]:
    if (root / "res").is_dir():
        return [root]
    return sorted(
        [
            d
            for d in root.iterdir()
            if d.is_dir() and (d / "res").is_dir()
        ]
    )


# ---------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------

def _write_report(path: Path, hits: list[HardcodeHit], stats: ExtractStats) -> None:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "summary": {
            "modules_scanned": stats.modules_scanned,
            "layout_files_scanned": stats.layout_files_scanned,
            "hits_found": stats.hits_found,
            "keys_new": stats.keys_new,
            "keys_reused": stats.keys_reused,
            "values_updated": stats.values_updated,
            "layouts_patched": stats.layouts_patched,
            "translated_inplace": stats.translated_inplace,
        },
        "hits": [
            {
                "module": h.module,
                "layout_file": h.layout_file,
                "tag": h.xml_tag,
                "attr": h.attr,
                "text": h.text,
            }
            for h in hits
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[report] {path}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    tools_root = Path(__file__).resolve().parent.parent
    reports_dir = tools_root / "reports"

    ap = argparse.ArgumentParser(
        description="Поиск и перевод хардкода в res/layout/**/*.xml"
    )
    ap.add_argument(
        "-m", "--module",
        action="append",
        dest="modules",
        metavar="DIR",
        help="Каталог одного модуля (можно несколько -m)",
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Папка со всеми *_src модулями или один модуль",
    )

    mode_group = ap.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--inject-values",
        action="store_true",
        help=(
            "Добавить хардкод в res/values/strings.xml и заменить на @string/key "
            "(рекомендуется)"
        ),
    )
    mode_group.add_argument(
        "--translate-inplace",
        action="store_true",
        help="Перевести текст прямо в атрибуте layout (без изменения values)",
    )

    ap.add_argument(
        "--key-prefix",
        default=DEFAULT_KEY_PREFIX,
        help=f"Префикс для новых ключей (по умолчанию: {DEFAULT_KEY_PREFIX!r})",
    )
    ap.add_argument(
        "--library-en",
        type=Path,
        default=None,
        help="Путь к en-словарю (по умолчанию: data/dictionaries/translation_library_ru_en.json)",
    )
    ap.add_argument(
        "--library-zh",
        type=Path,
        default=None,
        help="Путь к zh-словарю (по умолчанию: translation_library_ru_zh-rCN.json)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать что будет сделано, ничего не писать",
    )
    ap.add_argument(
        "--report-output",
        type=Path,
        default=reports_dir / "layout_hardcode_report.json",
        help="Путь к JSON-отчёту",
    )
    ap.add_argument(
        "--no-report",
        action="store_true",
        help="Не писать JSON-отчёт",
    )
    args = ap.parse_args()

    # Режим
    if args.inject_values:
        mode = "inject"
    elif args.translate_inplace:
        mode = "inplace"
    else:
        mode = "report"

    if mode == "report":
        print("[info] режим: только отчёт (используйте --inject-values или --translate-inplace для изменений)")
    elif mode == "inject":
        print("[info] режим: inject-values (хардкод → strings.xml + @string/key в layout)")
    else:
        print("[info] режим: translate-inplace (перевод прямо в атрибуте layout)")

    if args.dry_run:
        print("[info] --dry-run: файлы не будут изменены")

    # Загрузка словарей
    dict_dir = tools_root / "data" / "dictionaries"
    lib_en_path = args.library_en or (dict_dir / "translation_library_ru_en.json")
    lib_zh_path = args.library_zh or (dict_dir / "translation_library_ru_zh-rCN.json")

    string_map_en: dict[str, str] = {}
    string_map_zh: dict[str, str] = {}

    if lib_en_path.is_file():
        string_map_en = load_track_map(lib_en_path)
        print(f"[info] en-словарь: {len(string_map_en)} записей ({lib_en_path.name})")
    else:
        print(f"[warn] en-словарь не найден: {lib_en_path}", file=sys.stderr)

    if lib_zh_path.is_file():
        string_map_zh = load_track_map(lib_zh_path)
        print(f"[info] zh-словарь: {len(string_map_zh)} записей ({lib_zh_path.name})")
    else:
        print(f"[warn] zh-словарь не найден: {lib_zh_path}", file=sys.stderr)

    # Модули
    if args.root is not None:
        modules = _discover_modules(args.root.expanduser().resolve())
    elif args.modules:
        modules = [Path(m).expanduser().resolve() for m in args.modules]
    else:
        print("Укажите --root или -m", file=sys.stderr)
        return 1

    if not modules:
        print("Нет модулей с res/", file=sys.stderr)
        return 1

    print(f"[info] модулей: {len(modules)}")

    stats = ExtractStats()
    all_hits: list[HardcodeHit] = []

    for mod in modules:
        hits = process_module(
            mod,
            string_map_en,
            string_map_zh,
            mode=mode,
            key_prefix=args.key_prefix,
            dry_run=args.dry_run,
            stats=stats,
        )
        all_hits.extend(hits)

    # Итог
    print(
        f"\n[done] модулей со layout: {stats.modules_scanned}, "
        f"файлов: {stats.layout_files_scanned}, "
        f"хардкодов: {stats.hits_found}"
    )
    if mode == "inject":
        print(
            f"  ключей новых: {stats.keys_new}, "
            f"переиспользовано: {stats.keys_reused}, "
            f"values обновлено: {stats.values_updated}, "
            f"layout пропатчено: {stats.layouts_patched}"
        )
        if stats.keys_new > 0 and not args.dry_run:
            print(
                "\n[next] запустите scripts/fill_values_ru_from_library.py --library-only "
                "чтобы заполнить values-ru для новых ключей"
            )
    elif mode == "inplace":
        print(f"  переведено атрибутов: {stats.translated_inplace}")

    if not args.no_report:
        _write_report(args.report_output.resolve(), all_hits, stats)

    return 0


if __name__ == "__main__":
    sys.exit(main())
