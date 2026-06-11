#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Переносит ручные решения конфликтов в translation_library_ru.json.

1. Создайте шаблон (все конфликты с подсказкой «большинство модулей»):
     python3 tools/library/apply_translation_conflict_resolutions_ru.py --init

2. Отредактируйте tools/library/translation_library_ru_resolutions.json:
     для каждого source укажите выбранный русский текст в "chosen".

3. Примените:
     python3 tools/library/apply_translation_conflict_resolutions_ru.py --apply

4. Пересоберите отчёты (конфликт исчезнет из conflicts, попадёт в string_map):
     python3 tools/library/collect_translation_library_ru.py --library tools/translation_library_ru.json

Формат resolutions (пример):
  {
    "schema_version": 1,
    "resolutions": {
      "\\\"Couldn't connect\\\"": {
        "chosen": "Не удалось подключиться",
        "note": "ближе к оригиналу, без кавычек"
      }
    }
  }

Ключ — поле "source" из conflicts.json (копируйте как есть).
Значение "chosen" — один из вариантов из "translations" или свой канонический текст.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _pick_majority(variants: dict[str, list[str]]) -> tuple[str, int]:
    best_ru = ""
    best_n = -1
    for ru, mods in variants.items():
        n = len(mods)
        if n > best_n:
            best_n = n
            best_ru = ru
    return best_ru, best_n


def cmd_init(
    conflicts_path: Path,
    resolutions_path: Path,
    *,
    use_majority: bool,
    overwrite: bool,
) -> int:
    if resolutions_path.is_file() and not overwrite:
        print(f"Уже есть {resolutions_path} — удалите или укажите --overwrite", file=sys.stderr)
        return 1
    if not conflicts_path.is_file():
        print(f"Нет файла конфликтов: {conflicts_path}", file=sys.stderr)
        return 1

    data = _load_json(conflicts_path)
    conflicts = data.get("conflicts") or []
    resolutions: dict[str, Any] = {}

    for item in conflicts:
        src = item.get("source")
        variants = item.get("translations") or {}
        if not src or not isinstance(variants, dict):
            continue
        entry: dict[str, Any] = {"variants": variants}
        if use_majority and variants:
            majority, n = _pick_majority(variants)
            entry["chosen"] = majority
            entry["note"] = f"auto: большинство модулей ({n})"
        else:
            entry["chosen"] = ""
            entry["note"] = "заполните вручную"
        resolutions[src] = entry

    payload = {
        "schema_version": 1,
        "resolutions": resolutions,
        "meta": {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "from_conflicts": str(conflicts_path),
            "count": len(resolutions),
        },
    }
    _save_json(resolutions_path, payload)
    print(f"[write] {resolutions_path} — записей: {len(resolutions)}")
    if use_majority:
        print("[info] chosen заполнен вариантом с наибольшим числом модулей — проверьте спорные случаи")
    return 0


def cmd_apply(
    resolutions_path: Path,
    library_path: Path,
    *,
    strict_variants: bool,
    dry_run: bool,
) -> int:
    if not resolutions_path.is_file():
        print(f"Нет файла решений: {resolutions_path}", file=sys.stderr)
        return 1

    res_data = _load_json(resolutions_path)
    raw = res_data.get("resolutions") or {}
    if not isinstance(raw, dict):
        print("resolutions должен быть объектом", file=sys.stderr)
        return 1

    if library_path.is_file():
        lib_data = _load_json(library_path)
    else:
        lib_data = {"schema_version": 1, "string_map": {}, "meta": {}}

    string_map: dict[str, str] = dict(lib_data.get("string_map") or {})
    applied = 0
    skipped_empty = 0
    skipped_same = 0
    warnings: list[str] = []

    for src, val in raw.items():
        if isinstance(val, str):
            chosen = val.strip()
            variants: dict[str, list[str]] | None = None
        elif isinstance(val, dict):
            chosen = (val.get("chosen") or "").strip()
            variants = val.get("variants")
            if variants is None and isinstance(val.get("translations"), dict):
                variants = val["translations"]
        else:
            warnings.append(f"пропуск неверного типа для {src!r}")
            continue

        if not chosen:
            skipped_empty += 1
            continue

        if strict_variants and variants:
            if chosen not in variants:
                warnings.append(
                    f"chosen не среди variants для {src[:60]!r}… — всё равно применяем"
                )

        prev = string_map.get(src)
        if prev == chosen:
            skipped_same += 1
            continue

        if prev is not None and prev != chosen:
            warnings.append(f"перезапись: {src[:50]!r}…  {prev!r} → {chosen!r}")

        string_map[src] = chosen
        applied += 1

    lib_data["schema_version"] = 1
    from library_persist import order_string_map

    lib_data["string_map"] = order_string_map(string_map)
    meta = dict(lib_data.get("meta") or {})
    meta["resolutions_applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    meta["resolutions_file"] = str(resolutions_path)
    meta["string_map_size"] = len(string_map)
    lib_data["meta"] = meta

    print(f"[stats] применено: {applied}, без chosen: {skipped_empty}, без изменений: {skipped_same}")
    if warnings:
        print(f"[warn] предупреждений: {len(warnings)}")
        for w in warnings[:20]:
            print(f"  - {w}")
        if len(warnings) > 20:
            print(f"  … и ещё {len(warnings) - 20}")

    if dry_run:
        print("[dry-run] translation_library_ru.json не записан")
        return 0

    _save_json(library_path, lib_data)
    print(f"[write] {library_path} — string_map: {len(string_map)}")
    return 0


def main() -> int:
    library_dir = Path(__file__).resolve().parent
    tools_root = library_dir.parent
    default_conflicts = tools_root / "reports" / "translation_library_ru_conflicts.json"
    default_resolutions = library_dir / "translation_library_ru_resolutions.json"
    default_library = tools_root / "translation_library_ru.json"

    ap = argparse.ArgumentParser(description="Решения конфликтов → translation_library_ru.json")
    ap.add_argument("--conflicts", type=Path, default=default_conflicts)
    ap.add_argument("--resolutions", type=Path, default=default_resolutions)
    ap.add_argument("--library", type=Path, default=default_library)
    ap.add_argument(
        "--init",
        action="store_true",
        help="Создать translation_library_ru_resolutions.json из conflicts",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Записать chosen в string_map библиотеки",
    )
    ap.add_argument(
        "--majority",
        action="store_true",
        help="С --init: сразу подставить вариант с наибольшим числом модулей",
    )
    ap.add_argument("--overwrite", action="store_true", help="С --init: перезаписать resolutions")
    ap.add_argument(
        "--strict-variants",
        action="store_true",
        help="Предупредить, если chosen не совпадает ни с одним variant",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.init and not args.apply:
        ap.print_help()
        print(
            "\nТипичный цикл: --init  →  правка resolutions  →  --apply  →  collect_translation_library_ru.py",
            file=sys.stderr,
        )
        return 0

    rc = 0
    if args.init:
        rc = max(
            rc,
            cmd_init(
                args.conflicts.resolve(),
                args.resolutions.resolve(),
                use_majority=args.majority,
                overwrite=args.overwrite,
            ),
        )
    if args.apply:
        rc = max(
            rc,
            cmd_apply(
                args.resolutions.resolve(),
                args.library.resolve(),
                strict_variants=args.strict_variants,
                dry_run=args.dry_run,
            ),
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())
