"""Поиск похожих ключей в словаре."""

from __future__ import annotations

import difflib
import json
from pathlib import Path

from gui_pkg.config import DICT_EN, DICT_ZH


def search_similar_in_library(
    query: str,
    *,
    track: str,
    limit: int = 25,
) -> list[tuple[str, str]]:
    """(исходник, ru) — подстрока или fuzzy match."""
    q = (query or "").strip()
    if not q:
        return []
    path = DICT_EN if track == "en" else DICT_ZH
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    smap = data.get("string_map") or {}
    if not isinstance(smap, dict):
        return []
    q_lower = q.lower()
    exact_sub: list[tuple[str, str]] = []
    for src, ru in smap.items():
        if not src or not isinstance(ru, str):
            continue
        if q_lower in src.lower():
            exact_sub.append((src, ru))
    if len(exact_sub) >= limit:
        return exact_sub[:limit]
    keys = list(smap.keys())
    close = difflib.get_close_matches(q, keys, n=limit, cutoff=0.45)
    seen = {s for s, _ in exact_sub}
    out = list(exact_sub)
    for src in close:
        if src in seen:
            continue
        ru = smap.get(src)
        if isinstance(ru, str):
            out.append((src, ru))
        if len(out) >= limit:
            break
    return out[:limit]
