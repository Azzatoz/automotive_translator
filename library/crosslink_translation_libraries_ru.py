#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Связать en- и zh-словари.

Google переводит **только исходник** en↔zh-CN. Русский **не переводится** — в парный
трек копируется тот же ru, что уже стоит у записи, откуда зеркалируем.

Порядок для каждой строки:
  1) уже обработана (checkpoint) → пропуск;
  2) зеркальный ключ известен (кэш / bootstrap) и в словаре уже тот же ru → пропуск без Google;
  3) иначе Google → проверка → дописать или пропустить.

Примеры:
  python3 library/crosslink_translation_libraries_ru.py --dry-run --max 20
  python3 library/crosslink_translation_libraries_ru.py --delay 0.15
  python3 library/crosslink_translation_libraries_ru.py --resume
  python3 library/crosslink_translation_libraries_ru.py --reset-checkpoint
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

_LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(_LIB))
sys.path.insert(0, str(_LIB.parent / "functions"))

import fill_values_ru as fvr  # noqa: E402
from library_persist import load_track_map, save_track_map  # noqa: E402
from paths import CHECKPOINTS_DIR, DICT_EN, DICT_ZH, REPORTS_DIR  # noqa: E402
from source_resolve import (  # noqa: E402
    classify_track_for_text,
    is_real_translation,
    is_placeholder_ru,
    skip_for_translation_library,
)

DEFAULT_CHECKPOINT = CHECKPOINTS_DIR / "crosslink_translation_libraries.json"
CHECKPOINT_EVERY = 25


@dataclass
class CrosslinkCheckpoint:
    en_to_zh: dict[str, str] = field(default_factory=dict)
    zh_to_en: dict[str, str] = field(default_factory=dict)
    done_en: set[str] = field(default_factory=set)
    done_zh: set[str] = field(default_factory=set)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "en_to_zh": self.en_to_zh,
            "zh_to_en": self.zh_to_en,
            "done_en": sorted(self.done_en),
            "done_zh": sorted(self.done_zh),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    @classmethod
    def load(cls, path: Path) -> CrosslinkCheckpoint:
        if not path.is_file():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            en_to_zh={str(k): str(v) for k, v in (data.get("en_to_zh") or {}).items()},
            zh_to_en={str(k): str(v) for k, v in (data.get("zh_to_en") or {}).items()},
            done_en=set(data.get("done_en") or []),
            done_zh=set(data.get("done_zh") or []),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)


@dataclass
class CrosslinkStats:
    added: int = 0
    google_calls: int = 0
    cache_hits: int = 0
    skipped_done: int = 0
    skipped_exists: int = 0
    skipped_conflict: int = 0
    skipped_invalid: int = 0


def _can_add(dst: dict[str, str], key: str, ru: str, *, overwrite: bool) -> bool:
    if not key or skip_for_translation_library(key):
        return False
    if not is_real_translation(key, ru):
        return False
    existing = dst.get(key)
    if existing is None:
        return True
    if is_placeholder_ru(existing):
        return True
    if existing == ru:
        return False
    return overwrite


def _bootstrap_cache_and_done(
    en_map: dict[str, str],
    zh_map: dict[str, str],
    cp: CrosslinkCheckpoint,
) -> tuple[int, int]:
    """Пары en↔zh с одним ru в обоих словарях — в кэш; уже совпадающие — в done."""
    ru_to_en: dict[str, list[str]] = defaultdict(list)
    ru_to_zh: dict[str, list[str]] = defaultdict(list)
    for k, v in en_map.items():
        if is_real_translation(k, v):
            ru_to_en[v].append(k)
    for k, v in zh_map.items():
        if is_real_translation(k, v):
            ru_to_zh[v].append(k)

    paired = 0
    for ru, ens in ru_to_en.items():
        zhs = ru_to_zh.get(ru, [])
        if len(ens) == 1 and len(zhs) == 1:
            en_src, zh_src = ens[0], zhs[0]
            cp.en_to_zh.setdefault(en_src, zh_src)
            cp.zh_to_en.setdefault(zh_src, en_src)
            paired += 1

    marked = 0
    for en_src, ru in en_map.items():
        zh_key = cp.en_to_zh.get(en_src)
        if zh_key and zh_map.get(zh_key) == ru:
            if en_src not in cp.done_en:
                cp.done_en.add(en_src)
                marked += 1
    for zh_src, ru in zh_map.items():
        en_key = cp.zh_to_en.get(zh_src)
        if en_key and en_map.get(en_key) == ru:
            if zh_src not in cp.done_zh:
                cp.done_zh.add(zh_src)
                marked += 1
    return paired, marked


def _mirror_key(
    src: str,
    *,
    direction: Literal["en→zh", "zh→en"],
    cp: CrosslinkCheckpoint,
    session_cache: dict[tuple[str, str, str], str],
    stats: CrosslinkStats,
) -> str | None:
    if direction == "en→zh":
        cached = cp.en_to_zh.get(src)
        if cached is not None:
            stats.cache_hits += 1
            return cached
        ck = (src, "en", "zh-CN")
        if ck in session_cache:
            stats.cache_hits += 1
            mirror = session_cache[ck]
            cp.en_to_zh[src] = mirror
            return mirror
        mirror = fvr._translate_with_google(src, "en", "zh-CN").strip()
        stats.google_calls += 1
        session_cache[ck] = mirror
        cp.en_to_zh[src] = mirror
        return mirror

    cached = cp.zh_to_en.get(src)
    if cached is not None:
        stats.cache_hits += 1
        return cached
    ck = (src, "zh-CN", "en")
    if ck in session_cache:
        stats.cache_hits += 1
        mirror = session_cache[ck]
        cp.zh_to_en[src] = mirror
        return mirror
    mirror = fvr._translate_with_google(src, "zh-CN", "en").strip()
    stats.google_calls += 1
    session_cache[ck] = mirror
    cp.zh_to_en[src] = mirror
    return mirror


def _crosslink_en_to_zh(
    en_map: dict[str, str],
    zh_map: dict[str, str],
    *,
    overwrite: bool,
    delay: float,
    max_items: int | None,
    dry_run: bool,
    cp: CrosslinkCheckpoint,
    session_cache: dict[tuple[str, str, str], str],
    stats: CrosslinkStats,
    report: dict[str, Any],
    checkpoint_path: Path,
    processed_since_save: list[int],
) -> None:
    for en_src, ru in en_map.items():
        if max_items is not None and stats.added >= max_items:
            break
        if en_src in cp.done_en:
            stats.skipped_done += 1
            continue
        if not is_real_translation(en_src, ru):
            continue
        if classify_track_for_text(en_src) != "en":
            continue

        cached_mirror = cp.en_to_zh.get(en_src)
        if cached_mirror is not None and zh_map.get(cached_mirror) == ru:
            cp.done_en.add(en_src)
            stats.skipped_exists += 1
            processed_since_save[0] += 1
            if processed_since_save[0] >= CHECKPOINT_EVERY:
                cp.save(checkpoint_path)
                processed_since_save[0] = 0
            continue

        google_before = stats.google_calls
        try:
            zh_key = _mirror_key(
                en_src,
                direction="en→zh",
                cp=cp,
                session_cache=session_cache,
                stats=stats,
            )
        except Exception as exc:
            report["errors"].append(f"en→zh: {en_src[:50]!r}: {exc}")
            cp.done_en.add(en_src)
            continue
        if delay > 0 and stats.google_calls > google_before:
            time.sleep(delay)

        if not zh_key or classify_track_for_text(zh_key) != "zh":
            stats.skipped_invalid += 1
            report["skipped"].append(f"en→zh: неверный трек: {en_src!r} → {zh_key!r}")
            cp.done_en.add(en_src)
            continue

        if zh_map.get(zh_key) == ru:
            cp.done_en.add(en_src)
            stats.skipped_exists += 1
            processed_since_save[0] += 1
            if processed_since_save[0] >= CHECKPOINT_EVERY:
                cp.save(checkpoint_path)
                processed_since_save[0] = 0
            continue

        if not _can_add(zh_map, zh_key, ru, overwrite=overwrite):
            if zh_map.get(zh_key) and zh_map[zh_key] != ru:
                stats.skipped_conflict += 1
                report["conflicts"].append(
                    {"from": en_src, "zh_key": zh_key, "ru": ru, "existing_ru": zh_map[zh_key]}
                )
            cp.done_en.add(en_src)
            processed_since_save[0] += 1
            if processed_since_save[0] >= CHECKPOINT_EVERY:
                cp.save(checkpoint_path)
                processed_since_save[0] = 0
            continue

        report["added"].append(
            {
                "direction": "en→zh",
                "src": en_src,
                "mirror": zh_key,
                "ru": ru,
                "ru_from": "en",
            }
        )
        print(f"  [mirror] en→zh: ru скопирован с en | {en_src[:40]!r} → {zh_key[:40]!r}", flush=True)
        if not dry_run:
            zh_map[zh_key] = ru
        stats.added += 1
        cp.done_en.add(en_src)
        processed_since_save[0] += 1
        if processed_since_save[0] >= CHECKPOINT_EVERY:
            cp.save(checkpoint_path)
            processed_since_save[0] = 0


def _crosslink_zh_to_en(
    en_map: dict[str, str],
    zh_map: dict[str, str],
    *,
    overwrite: bool,
    delay: float,
    max_items: int | None,
    dry_run: bool,
    cp: CrosslinkCheckpoint,
    session_cache: dict[tuple[str, str, str], str],
    stats: CrosslinkStats,
    report: dict[str, Any],
    checkpoint_path: Path,
    processed_since_save: list[int],
) -> None:
    for zh_src, ru in zh_map.items():
        if max_items is not None and stats.added >= max_items:
            break
        if zh_src in cp.done_zh:
            stats.skipped_done += 1
            continue
        if not is_real_translation(zh_src, ru):
            continue
        if classify_track_for_text(zh_src) != "zh":
            continue

        cached_mirror = cp.zh_to_en.get(zh_src)
        if cached_mirror is not None and en_map.get(cached_mirror) == ru:
            cp.done_zh.add(zh_src)
            stats.skipped_exists += 1
            processed_since_save[0] += 1
            if processed_since_save[0] >= CHECKPOINT_EVERY:
                cp.save(checkpoint_path)
                processed_since_save[0] = 0
            continue

        google_before = stats.google_calls
        try:
            en_key = _mirror_key(
                zh_src,
                direction="zh→en",
                cp=cp,
                session_cache=session_cache,
                stats=stats,
            )
        except Exception as exc:
            report["errors"].append(f"zh→en: {zh_src[:50]!r}: {exc}")
            cp.done_zh.add(zh_src)
            continue
        if delay > 0 and stats.google_calls > google_before:
            time.sleep(delay)

        if not en_key or classify_track_for_text(en_key) != "en":
            stats.skipped_invalid += 1
            report["skipped"].append(f"zh→en: неверный трек: {zh_src!r} → {en_key!r}")
            cp.done_zh.add(zh_src)
            continue

        if en_map.get(en_key) == ru:
            cp.done_zh.add(zh_src)
            stats.skipped_exists += 1
            processed_since_save[0] += 1
            if processed_since_save[0] >= CHECKPOINT_EVERY:
                cp.save(checkpoint_path)
                processed_since_save[0] = 0
            continue

        if not _can_add(en_map, en_key, ru, overwrite=overwrite):
            if en_map.get(en_key) and en_map[en_key] != ru:
                stats.skipped_conflict += 1
                report["conflicts"].append(
                    {"from": zh_src, "en_key": en_key, "ru": ru, "existing_ru": en_map[en_key]}
                )
            cp.done_zh.add(zh_src)
            processed_since_save[0] += 1
            if processed_since_save[0] >= CHECKPOINT_EVERY:
                cp.save(checkpoint_path)
                processed_since_save[0] = 0
            continue

        report["added"].append(
            {
                "direction": "zh→en",
                "src": zh_src,
                "mirror": en_key,
                "ru": ru,
                "ru_from": "zh",
            }
        )
        print(f"  [mirror] zh→en: ru скопирован с zh | {zh_src[:40]!r} → {en_key[:40]!r}", flush=True)
        if not dry_run:
            en_map[en_key] = ru
        stats.added += 1
        cp.done_zh.add(zh_src)
        processed_since_save[0] += 1
        if processed_since_save[0] >= CHECKPOINT_EVERY:
            cp.save(checkpoint_path)
            processed_since_save[0] = 0


def _run(args: argparse.Namespace) -> int:
    if args.reset_checkpoint:
        if args.checkpoint.is_file():
            args.checkpoint.unlink()
            print(f"[checkpoint] удалён {args.checkpoint}")

    en_map = load_track_map(args.library_en) if args.library_en.is_file() else {}
    zh_map = load_track_map(args.library_zh) if args.library_zh.is_file() else {}
    cp = CrosslinkCheckpoint.load(args.checkpoint) if args.resume or args.checkpoint.is_file() else CrosslinkCheckpoint()

    paired, marked_done = _bootstrap_cache_and_done(en_map, zh_map, cp)
    if paired:
        print(f"[bootstrap] пар en↔zh с одним ru в кэш: {paired}, отмечено готовым: {marked_done}")

    if args.resume:
        print(
            f"[checkpoint] resume: done_en={len(cp.done_en)}, done_zh={len(cp.done_zh)}, "
            f"кэш en→zh={len(cp.en_to_zh)}, zh→en={len(cp.zh_to_en)}"
        )

    report: dict[str, Any] = {
        "added": [],
        "skipped": [],
        "conflicts": [],
        "errors": [],
        "dry_run": args.dry_run,
    }
    stats = CrosslinkStats()
    session_cache: dict[tuple[str, str, str], str] = {}
    processed_since_save = [0]

    do_en_zh = not args.zh_to_en_only
    do_zh_en = not args.en_to_zh_only

    try:
        if do_en_zh:
            print("[phase] en → zh", flush=True)
            _crosslink_en_to_zh(
                en_map,
                zh_map,
                overwrite=args.overwrite,
                delay=args.delay,
                max_items=args.max,
                dry_run=args.dry_run,
                cp=cp,
                session_cache=session_cache,
                stats=stats,
                report=report,
                checkpoint_path=args.checkpoint,
                processed_since_save=processed_since_save,
            )
        if do_zh_en:
            print("[phase] zh → en", flush=True)
            _crosslink_zh_to_en(
                en_map,
                zh_map,
                overwrite=args.overwrite,
                delay=args.delay,
                max_items=args.max,
                dry_run=args.dry_run,
                cp=cp,
                session_cache=session_cache,
                stats=stats,
                report=report,
                checkpoint_path=args.checkpoint,
                processed_since_save=processed_since_save,
            )
    except KeyboardInterrupt:
        print("\n[interrupt] сохраняю checkpoint…", flush=True)
        cp.save(args.checkpoint)
        if not args.dry_run and stats.added:
            save_track_map(args.library_en, "en", en_map)
            save_track_map(args.library_zh, "zh", zh_map)
            print("[interrupt] частично записаны словари")
        print(f"[checkpoint] {args.checkpoint} — продолжите с --resume")
        return 130

    cp.save(args.checkpoint)

    print(
        f"[stats] добавлено: {stats.added}, Google: {stats.google_calls}, "
        f"кэш: {stats.cache_hits}, уже готово: {stats.skipped_exists}, "
        f"checkpoint: {stats.skipped_done}, конфликтов: {stats.skipped_conflict}, "
        f"пропусков: {stats.skipped_invalid}, ошибок: {len(report['errors'])}"
    )
    if report["conflicts"][:5]:
        print("[warn] примеры конфликтов (зеркальный ключ уже с другим ru):")
        for item in report["conflicts"][:5]:
            print(f"  - {item}")

    if not args.dry_run and stats.added:
        save_track_map(args.library_en, "en", en_map)
        save_track_map(args.library_zh, "zh", zh_map)
        print(f"[write] {args.library_en}")
        print(f"[write] {args.library_zh}")

    report["stats"] = {
        "added": stats.added,
        "google_calls": stats.google_calls,
        "cache_hits": stats.cache_hits,
        "skipped_exists": stats.skipped_exists,
        "skipped_done": stats.skipped_done,
        "skipped_conflict": stats.skipped_conflict,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[report] {args.report}")
    print(f"[checkpoint] {args.checkpoint}")
    return 1 if report["errors"] and not stats.added else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Зеркальный ключ en↔zh через Google; ru копируется из исходной записи. "
            "Checkpoint: --resume / --reset-checkpoint"
        )
    )
    ap.add_argument("--library-en", type=Path, default=DICT_EN)
    ap.add_argument("--library-zh", type=Path, default=DICT_ZH)
    ap.add_argument("--en-to-zh-only", action="store_true", help="Только en → zh")
    ap.add_argument("--zh-to-en-only", action="store_true", help="Только zh → en")
    ap.add_argument("--overwrite", action="store_true", help="Перезаписать другой ru у зеркального ключа")
    ap.add_argument("--delay", type=float, default=0.12, help="Пауза после запроса Google")
    ap.add_argument("--max", type=int, default=None, help="Макс. новых записей (на оба направления суммарно)")
    ap.add_argument("--dry-run", action="store_true", help="Не писать словари")
    ap.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    ap.add_argument("--resume", action="store_true", help="Продолжить с checkpoint (пропустить done_*)")
    ap.add_argument("--reset-checkpoint", action="store_true", help="Удалить checkpoint и начать заново")
    ap.add_argument(
        "--report",
        type=Path,
        default=REPORTS_DIR / "crosslink_translation_libraries.json",
    )
    return _run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
