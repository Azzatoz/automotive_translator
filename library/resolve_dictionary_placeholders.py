#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Закрыть заглушки в словарях без Google: ru = source для техстрок.

Только то, что в fill считается copy-as-is / looks_technical / шаблоны.
Остальные заглушки — вручную (GUI: двойной щелчок по модулю) или fill по APK.

  python3 library/resolve_dictionary_placeholders.py --dry-run
  python3 library/resolve_dictionary_placeholders.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(_LIB))

from library_persist import load_track_map, save_track_map  # noqa: E402
from paths import DICT_EN, DICT_ZH  # noqa: E402
from source_resolve import (  # noqa: E402
    Track,
    _FQCN_RE,
    has_cjk,
    is_placeholder_ru,
    looks_technical,
    skip_for_translation_library,
)

# Явно требуют нормального перевода, не копирования
_NEEDS_HUMAN_RU = frozenset({
    "address",
    "clipboard",
    "content",
    "Coffee",
    "decrease",
    "floating close",
    "floating setting",
    "increase",
    "name",
    "slogan",
    "timepoint",
    "user",
    "weather",
})

_BRAND_OR_PRODUCT_AS_IS = frozenset({
    "Apple CarPlay",
    "Changan",
    "China Mobile",
    "China Telecom",
    "China Unicom",
    "Deepal-OTA",
    "FileDownloader",
    "Hi-Fi",
    "HMIGodotPro",
    "MegaOS",
    "Shen lan",
})


def _copy_as_is_fill(text: str) -> bool:
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


def should_copy_source_as_ru(text: str, *, track: Track | None = None) -> bool:
    """Техстрока / шаблон / бренд — в ru копируем исходник, Google не нужен."""
    if text in _NEEDS_HUMAN_RU:
        return False
    if text in _BRAND_OR_PRODUCT_AS_IS:
        return True

    s = text.strip()
    # zh-трек: длинный китайский UI — переводить, не копировать иероглифы в ru
    if track == "zh" and has_cjk(s) and not looks_technical(s):
        if re.fullmatch(r"第%s个", s) or re.fullmatch(r"\[一-龥\]", s):
            return True
        return False
    if not s:
        return True
    if _copy_as_is_fill(s) or looks_technical(s):
        return True

    if re.search(r"[<>&]|\\n|;\s*space|bottom_|_enabled:|get[A-Z]|\.com$", s):
        return True
    if re.fullmatch(r"\$\{[^}]+\}", s):
        return True
    if re.fullmatch(r"\([^)]*%[^)]*\)", s):
        return True
    if re.fullmatch(r"[+]? ?%[\w$]+", s):
        return True
    if re.fullmatch(r"[A-Z]( [A-Z]){1,5}", s) or re.fullmatch(r"[A-Z]{2,5}", s):
        return True
    if s.isascii() and re.fullmatch(r"[\w,;]+", s) and (";" in s or s.count(",") >= 2):
        return True
    if re.fullmatch(r"[a-z][a-zA-Z0-9_]*", s) and any(c.isupper() for c in s[1:]):
        return True
    if re.fullmatch(r"[a-z_]+:[\w]+", s):
        return True
    if re.fullmatch(r"\d+[a-z]{1,3}", s, re.I):
        return True
    if re.fullmatch(r"[\d°℃#+\-]+|[-\d.]+[°℃]?|[\d ]{7,}|->|\\\\#", s):
        return True
    if re.fullmatch(r"[\w+\-/‑]+", s) and any(
        x in s
        for x in (
            "Wi-Fi",
            "Wi‑Fi",
            "WPA",
            "LTE",
            "4G",
            "5G",
            "DNS",
            "VPN",
            "WEP",
            "OTA",
            "CarPlay",
            "iOS",
            "http",
            "ESP",
            "MCU",
            "LC3",
        )
    ):
        return True
    if re.fullmatch(r"[A-Za-z]+[-][A-Za-z0-9]+", s):
        return True
    if re.fullmatch(r"[a-z]+\d+", s):
        return True
    if len(s) >= 10 and set(s) <= {"g", " "}:
        return True
    if re.fullmatch(r"\d{2}:\d{2}(?:-\d{2}:\d{2})?", s):
        return True
    if re.fullmatch(r"\d{2}:\d{2}:\d{2}(?:\.\d+)?", s):
        return True
    if re.fullmatch(r"-?[0-9A-Fa-f]{4,}(?:-[0-9A-Fa-f]{4,})*-?", s):
        return True
    if re.fullmatch(r"W\+", s):
        return True
    if re.fullmatch(r",?[a-zA-Z]+=", s):
        return True
    if re.fullmatch(r"L%d", s):
        return True
    if re.fullmatch(r"\\#", s):
        return True
    if re.fullmatch(r"第%s个", s):
        return True
    if re.fullmatch(r"\[一-龥\]", s):
        return True
    if re.fullmatch(r"[A-Za-z0-9+ /‑-]+", s) and any(
        x in s for x in ("4G", "5G", "LTE", "DNS", "Wi", "WAPI", "Gig", "Lock")
    ):
        return True
    if re.fullmatch(r"B\d+", s):
        return True
    if re.fullmatch(r"[A-Za-z]+\d*", s) and s[0].isupper() and len(s) <= 16 and " " not in s:
        if s not in _NEEDS_HUMAN_RU and s not in ("Coffee",):
            return True
    if len(s) > 40 and s.isascii() and "@" in s and "." in s:
        return True

    # debug / metadata / SDK (часто из сторонних APK)
    if s.startswith("AIza"):
        return True
    if re.fullmatch(r"[\d.]+[fsF]", s):
        return True
    if re.fullmatch(r"\d+[dhm],\d+", s):
        return True
    if re.fullmatch(r"\d+ X", s) or re.fullmatch(r"\d+ s", s):
        return True
    if re.fullmatch(r"\d+%", s) or s in ("--:--", "0~99", ".debug", ".sharing.fileprovider"):
        return True
    if s.startswith("- SD-card:") or (s.startswith("- ") and (":" in s or "%s" in s)):
        return True
    if s.startswith(("Debug ", "App version", "Active flags")):
        return True
    if s in ("ADFOX ENVIRONMENT", "Api environment", "Current endpoint", "AA UI", "CarPlay UI"):
        return True
    if re.fullmatch(r":[A-Za-z]+", s):
        return True
    if re.fullmatch(r"\$[\w]+\$", s):
        return True
    if re.fullmatch(r"\+7[\d X\-]+", s) or re.fullmatch(r"\d{3} \d{3}-\d{2}-\d{2}", s):
        return True
    if ", com." in s and len(s) > 60:
        return True
    if re.fullmatch(r"\d+:\d+:android:[a-f0-9]+", s):
        return True
    if s.startswith("^") or (s.count("\\") >= 2 and re.search(r"[\[\]|*+?()]", s)):
        return True
    if re.fullmatch(r"%1\$\.[\d]+[a-zA-Z]+", s):
        return True
    if re.fullmatch(r"A \d{3} AA \d{3}", s):
        return True
    if re.fullmatch(r"Country_Id:%s", s) or s.startswith("Audio_codecs:"):
        return True
    if re.fullmatch(r"App_version: v%1\$s\(%2\$s\)", s):
        return True
    if re.fullmatch(r"key\d+=value\d+", s) or ("key1=value1" in s and "\\n" in s):
        return True
    # названия треков «Artist — Title»
    if " — " in s and len(s) < 90 and not re.search(
        r"\b(error|please|try|allow|delete|connect|watch|subscribe|internet)\b", s, re.I
    ):
        return True
    if track == "zh":
        if s.startswith("点击|") or re.fullmatch(r"开始导航.*", s):
            return True
        if s.startswith("<html>"):
            return True

    # оставшиеся SDK / шаблоны / debug en
    if s.startswith('"') and ("%" in s or "key1=" in s):
        return True
    if s.startswith("Lorem ipsum"):
        return True
    if re.fullmatch(r"MMM dd.*", s) or re.fullmatch(r"d MMMM.*", s):
        return True
    if re.fullmatch(r"ISO %1\$d", s):
        return True
    if re.fullmatch(r"© .*", s) or re.fullmatch(r"¥\d+", s):
        return True
    if re.fullmatch(r"•+ %1\$s", s) or s in ("•• %1$s", "•••• %1$s"):
        return True
    if re.fullmatch(r"№ %1\$s · %2\$s \(%3\$s\)", s):
        return True
    if re.fullmatch(r"~%1\$s", s) or re.fullmatch(r"«%s»", s):
        return True
    if "cubic-bezier" in s:
        return True
    if s.startswith(("ca-app-pub", "com.", "com/")) or "@" in s and "." in s:
        return True
    if re.fullmatch(r"\\\\?|\\\\@|\\\\\"|\\\\#", s):
        return True
    if re.fullmatch(r"\\\\#+.*", s):
        return True
    if re.fullmatch(r"\\+7 .*", s):
        return True
    if s.endswith(":") and ("_" in s or s[0].isupper()):
        return True
    if re.search(r": %[sb]$", s):
        return True
    if re.fullmatch(r"\[[\d\w:,{}\s\"]+\]", s) and "language" in s:
        return True
    if re.fullmatch(r"\[0-9\]d\*.*", s):
        return True
    if s.startswith("– "):
        return True
    if re.fullmatch(r"f/%1\$,.1f", s):
        return True
    if s in (
        "Baidu CarLife",
        "Billie Eilish",
        "Delivery Club",
        "Google Pay",
        "Google Play",
        "Google+",
        "Huawei APA",
        "Huawei AVM",
        "Imagine Dragons",
        "Instagram Stories",
        "Kuwo Music",
        "Linkin Park",
        "Mir Pay",
        "Noize MC",
        "Samsung Pay",
        "Yandex Radio",
        "Yango Maps",
        "ZXing Android Embedded",
        "Yandex LTD",
        "Español",
        "Français",
        "Română",
        "Türkçe",
        "Português do Brasil",
        "Azərbaycan",
        "Bahasa Indonesia",
        "A/C MAX",
        "3.5G",
        "Android Wear",
        "Apple Pay",
        "HQ+",
        "navimaps",
        "Lorem ipsum",
    ) or s.startswith("Lorem ipsum"):
        return True

    return False


def resolve_track(track: Track, path: Path, *, dry_run: bool) -> tuple[int, int]:
    string_map = load_track_map(path) if path.is_file() else {}
    copied = left = 0
    for key, ru in list(string_map.items()):
        if not is_placeholder_ru(ru):
            continue
        if should_copy_source_as_ru(key, track=track):
            if not dry_run:
                string_map[key] = key
            copied += 1
            print(f"  [copy] {key[:72]!r}", flush=True)
        else:
            left += 1
    if not dry_run and copied:
        save_track_map(path, track, string_map)
    return copied, left


def main() -> int:
    ap = argparse.ArgumentParser(description="Заглушки → ru=source для техстрок (без Google)")
    ap.add_argument("--track", choices=("en", "zh", "both"), default="both")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total_c = total_l = 0
    tracks: list[tuple[Track, Path]] = []
    if args.track in ("en", "both"):
        tracks.append(("en", DICT_EN))
    if args.track in ("zh", "both"):
        tracks.append(("zh", DICT_ZH))

    for track, path in tracks:
        print(f"[{track}] {path.name}", flush=True)
        c, l = resolve_track(track, path, dry_run=args.dry_run)
        total_c += c
        total_l += l
        print(f"  скопировано: {c}, осталось заглушек: {l}", flush=True)

    print(f"[done] copy-as-is: {total_c}, нужен ручной перевод: {total_l}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
