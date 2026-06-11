#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сортировка translation_library_ru_en.json и translation_library_ru_zh-rCN.json.

Порядок string_map:
  1) все записи с реальным переводом — по алфавиту ключа;
  2) заглушки (ru = « » или пусто) — в конце файла, тоже по алфавиту.

Остальные поля JSON (meta, schema_version, …) не меняются.

Пример:
  python3 "tools Linux/sort_translation_libraries.py"
  python3 "tools Linux/sort_translation_libraries.py" --en-only
  python3 "tools Linux/sort_translation_libraries.py" --zh path/to/custom.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_LIB = Path(__file__).resolve().parent / "library"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from library_persist import order_string_map  # noqa: E402
from source_resolve import is_placeholder_ru  # noqa: E402


def sort_library_file(path: Path, *, dry_run: bool = False) -> tuple[int, int, int]:
    """Возвращает (всего, переводы, заглушки)."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    sm = data.get("string_map")
    if not isinstance(sm, dict):
        raise ValueError(f"{path}: нет объекта string_map")
    raw = {str(k): str(v) for k, v in sm.items()}
    n_ph_before = sum(1 for v in raw.values() if is_placeholder_ru(v))
    ordered = order_string_map(raw)
    n_ph = sum(1 for v in ordered.values() if is_placeholder_ru(v))
    data["string_map"] = ordered
    if "updated_at" in data and isinstance(data["updated_at"], str):
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if isinstance(data.get("meta"), dict):
        data["meta"]["sorted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not dry_run:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(ordered), len(ordered) - n_ph, n_ph


def main() -> int:
    tools_root = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Сортировка библиотек en/zh (заглушки в конце)")
    ap.add_argument(
        "--en",
        type=Path,
        default=tools_root / "translation_library_ru_en.json",
        help="Путь к en-словарю",
    )
    ap.add_argument(
        "--zh",
        type=Path,
        default=tools_root / "translation_library_ru_zh-rCN.json",
        help="Путь к zh-словарю",
    )
    ap.add_argument("--en-only", action="store_true", help="Только en")
    ap.add_argument("--zh-only", action="store_true", help="Только zh")
    ap.add_argument("--dry-run", action="store_true", help="Не записывать файл")
    args = ap.parse_args()

    paths: list[tuple[str, Path]] = []
    if args.en_only:
        paths.append(("en", args.en))
    elif args.zh_only:
        paths.append(("zh", args.zh))
    else:
        paths.append(("en", args.en))
        paths.append(("zh", args.zh))

    for label, p in paths:
        total, real, ph = sort_library_file(p, dry_run=args.dry_run)
        action = "would sort" if args.dry_run else "sorted"
        print(f"[{label}] {action} {p}: {total} keys ({real} translations, {ph} placeholders at end)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
