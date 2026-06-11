#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Исправляет в словарях ru-переводы шаблонов дат и типичные аббревиатуры (латиница)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT / "library"))

from library_persist import load_track_map, save_track_map  # noqa: E402
from source_resolve import Track  # noqa: E402

def _exact_pairs() -> dict[str, str]:
    """Пары source → ru (% в ключах — только через конкатенацию, не %-literal в dict)."""
    pct = "%"
    return {
        f"{pct}1$d月{pct}2$d日": f"{pct}2$d.{pct}1$d",
        f"{pct}1$s月{pct}2$s日": f"{pct}2$s.{pct}1$s",
        f"{pct}2$d年{pct}1$d月": f"{pct}1$d.{pct}2$d",
        f"{pct}1$d年{pct}2$d月": f"{pct}2$d.{pct}1$d",
        "M月d日 EEEE": "EEEE, MMM d",
        "yyyy年MM月dd号": "dd.MM.yyyy",
        "yyyy年MM月dd日 HH:mm:ss": "dd.MM.yyyy HH:mm:ss",
        "数据更新时间：yyyy年MM月dd日 HH:mm:ss": "Обновлено: dd.MM.yyyy HH:mm:ss",
        "MIDI": "MIDI",
        "h:mm": "HH:mm",
        f"{pct}1$dMonth{pct}2$dDay": f"{pct}2$d.{pct}1$d",
        f"{pct}1$dYear{pct}2$dMonth": f"{pct}1$d.{pct}2$d",
        "E, MMM d": "E, MMM d",
        "EEEE, MMM d": "EEEE, MMM d",
        "EEEE, MMMM d": "EEEE, MMMM d",
        "M/d/y": "d.M.y",
        "yyyy-MM-dd HH:mm": "yyyy-MM-dd HH:mm",
        "E": "E",
    }


EXACT = _exact_pairs()

def _ru_replacements() -> list[tuple[str, str]]:
    p = "%"
    return [
        (f"{p}1$dгод{p}2$dмесяц{p}3$d", f"{p}3$d.{p}2$d.{p}1$d"),
        ("ММ/дд/гггг ЧЧ: мм: сс", "dd.MM.yyyy HH:mm:ss"),
        ("ММ, дд, гггг год ЧЧ:мм:сс", "dd.MM.yyyy HH:mm:ss"),
    ]


RU_REPLACEMENTS = _ru_replacements()

_BAD_DATE_RU = re.compile(
    r"ЭЭЭЭ|ММММ|МММ д|Э, МММ|М/д/г|"
    r"месяц %\d|%\d+ месяц|%\d+ день|год %\d|"
    r"гггг-ММ-дд ЧЧ|ЧЧ:мм|ЧЧ: мм",
    re.I,
)


def _is_date_format_source(src: str) -> bool:
    s = src.strip()
    if not s or len(s) > 80:
        return False
    if re.search(r"[月年日号]", s) and re.search(r"[%yMdHms/:\s]", s):
        return True
    if re.fullmatch(r"[EMdHmsy/:\s,\-.%]+", s) and re.search(r"[EMd]{2,}", s):
        return True
    return False


def fix_map(string_map: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for src, ru_raw in list(string_map.items()):
        if not isinstance(ru_raw, str):
            continue
        ru = ru_raw
        new_ru: str | None = None
        if src in EXACT:
            new_ru = EXACT[src]
        elif _BAD_DATE_RU.search(ru) and (_is_date_format_source(src) or src in EXACT):
            new_ru = EXACT.get(src)
        if new_ru is None:
            patched = ru
            for old, new in RU_REPLACEMENTS:
                if old in patched:
                    patched = patched.replace(old, new)
            if patched != ru:
                new_ru = patched
        if new_ru is not None and new_ru != ru:
            string_map[src] = new_ru
            changed.append(src)
    return changed


def main() -> int:
    dict_dir = TOOLS_ROOT / "data" / "dictionaries"
    jobs: list[tuple[Path, Track]] = [
        (dict_dir / "translation_library_ru_zh-rCN.json", "zh"),
        (dict_dir / "translation_library_ru_en.json", "en"),
    ]
    for path, track in jobs:
        string_map = load_track_map(path)
        changed = fix_map(string_map)
        if changed:
            save_track_map(path, track, string_map)
        print(f"{path.name}: исправлено {len(changed)}", flush=True)
        for src in changed[:20]:
            print(f"  - {src[:70]}{'…' if len(src) > 70 else ''}", flush=True)
        if len(changed) > 20:
            print(f"  … и ещё {len(changed) - 20}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
