#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка: merged assets/total_functions.json без иероглифов, Hive и SceneBlock совпадают,
опционально — что значения в translate_functions.json не содержат CJK.

Выход: 0 если всё ок, иначе 1.

Пример:
  python3 tools/functions/verify_total_functions_ru.py
  python3 tools/functions/verify_total_functions_ru.py --check-translate-json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TRANSLATED_ROOT = Path(__file__).resolve().parents[2] / "Translated"
DEFAULT_HIVE = TRANSLATED_ROOT / "AndesHive_src" / "assets" / "total_functions.json"
DEFAULT_SB = TRANSLATED_ROOT / "AndesSceneBlock_src" / "assets" / "total_functions.json"
DEFAULT_TRANSLATE = Path(__file__).resolve().parent / "translate_functions.json"

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufadf]")


def _walk_strings(obj: object, acc: list[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk_strings(k, acc)
            _walk_strings(v, acc)
    elif isinstance(obj, list):
        for x in obj:
            _walk_strings(x, acc)
    elif isinstance(obj, str):
        acc.append(obj)


def count_cjk(strings: list[str]) -> tuple[int, int, list[str]]:
    total_chars = 0
    with_hits: list[str] = []
    for s in strings:
        if _CJK.search(s):
            total_chars += len(_CJK.findall(s))
            with_hits.append(s)
    return total_chars, len(with_hits), with_hits


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверка русского total_functions.json")
    ap.add_argument("--hive", type=Path, default=DEFAULT_HIVE)
    ap.add_argument("--sceneblock", type=Path, default=DEFAULT_SB)
    ap.add_argument("--translate-json", type=Path, default=DEFAULT_TRANSLATE)
    ap.add_argument(
        "--check-translate-json",
        action="store_true",
        help="Проверить что значения string_map не содержат CJK",
    )
    args = ap.parse_args()

    errs = 0

    if not args.hive.is_file():
        print(f"[fail] нет файла: {args.hive}", file=sys.stderr)
        return 1
    if not args.sceneblock.is_file():
        print(f"[fail] нет файла: {args.sceneblock}", file=sys.stderr)
        return 1

    ha = args.hive.read_bytes()
    sb = args.sceneblock.read_bytes()
    if ha != sb:
        print("[fail] AndesHive_src и AndesSceneBlock_src total_functions.json различаются по байтам", file=sys.stderr)
        errs += 1
    else:
        print("[ok] оба assets/total_functions.json идентичны")

    try:
        data = json.loads(ha.decode("utf-8"))
    except json.JSONDecodeError as e:
        print(f"[fail] JSON parse: {e}", file=sys.stderr)
        return 1

    strings: list[str] = []
    _walk_strings(data, strings)
    cjk_chars, n_str, samples = count_cjk(strings)
    if cjk_chars > 0:
        print(f"[fail] в merged JSON осталось CJK: символов={cjk_chars}, строк={n_str}", file=sys.stderr)
        for s in samples[:8]:
            print(f"  sample: {s[:120]!r}{'...' if len(s) > 120 else ''}", file=sys.stderr)
        errs += 1
    else:
        print("[ok] в merged JSON нет символов CJK")

    if args.check_translate_json and args.translate_json.is_file():
        tcfg = json.loads(args.translate_json.read_text(encoding="utf-8"))
        sm = tcfg.get("string_map") or {}
        bad_v = [v for v in sm.values() if isinstance(v, str) and _CJK.search(v)]
        bad_id = [k for k, v in sm.items() if isinstance(k, str) and isinstance(v, str) and k.strip() == v.strip() and k.strip()]
        if bad_v:
            print(f"[fail] в translate_functions string_map значений с CJK: {len(bad_v)}", file=sys.stderr)
            errs += 1
        if bad_id:
            print(f"[fail] в string_map пар «ключ==значение» (как исходник): {len(bad_id)}", file=sys.stderr)
            errs += 1
        if not bad_v and not bad_id:
            print("[ok] translate_functions.json string_map: нет CJK в значениях, нет тождественных пар")

    if errs:
        return 1
    print("[ok] проверка пройдена — в собранных assets подмена на русский согласована.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
