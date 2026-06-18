#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Чтение/запись translation_library_ru_*.json по треку."""

from __future__ import annotations

import json
import time
from pathlib import Path

from source_resolve import Track, is_placeholder_ru

SCHEMA_VERSION = 2

PENDING_KIND = "pending_no_ru"


def default_pending_path(tools_root: Path, track: Track) -> Path:
    base = tools_root / "data" / "pending"
    name = "translation_library_ru_en_pending.json" if track == "en" else "translation_library_ru_zh-rCN_pending.json"
    return base / name


def order_string_map(string_map: dict[str, str]) -> dict[str, str]:
    """Сначала реальные переводы по алфавиту ключа, затем заглушки (« ») — тоже по алфавиту."""
    real_keys = sorted(k for k, v in string_map.items() if not is_placeholder_ru(v))
    ph_keys = sorted(k for k, v in string_map.items() if is_placeholder_ru(v))
    ordered: dict[str, str] = {}
    for k in real_keys:
        ordered[k] = string_map[k]
    for k in ph_keys:
        ordered[k] = string_map[k]
    return ordered


def load_track_map(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    sm = data.get("string_map")
    if not isinstance(sm, dict):
        raise ValueError(f"{path}: ожидается объект string_map")
    return {str(k): str(v) for k, v in sm.items()}


def save_track_map(
    path: Path,
    track: Track,
    string_map: dict[str, str],
    *,
    meta: dict | None = None,
    merge_meta: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged_meta: dict = {}
    if merge_meta and path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            prev = data.get("meta")
            if isinstance(prev, dict):
                merged_meta.update(prev)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    if meta:
        merged_meta.update(meta)
    track_label = "en" if track == "en" else "zh-rCN"
    payload: dict = {
        "schema_version": SCHEMA_VERSION,
        "track": track_label,
        "string_map": order_string_map(string_map),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if merged_meta:
        payload["meta"] = merged_meta
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
