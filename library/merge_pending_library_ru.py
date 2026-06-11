#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перенести заполненные переводы из translation_library_ru_*_pending.json в основной словарь.

В pending остаются только строки с пустым ru ("" или « »). Заполните ru в pending-файле
и запустите этот скрипт (или снова collect — он тоже переносит готовые pending → main).

  python3 library/merge_pending_library_ru.py --track both
  python3 library/merge_pending_library_ru.py --track en --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from library_persist import (  # noqa: E402
    PENDING_KIND,
    default_pending_path,
    load_track_map,
    order_string_map,
    save_track_map,
)
from source_resolve import Track, is_placeholder_ru  # noqa: E402


def promote_pending(
    main_map: dict[str, str],
    pending_map: dict[str, str],
    *,
    overwrite: bool,
) -> tuple[dict[str, str], dict[str, str], int]:
    new_pending: dict[str, str] = {}
    promoted = 0
    for src, ru in pending_map.items():
        if ru and not is_placeholder_ru(ru):
            if overwrite or src not in main_map:
                main_map[src] = ru
            promoted += 1
        else:
            new_pending[src] = ru
    return main_map, new_pending, promoted


def _main_path(tools: Path, track: Track) -> Path:
    base = tools / "data" / "dictionaries"
    return (
        base / "translation_library_ru_en.json"
        if track == "en"
        else base / "translation_library_ru_zh-rCN.json"
    )


def merge_track(
    tools: Path,
    track: Track,
    *,
    main_path: Path | None,
    pending_path: Path | None,
    overwrite: bool,
    dry_run: bool,
) -> int:
    main_p = (main_path or _main_path(tools, track)).expanduser().resolve()
    pend_p = (pending_path or default_pending_path(tools, track)).expanduser().resolve()
    if not pend_p.is_file():
        print(f"[skip][{track}] нет pending: {pend_p}")
        return 0

    main_map = load_track_map(main_p) if main_p.is_file() else {}
    pending_map = load_track_map(pend_p)
    main_map, pending_map, promoted = promote_pending(
        main_map, pending_map, overwrite=overwrite
    )

    print(
        f"[{track}] {pend_p.name}: перенесено в {main_p.name}: {promoted}; "
        f"осталось pending: {len(pending_map)}"
    )
    if dry_run:
        return 0

    save_track_map(main_p, track, main_map)
    save_track_map(
        pend_p,
        track,
        order_string_map(pending_map),
    )
    return 0


def main() -> int:
    tools = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="pending → основной словарь")
    ap.add_argument("--track", choices=("en", "zh", "both"), default="both")
    ap.add_argument("--main-en", type=Path, default=None)
    ap.add_argument("--main-zh", type=Path, default=None)
    ap.add_argument("--pending-en", type=Path, default=None)
    ap.add_argument("--pending-zh", type=Path, default=None)
    ap.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Не перезаписывать уже существующие ключи в основном словаре",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    overwrite = not args.no_overwrite
    tracks: list[Track] = []
    if args.track in ("en", "both"):
        tracks.append("en")
    if args.track in ("zh", "both"):
        tracks.append("zh")

    rc = 0
    for track in tracks:
        rc = max(
            rc,
            merge_track(
                tools,
                track,
                main_path=args.main_en if track == "en" else args.main_zh,
                pending_path=args.pending_en if track == "en" else args.pending_zh,
                overwrite=overwrite,
                dry_run=args.dry_run,
            ),
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())
