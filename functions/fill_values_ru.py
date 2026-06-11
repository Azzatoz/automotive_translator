#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перевод assets/total_functions.json (голосовые функции) и merge translate_functions.json.

Для res/values-ru/strings.xml используйте главный скрипт в корне tools:
  fill_values_ru_from_library.py

Дополнительно: перевод assets/total_functions.json через tools/functions/translate_functions.json
  (--total-functions / --only-total-functions): собирает уникальные строки с CJK из JSON,
  переводит тем же GoogleTranslator, дополняет string_map, затем merge в оба APK (Hive + SceneBlock).

Особенности:
  — периодически сохраняет values-ru и checkpoint (по умолчанию каждые 25 строк);
  — checkpoint: tools/checkpoints/<имя_модуля>_values_ru.json;
  — для functions: tools/checkpoints/total_functions_string_map_ru.json;
  — плейсхолдеры %s, %1$d, \\n и т.п. перед переводом заменяются маркерами и восстанавливаются;
  — при обрыве можно снова запустить с теми же аргументами — продолжит с checkpoint.

Зависимость перевода (опционально):
  pip install deep-translator

Без deep-translator: используйте --copy-source (копия исходного текста) или установите пакет.

Пример:
  python3 tools/fill_values_ru.py \\
    --module "/path/to/com_android_launcher3__AndesLauncher" \\
    --source-lang zh-CN --target-lang ru --save-every 25

Только один модуль (медиа):
  bash AndesMedia_src/scripts/run_fill_values_ru.sh --source-lang zh-CN --delay 0.2

Несколько модулей:
  python3 tools/fill_values_ru.py -m App1 -m App2 --save-every 15

Только словарь для total_functions + запись в assets:
  python3 tools/fill_values_ru.py --only-total-functions --source-lang zh-CN --sync-functions-assets --report-functions
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None  # type: ignore[misc, assignment]

# Rest 4.1.1/Translated — модули APK
REST_ROOT = Path(__file__).resolve().parents[2]
TRANSLATED_ROOT = REST_ROOT / "Translated"
DEFAULT_MODULES = [
    TRANSLATED_ROOT / "AdsHmi_src",
    TRANSLATED_ROOT / "AndesHive_src",
    TRANSLATED_ROOT / "AndesMedia_src",
    TRANSLATED_ROOT / "AndesSceneBlock_src",
    TRANSLATED_ROOT / "AndesSceneMode_src",
]

DEFAULT_FUNCTIONS_BASE = TRANSLATED_ROOT / "AndesHive_src" / "assets" / "total_functions.json"
DEFAULT_FUNCTIONS_TRANSLATE = Path(__file__).resolve().parent / "translate_functions.json"
FUNCTIONS_HIVE_OUT = TRANSLATED_ROOT / "AndesHive_src" / "assets" / "total_functions.json"
FUNCTIONS_SCENEBLOCK_OUT = TRANSLATED_ROOT / "AndesSceneBlock_src" / "assets" / "total_functions.json"

# Строки с хотя бы одним символом CJK — кандидаты на перевод в total_functions.json
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufadf]")

# Маркеры для подстановок вида %s, %1$d, %d — не переводим
_PLACEHOLDER_PATTERN = re.compile(
    r"(%(?:\d+\$)?(?:s|d|u|f|x|X|o|c|e|E|g|G|h|H))"
)
_EXTRA_ESCAPES = re.compile(r"(\\n|\\'|\\\"|\\\\)")


def _protect_specials(text: str) -> tuple[str, dict[str, str]]:
    """Заменяет плейсхолдеры и простые escape-последовательности на токены."""
    mapping: dict[str, str] = {}
    out = text
    idx = 0

    def repl_token(m: re.Match[str]) -> str:
        nonlocal idx
        key = f"⟦PT{idx}⟧"
        mapping[key] = m.group(1)
        idx += 1
        return key

    out = _PLACEHOLDER_PATTERN.sub(repl_token, out)
    out = _EXTRA_ESCAPES.sub(repl_token, out)
    return out, mapping


def _restore_specials(text: str, mapping: dict[str, str]) -> str:
    for k, v in mapping.items():
        text = text.replace(k, v)
    return text


def _translate_with_google(text: str, source: str, target: str) -> str:
    if GoogleTranslator is None:
        raise RuntimeError("Установите: pip install deep-translator")
    prot, mp = _protect_specials(text)
    tr = GoogleTranslator(source=source, target=target).translate(prot)
    if not tr:
        return text
    return _restore_specials(tr.strip(), mp)


def _hash_utf8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# --- assets/total_functions.json: merge + перевод string_map ---


def _collect_strings_from_json(obj: Any, out: list[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_strings_from_json(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_strings_from_json(item, out)
    elif isinstance(obj, str):
        out.append(obj)


def _apply_string_map_inplace(obj: Any, sm: dict[str, str]) -> None:
    if not sm:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                if v in sm:
                    obj[k] = sm[v]
                else:
                    _apply_string_map_inplace(v, sm)
            else:
                _apply_string_map_inplace(v, sm)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                if item in sm:
                    obj[i] = sm[item]
                else:
                    _apply_string_map_inplace(item, sm)
            else:
                _apply_string_map_inplace(item, sm)


def _apply_meta_overrides_inplace(data: list[Any], meta_overrides: dict[str, Any]) -> None:
    if not meta_overrides:
        return
    for group in data:
        if not isinstance(group, dict):
            continue
        for fn in group.get("functions") or []:
            if not isinstance(fn, dict):
                continue
            mid = fn.get("meta_id")
            if mid is None:
                continue
            ov = meta_overrides.get(str(mid))
            if not ov:
                continue
            impl_by_id = ov.get("implements_by_id")
            for key, val in ov.items():
                if key == "implements_by_id":
                    continue
                fn[key] = val
            if not impl_by_id:
                continue
            for imp in fn.get("implements") or []:
                if not isinstance(imp, dict):
                    continue
                iid = imp.get("id")
                if iid is None:
                    continue
                patch = impl_by_id.get(str(iid))
                if not patch:
                    continue
                for ik, iv in patch.items():
                    imp[ik] = iv


def merge_functions_payload(base: Any, translate_cfg: dict[str, Any]) -> Any:
    """Копия базы + string_map + meta_overrides (как merge_total_functions_ru.merge_payload)."""
    data = copy.deepcopy(base)
    sm = translate_cfg.get("string_map") or {}
    if not isinstance(sm, dict):
        raise ValueError("string_map должен быть объектом")
    meta_ov = translate_cfg.get("meta_overrides") or {}
    if not isinstance(meta_ov, dict):
        raise ValueError("meta_overrides должен быть объектом")

    sm_norm = {str(k): v for k, v in sm.items()}
    meta_norm = {str(k): v for k, v in meta_ov.items()}
    if isinstance(data, list):
        _apply_string_map_inplace(data, sm_norm)
        _apply_meta_overrides_inplace(data, meta_norm)
    else:
        _apply_string_map_inplace(data, sm_norm)
    return data


def count_cjk_in_functions_json(obj: Any) -> tuple[int, int]:
    strings: list[str] = []
    _collect_strings_from_json(obj, strings)
    cjk_chars = 0
    cjk_lines = 0
    for s in strings:
        n = len(_CJK_RE.findall(s))
        if n:
            cjk_chars += n
            cjk_lines += 1
    return cjk_chars, cjk_lines


def _unique_cjk_strings_from_base(base_data: Any) -> list[str]:
    raw: list[str] = []
    _collect_strings_from_json(base_data, raw)
    seen: set[str] = set()
    out: list[str] = []
    for s in raw:
        if not s or not _CJK_RE.search(s):
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    out.sort()
    return out


def _functions_string_map_checkpoint_path(tools_dir: Path) -> Path:
    d = tools_dir / "checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return d / "total_functions_string_map_ru.json"


def _load_functions_string_checkpoint(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("done_hashes", []))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_functions_string_checkpoint(path: Path, done_hashes: set[str]) -> None:
    payload = {
        "done_hashes": sorted(done_hashes),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_translate_functions_json(
    path: Path,
    *,
    string_map: dict[str, str],
    meta_overrides: dict[str, Any],
    schema_version: int,
) -> None:
    cfg_out = {
        "schema_version": schema_version,
        "string_map": dict(sorted(string_map.items(), key=lambda kv: kv[0])),
        "meta_overrides": meta_overrides,
    }
    path.write_text(json.dumps(cfg_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fill_total_functions_string_map(
    *,
    tools_dir: Path,
    source_lang: str,
    target_lang: str,
    save_every: int,
    copy_source: bool,
    skip_existing: bool,
    resume: bool,
    translate_delay: float,
    sync_assets: bool,
    report: bool,
    json_indent: int,
    functions_base: Path,
    functions_translate: Path,
    functions_max: int | None,
) -> int:
    """
    Переводит уникальные строки с CJK из total_functions.json → string_map в translate_functions.json,
    затем merge и опционально запись в assets обоих приложений.
    """
    if not functions_base.is_file():
        print(f"[functions] нет базового файла: {functions_base}", file=sys.stderr)
        return 1

    base_data = json.loads(functions_base.read_text(encoding="utf-8"))

    if functions_translate.is_file():
        cfg = json.loads(functions_translate.read_text(encoding="utf-8"))
    else:
        cfg = {"schema_version": 1, "string_map": {}, "meta_overrides": {}}

    schema_version = int(cfg.get("schema_version", 1))
    string_map: dict[str, str] = dict(cfg.get("string_map") or {})
    meta_overrides: dict[str, Any] = dict(cfg.get("meta_overrides") or {})

    cp_path = _functions_string_map_checkpoint_path(tools_dir)
    done_hashes = _load_functions_string_checkpoint(cp_path) if resume else set()

    def translate_fn(text: str) -> str:
        if copy_source:
            return text
        return _translate_with_google(text, source_lang, target_lang)

    all_cjk = _unique_cjk_strings_from_base(base_data)
    candidates = all_cjk
    if functions_max is not None:
        candidates = all_cjk[: max(0, functions_max)]

    pending: list[str] = []
    for s in candidates:
        h = _hash_utf8(s)
        if resume and h in done_hashes:
            continue
        if skip_existing and s in string_map:
            prev = (string_map[s] or "").strip()
            if prev and prev != s.strip():
                continue
        pending.append(s)

    total = len(pending)
    print(f"[functions] уникальных строк с CJK: {len(all_cjk)}, к переводу: {total}")

    errors = 0
    changed_since_save = 0

    def flush_maps() -> None:
        nonlocal changed_since_save
        _save_translate_functions_json(
            functions_translate,
            string_map=string_map,
            meta_overrides=meta_overrides,
            schema_version=schema_version,
        )
        _save_functions_string_checkpoint(cp_path, done_hashes)
        print(
            f"[functions save] {functions_translate} (+ checkpoint), "
            f"строк в string_map: {len(string_map)}, хешей в checkpoint: {len(done_hashes)}"
        )
        changed_since_save = 0

    for idx, s in enumerate(pending, 1):
        try:
            ru = translate_fn(s)
            string_map[s] = ru if ru else s
            done_hashes.add(_hash_utf8(s))
        except Exception as e:  # noqa: BLE001
            print(f"[functions err] строка #{idx}: {e}", file=sys.stderr)
            errors += 1
            continue

        changed_since_save += 1
        print(f"[functions {idx}/{total}] OK hash={_hash_utf8(s)[:12]}…")
        if not copy_source and translate_delay > 0:
            time.sleep(translate_delay)
        if changed_since_save >= save_every:
            flush_maps()

    if changed_since_save > 0 or total == 0:
        flush_maps()

    merged = merge_functions_payload(base_data, {"string_map": string_map, "meta_overrides": meta_overrides})
    out_json = json.dumps(merged, ensure_ascii=False, indent=json_indent) + "\n"

    if sync_assets:
        for p in (FUNCTIONS_HIVE_OUT, FUNCTIONS_SCENEBLOCK_OUT):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(out_json, encoding="utf-8")
            print(f"[functions write] {p}")
        if FUNCTIONS_HIVE_OUT.read_bytes() == FUNCTIONS_SCENEBLOCK_OUT.read_bytes():
            print("[functions ok] оба assets/total_functions.json идентичны")
        else:
            print("[functions err] файлы различаются", file=sys.stderr)
            return 2

    if report:
        cc, nn = count_cjk_in_functions_json(merged)
        print(f"[functions report] CJK символов в строках: {cc}; строк с CJK: {nn}")

    return 0 if errors == 0 else 2


def merge_total_functions_cli() -> int:
    """CLI: merge translate_functions.json → total_functions.json без перевода strings."""
    ap = argparse.ArgumentParser(description="Подстановка русского в total_functions.json (merge без перевода)")
    ap.add_argument("--base", type=Path, default=DEFAULT_FUNCTIONS_BASE)
    ap.add_argument("--translate", type=Path, default=DEFAULT_FUNCTIONS_TRANSLATE)
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--sync-apps", action="store_true")
    ap.add_argument("--indent", type=int, default=2)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.base.is_file():
        print(f"Нет базового файла: {args.base}", file=sys.stderr)
        return 1
    if not args.translate.is_file():
        print(f"Нет файла перевода: {args.translate}", file=sys.stderr)
        return 1

    base_data = json.loads(args.base.read_text(encoding="utf-8"))
    cfg = json.loads(args.translate.read_text(encoding="utf-8"))
    merged = merge_functions_payload(base_data, cfg)
    report_lines: list[str] = []
    if args.report:
        cjk_c, cjk_n = count_cjk_in_functions_json(merged)
        report_lines.append(f"CJK символов в строковых значениях: {cjk_c}")
        report_lines.append(f"Строковых значений с CJK: {cjk_n}")

    out_json = json.dumps(merged, ensure_ascii=False, indent=args.indent) + "\n"

    if args.dry_run:
        if report_lines:
            print("\n".join(report_lines))
        print("[dry-run] файлы не записаны")
        return 0

    targets: list[Path] = []
    if args.output is not None:
        targets.append(args.output)
    if args.sync_apps:
        targets.extend([FUNCTIONS_HIVE_OUT, FUNCTIONS_SCENEBLOCK_OUT])

    if not targets:
        print(out_json, end="")
        if report_lines:
            print("\n".join(report_lines), file=sys.stderr)
        return 0

    for p in targets:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out_json, encoding="utf-8")
        print(f"[write] {p}")

    if args.sync_apps and len(targets) >= 2:
        if FUNCTIONS_HIVE_OUT.read_bytes() == FUNCTIONS_SCENEBLOCK_OUT.read_bytes():
            print("[ok] AndesHive_src и AndesSceneBlock_src assets/total_functions.json идентичны")
        else:
            print("[err] файлы после записи различаются", file=sys.stderr)
            return 2

    if report_lines:
        print("\n".join(report_lines))

    return 0


def _checkpoint_path(module_dir: Path, tools_dir: Path) -> Path:
    safe = module_dir.name.replace("/", "_")
    d = tools_dir / "checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}_values_ru.json"


def _load_checkpoint(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("done_keys", []))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_checkpoint(path: Path, done_keys: set[str], meta: dict[str, Any]) -> None:
    payload = {
        "done_keys": sorted(done_keys),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **meta,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _deep_copy_el(el: ET.Element) -> ET.Element:
    c = ET.Element(el.tag, el.attrib)
    if el.text and el.text.strip():
        c.text = el.text
    for sub in el:
        c.append(_deep_copy_el(sub))
        if sub.tail:
            c[-1].tail = sub.tail
    if el.tail:
        c.tail = el.tail
    return c


def _values_ru_never_override(name: str) -> bool:
    """
    Ключи с PEM/сертификатами, AGC, корневым ключом БД, отпечатками — не брать из values-ru
    и не ставить в очередь перевода: всегда как в res/values/strings.xml (fallback локали).
    """
    if name in (
        "ag_sdk_cbg_root",
        "rk",
        "tasktransfer_whitelist_authentication",
        "fa_auth_text",
    ):
        return True
    return name.startswith("agc_")


def _collect_string_like_keys(root: ET.Element) -> dict[tuple[str, str], list[ET.Element]]:
    """
    Ключ (tag, name) -> список элементов (для plurals один name — один узел).
    """
    out: dict[tuple[str, str], list[ET.Element]] = {}
    for el in root:
        name = el.attrib.get("name")
        if not name:
            continue
        key = (el.tag, name)
        out.setdefault(key, []).append(el)
    return out


def _find_item_quantity(plurals_el: ET.Element, quantity: str) -> ET.Element | None:
    for it in plurals_el.findall("item"):
        if it.attrib.get("quantity") == quantity:
            return it
    return None


def _should_skip_filled_ru(
    skip_existing: bool,
    ru_text: str | None,
    default_text: str | None,
) -> bool:
    """
    При skip_existing пропускаем только строку, которая уже отличается от исходника
    (считаем её переведённой). Если ru совпадает с values/strings.xml — это копия
    после сбоя перевода; такие снова ставим в очередь.
    """
    if not skip_existing:
        return False
    ru_s = (ru_text or "").strip()
    if not ru_s:
        return False
    def_s = (default_text or "").strip()
    if def_s and ru_s == def_s:
        return False
    return True


def _merge_translation(
    default_el: ET.Element,
    ru_el: ET.Element | None,
    *,
    done_keys: set[str],
    key_name: str,
    translate_fn,
    copy_source: bool,
    skip_existing_ru: bool,
) -> tuple[bool, str | None]:
    """
    Возвращает (changed, error_message).
    key_name = name для string; для plurals используем name с суффиксом /quantity= и т.д. в caller.
    """
    if skip_existing_ru and ru_el is not None and ru_el.text and ru_el.text.strip():
        return False, None

    src_text = default_el.text or ""
    if not src_text.strip():
        return False, None

    if copy_source:
        new_text = src_text
    else:
        try:
            new_text = translate_fn(src_text)
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    if ru_el is None:
        return False, "internal: ru_el required for update"
    ru_el.text = new_text
    done_keys.add(key_name)
    return True, None


def fill_module(
    module_dir: Path,
    *,
    source_lang: str,
    target_lang: str,
    save_every: int,
    copy_source: bool,
    skip_existing: bool,
    tools_dir: Path,
    resume: bool,
    translate_delay: float,
) -> int:
    values_default = module_dir / "res" / "values" / "strings.xml"
    values_ru_path = module_dir / "res" / "values-ru" / "strings.xml"
    if not values_default.is_file():
        print(f"[skip] нет файла: {values_default}", file=sys.stderr)
        return 1

    cp_path = _checkpoint_path(module_dir, tools_dir)
    done_keys: set[str] = _load_checkpoint(cp_path) if resume else set()

    def translate_fn(text: str) -> str:
        if copy_source:
            return text
        return _translate_with_google(text, source_lang, target_lang)

    tree_def = ET.parse(values_default)
    root_def = tree_def.getroot()

    if values_ru_path.is_file():
        tree_ru = ET.parse(values_ru_path)
        root_ru = tree_ru.getroot()
    else:
        values_ru_path.parent.mkdir(parents=True, exist_ok=True)
        tree_ru = ET.ElementTree(ET.Element("resources"))
        root_ru = tree_ru.getroot()

    ru_by_key = _collect_string_like_keys(root_ru)

    # Строим объединённое дерево: база — структура default; текст берём из ru где уже есть
    merged_root = ET.Element("resources")
    pending_merges: list[tuple[str, ET.Element, ET.Element | None]] = []

    for child in root_def:
        name = child.attrib.get("name")
        if not name:
            merged_root.append(_deep_copy_el(child))
            continue

        key = (child.tag, name)
        ru_match = ru_by_key.get(key)
        ru_node = ru_match[0] if ru_match else None

        if child.tag == "string":
            new_el = ET.Element("string", child.attrib)
            if _values_ru_never_override(name):
                new_el.text = child.text or ""
            else:
                new_el.text = (ru_node.text if ru_node is not None else None) or child.text or ""
            merged_root.append(new_el)
            sk = name
            if sk in done_keys:
                continue
            if _values_ru_never_override(name):
                continue
            if _should_skip_filled_ru(
                skip_existing, ru_node.text if ru_node is not None else None, child.text
            ):
                continue
            pending_merges.append((sk, child, new_el))

        elif child.tag == "plurals":
            new_pl = ET.Element("plurals", child.attrib)
            for item in child.findall("item"):
                q = item.attrib.get("quantity", "")
                ru_item = None
                if ru_node is not None:
                    ru_item = _find_item_quantity(ru_node, q)
                ni = ET.Element("item", item.attrib)
                ni.text = (ru_item.text if ru_item is not None else None) or item.text or ""
                new_pl.append(ni)
            merged_root.append(new_pl)
            for item in child.findall("item"):
                q = item.attrib.get("quantity", "")
                sk = f"{name}#/quantity={q}"
                if sk in done_keys:
                    continue
                ru_item = None
                if ru_node is not None:
                    ru_item = _find_item_quantity(ru_node, q)
                src_it = _find_item_quantity(child, q)
                tgt_it = _find_item_quantity(new_pl, q)
                if src_it is None or tgt_it is None:
                    continue
                if _should_skip_filled_ru(
                    skip_existing,
                    ru_item.text if ru_item is not None else None,
                    src_it.text,
                ):
                    continue
                pending_merges.append((sk, src_it, tgt_it))

        elif child.tag == "string-array":
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
                sk = f"{name}#[{i}]"
                if sk in done_keys:
                    continue
                tgt_it = new_arr.findall("item")[i]
                ru_it_text = ru_items[i].text if i < len(ru_items) else None
                if _should_skip_filled_ru(skip_existing, ru_it_text, item.text):
                    continue
                pending_merges.append((sk, item, tgt_it))
        else:
            merged_root.append(_deep_copy_el(child))

    changed_since_save = 0
    errors = 0

    def flush_tree() -> None:
        nonlocal changed_since_save
        ET.indent(merged_root, space="    ")
        values_ru_path.parent.mkdir(parents=True, exist_ok=True)
        with open(values_ru_path, "wb") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n'.encode("utf-8"))
        tree_out = ET.ElementTree(merged_root)
        tree_out.write(values_ru_path, encoding="utf-8", xml_declaration=False)
        _save_checkpoint(
            cp_path,
            done_keys,
            {"module": str(module_dir), "strings_xml": str(values_ru_path)},
        )
        print(f"[save] {values_ru_path} (+ checkpoint), ключей в checkpoint: {len(done_keys)}")
        changed_since_save = 0

    total = len(pending_merges)
    for idx, (sk, src_el, tgt_el) in enumerate(pending_merges, 1):
        if tgt_el is None:
            continue
        ch, err = _merge_translation(
            src_el,
            tgt_el,
            done_keys=done_keys,
            key_name=sk,
            translate_fn=translate_fn,
            copy_source=copy_source,
            skip_existing_ru=False,
        )
        if err:
            print(f"[err] {sk}: {err}", file=sys.stderr)
            errors += 1
            continue
        if ch:
            changed_since_save += 1
            print(f"[{idx}/{total}] OK {sk}")
            if not copy_source and translate_delay > 0:
                time.sleep(translate_delay)
        if changed_since_save >= save_every:
            flush_tree()

    if changed_since_save > 0 or not values_ru_path.is_file():
        flush_tree()
    elif total == 0:
        print(f"[ok] нечего переводить в {module_dir.name}")

    return 0 if errors == 0 else 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Заполнение values-ru/strings.xml из values/strings.xml")
    ap.add_argument(
        "-m",
        "--module",
        action="append",
        dest="modules",
        required=False,
        help="Каталог приложения (родитель res/). Можно указать несколько раз.",
    )
    ap.add_argument(
        "--source-lang",
        default="auto",
        help="Язык исходника для Google (например en, zh-CN). По умолчанию auto.",
    )
    ap.add_argument("--target-lang", default="ru")
    ap.add_argument(
        "--save-every",
        type=int,
        default=25,
        help="Сохранять strings.xml и checkpoint каждые N успешных переводов.",
    )
    ap.add_argument(
        "--copy-source",
        action="store_true",
        help="Не вызывать переводчик — копировать исходный текст (проверка пайплайна).",
    )
    ap.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Перезаписать все непустые строки в values-ru (игнорировать отличие от исходника). "
        "Иначе совпадение с values/strings.xml не считается «переводом» и снова переводится.",
    )
    ap.add_argument(
        "--no-resume",
        action="store_true",
        help="Не использовать checkpoint (начать список done_keys заново).",
    )
    ap.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Пауза (сек) между запросами к переводчику (не используется с --copy-source).",
    )
    ap.add_argument(
        "--tools-dir",
        type=Path,
        default=None,
        help="Каталог tools (для checkpoints). По умолчанию каталог этого скрипта.",
    )
    ap.add_argument(
        "--total-functions",
        action="store_true",
        help="После модулей: перевести строки с CJK для assets/total_functions.json → translate_functions.json.",
    )
    ap.add_argument(
        "--only-total-functions",
        action="store_true",
        help="Только total_functions / translate_functions.json, без values-ru/strings.xml.",
    )
    ap.add_argument(
        "--sync-functions-assets",
        action="store_true",
        help="После перевода записать merged JSON в AndesHive_src и AndesSceneBlock_src assets.",
    )
    ap.add_argument(
        "--report-functions",
        action="store_true",
        help="Статистика оставшегося CJK в merged total_functions.json.",
    )
    ap.add_argument(
        "--functions-base",
        type=Path,
        default=DEFAULT_FUNCTIONS_BASE,
        help="Базовый total_functions.json (исходник с китайским).",
    )
    ap.add_argument(
        "--functions-translate",
        type=Path,
        default=DEFAULT_FUNCTIONS_TRANSLATE,
        help="Файл translate_functions.json (string_map пополняется автоматически).",
    )
    ap.add_argument(
        "--functions-save-every",
        type=int,
        default=None,
        help="Сохранять translate_functions.json каждые N строк (по умолчанию как --save-every).",
    )
    ap.add_argument(
        "--functions-max",
        type=int,
        default=None,
        help="Ограничить число переводимых уникальных строк (тест).",
    )
    ap.add_argument(
        "--functions-json-indent",
        type=int,
        default=2,
        help="Отступ merged JSON при записи в assets.",
    )

    args = ap.parse_args()
    if not args.copy_source and GoogleTranslator is None:
        print(
            "Ошибка: для этого интерпретатора не установлен deep-translator.\n"
            f"  Python: {sys.executable}\n"
            "Установите в то же окружение:\n"
            "  python3 -m pip install --user --break-system-packages deep-translator\n"
            "Или используйте обёртку (ставит пакет через pip для этого же Python):\n"
            "  bash tools/functions/run_fill_values_ru.sh ...\n"
            "Либо запустите с --copy-source для проверки без перевода.",
            file=sys.stderr,
        )
        return 1

    tools_dir = args.tools_dir or Path(__file__).resolve().parent.parent

    run_functions = bool(args.total_functions or args.only_total_functions)
    only_functions = bool(args.only_total_functions)

    modules: list[Path]
    if only_functions:
        modules = []
    elif args.modules:
        modules = [Path(m).expanduser().resolve() for m in args.modules]
    else:
        modules = [p.resolve() for p in DEFAULT_MODULES]
        print("[info] --module не указан, используем хардкод-список модулей:")
        for p in modules:
            print(f"  - {p}")

    rc = 0
    for module_dir in modules:
        r = fill_module(
            module_dir,
            source_lang=args.source_lang,
            target_lang=args.target_lang,
            save_every=max(1, args.save_every),
            copy_source=args.copy_source,
            skip_existing=not args.no_skip_existing,
            tools_dir=tools_dir,
            resume=not args.no_resume,
            translate_delay=max(0.0, args.delay),
        )
        rc = max(rc, r)

    if run_functions:
        fevery = args.functions_save_every if args.functions_save_every is not None else args.save_every
        r = fill_total_functions_string_map(
            tools_dir=tools_dir,
            source_lang=args.source_lang,
            target_lang=args.target_lang,
            save_every=max(1, fevery),
            copy_source=args.copy_source,
            skip_existing=not args.no_skip_existing,
            resume=not args.no_resume,
            translate_delay=max(0.0, args.delay),
            sync_assets=args.sync_functions_assets,
            report=args.report_functions,
            json_indent=max(0, args.functions_json_indent),
            functions_base=args.functions_base.resolve(),
            functions_translate=args.functions_translate.resolve(),
            functions_max=args.functions_max,
        )
        rc = max(rc, r)

    return rc


if __name__ == "__main__":
    sys.exit(main())
