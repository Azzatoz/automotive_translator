#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перевод TOR-словаря AdsHmi: tor_dictionary_zh.json → tor_dictionary_ru.json

Строки с разделителем ;; переводятся по частям (как в HMI), чтобы «请接管;;…»
давало согласованные подписи.

Зависимость: pip install deep-translator (см. tools/run_translate_tor_dictionary_ru.sh)

Checkpoint: tools/checkpoints/tor_dictionary_ru_segment_map.json
запустите с теми же аргументами (без --no-resume).
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None  # type: ignore[misc, assignment]

TRANSLATED_ROOT = Path(__file__).resolve().parents[2] / "Translated"
TOOLS_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    TRANSLATED_ROOT
    / "AdsHmi_src"
    / "assets"
    / "P_Public"
    / "TORConfig"
    / "tor_dictionary_zh.json"
)
DEFAULT_OUTPUT = (
    TRANSLATED_ROOT
    / "AdsHmi_src"
    / "assets"
    / "P_Public"
    / "TORConfig"
    / "tor_dictionary_ru.json"
)
DEFAULT_CHECKPOINT = TOOLS_ROOT / "checkpoints" / "tor_dictionary_ru_segment_map.json"

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufadf]")
_PLACEHOLDER_PATTERN = re.compile(
    r"(%(?:\d+\$)?(?:s|d|u|f|x|X|o|c|e|E|g|G|h|H))"
)
_EXTRA_ESCAPES = re.compile(r"(\\n|\\'|\\\"|\\\\)")


def _protect_specials(text: str) -> tuple[str, dict[str, str]]:
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


def _collect_cjk_segments(dictionary: list[dict[str, Any]], out: set[str]) -> None:
    for entry in dictionary:
        t = entry.get("text")
        if not isinstance(t, str) or not t:
            continue
        for seg in t.split(";;"):
            if _CJK_RE.search(seg):
                out.add(seg)


def _apply_segment_map(text: str, seg_map: dict[str, str]) -> str:
    parts = text.split(";;")
    built: list[str] = []
    for p in parts:
        if _CJK_RE.search(p):
            built.append(seg_map.get(p, p))
        else:
            built.append(p)
    return ";;".join(built)


def _load_checkpoint(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    sm = data.get("segment_map")
    if not isinstance(sm, dict):
        return {}
    return {str(k): str(v) for k, v in sm.items()}


def _save_checkpoint(path: Path, segment_map: dict[str, str], meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"segment_map": dict(sorted(segment_map.items())), **meta}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    p = argparse.ArgumentParser(description="TOR dictionary zh → ru (AdsHmi)")
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Исходный JSON")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Куда записать ru JSON")
    p.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_CHECKPOINT,
        help="Файл сегментного словаря для возобновления",
    )
    p.add_argument("--source-lang", default="zh-CN")
    p.add_argument("--target-lang", default="ru")
    p.add_argument("--delay", type=float, default=0.08, help="Пауза между запросами (сек)")
    p.add_argument(
        "--save-every",
        type=int,
        default=25,
        help="Сохранять checkpoint после каждых N новых сегментов",
    )
    p.add_argument(
        "--no-resume",
        action="store_true",
        help="Не читать checkpoint (переводить все CJK-сегменты заново)",
    )
    args = p.parse_args()

    inp = args.input.expanduser().resolve()
    if not inp.is_file():
        raise SystemExit(f"Нет файла: {inp}")

    raw = json.loads(inp.read_text(encoding="utf-8"))
    dictionary = raw.get("dictionary")
    if not isinstance(dictionary, list):
        raise SystemExit("Ожидался ключ верхнего уровня 'dictionary' (массив)")

    segment_map: dict[str, str] = {}
    if not args.no_resume:
        segment_map = _load_checkpoint(args.checkpoint)

    segments: set[str] = set()
    _collect_cjk_segments(dictionary, segments)
    pending = sorted(se for se in segments if se not in segment_map)
    total_pending = len(pending)
    print(
        f"[tor_dictionary] уникальных CJK-сегментов: {len(segments)}, "
        f"в checkpoint: {len(segments) - total_pending}, осталось: {total_pending}",
        file=sys.stderr,
    )

    meta = {
        "source_lang": args.source_lang,
        "target_lang": args.target_lang,
        "source_file": str(inp),
    }

    for i, seg in enumerate(pending):
        try:
            segment_map[seg] = _translate_with_google(seg, args.source_lang, args.target_lang)
        except Exception as e:
            print(f"[warn] сегмент {seg[:48]!r}…: {e}", file=sys.stderr)
            segment_map[seg] = seg
        time.sleep(max(0.0, args.delay))
        done_n = i + 1
        if done_n % max(1, args.save_every) == 0:
            _save_checkpoint(args.checkpoint, segment_map, meta)
            print(f"[checkpoint] {done_n}/{total_pending}", file=sys.stderr)

    if total_pending:
        _save_checkpoint(args.checkpoint, segment_map, meta)

    out_obj = copy.deepcopy(raw)
    out_obj["language"] = "ru"
    if isinstance(out_obj.get("dictionary"), list):
        for entry in out_obj["dictionary"]:
            if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                entry["text"] = _apply_segment_map(entry["text"], segment_map)

    out_path = args.output.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(out_obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OK: {out_path} (записей: {len(dictionary)})", file=sys.stderr)


if __name__ == "__main__":
    main()
