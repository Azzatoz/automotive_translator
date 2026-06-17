#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Применить ручные переводы source→ru к словарям."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(_LIB))

from library_persist import load_track_map, save_track_map  # noqa: E402
from paths import DICT_EN, DICT_ZH  # noqa: E402
from source_resolve import Track, is_placeholder_ru, is_real_translation  # noqa: E402


def apply_file(path: Path, track: Track, translations: dict[str, str], *, dry_run: bool) -> tuple[int, int]:
    string_map = load_track_map(path)
    applied = skipped = 0
    for src, ru in translations.items():
        if src not in string_map:
            continue
        if not is_placeholder_ru(string_map.get(src)):
            skipped += 1
            continue
        if not is_real_translation(src, ru):
            skipped += 1
            continue
        if not dry_run:
            string_map[src] = ru
        applied += 1
    if not dry_run and applied:
        save_track_map(path, track, string_map)
    return applied, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("json_file", type=Path, help="JSON: {track: {source: ru}} или {source: ru}")
    ap.add_argument("--track", choices=("en", "zh", "auto"), default="auto")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = json.loads(args.json_file.read_text(encoding="utf-8"))
    total = 0
    if args.track in ("en", "auto") and isinstance(data.get("en"), dict):
        a, s = apply_file(DICT_EN, "en", data["en"], dry_run=args.dry_run)
        print(f"[en] применено {a}, пропущено {s}")
        total += a
    if args.track in ("zh", "auto") and isinstance(data.get("zh"), dict):
        a, s = apply_file(DICT_ZH, "zh", data["zh"], dry_run=args.dry_run)
        print(f"[zh] применено {a}, пропущено {s}")
        total += a
    if "en" not in data and "zh" not in data and isinstance(data, dict):
        # flat map — try both tracks
        for track, p in (("en", DICT_EN), ("zh", DICT_ZH)):
            a, s = apply_file(p, track, data, dry_run=args.dry_run)
            if a:
                print(f"[{track}] применено {a}, пропущено {s}")
                total += a
    print(f"[done] всего {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
