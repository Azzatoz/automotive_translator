"""Поиск и правка записей в словарях en/zh."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from gui_pkg.config import DICT_EN, DICT_ZH, REPO_ROOT
from gui_pkg.dictionary_data import load_google_fill_index
from gui_pkg.scanner import discover_modules, display_module_name, load_conflicts_cache, modules_in_conflict

sys.path.insert(0, str(REPO_ROOT / "library"))
from library_persist import load_track_map, save_track_map  # noqa: E402
from source_resolve import SourceVariant, Track, apply_ru_to_track_maps, is_placeholder_ru  # noqa: E402


@dataclass(frozen=True)
class DictSearchHit:
    track: str  # en | zh-CN
    source: str
    ru: str
    modules: tuple[str, ...] = ()
    is_placeholder: bool = False

    @property
    def track_key(self) -> Track:
        return "zh" if self.track.startswith("zh") else "en"


def dictionary_path_for_track_key(track: str) -> Path:
    return DICT_ZH if track.startswith("zh") else DICT_EN


def build_module_index_from_reports() -> dict[str, set[str]]:
    """source → имена модулей из отчётов конфликтов и Google fill."""
    index: dict[str, set[str]] = {}
    for items in load_conflicts_cache().values():
        for item in items:
            src = str(item.get("source") or "").strip()
            if not src:
                continue
            mods = modules_in_conflict(item)
            if mods:
                index.setdefault(src, set()).update(mods)
    google = load_google_fill_index()
    for mod, sources in google.sources_by_module.items():
        for src in sources:
            if src:
                index.setdefault(src, set()).add(mod)
    return index


def scan_project_module_index(project_root: Path) -> dict[str, set[str]]:
    """source → модули проекта (сканирование values-* в APK)."""
    from gui_pkg.placeholder_editor import collect_all_module_rows

    index: dict[str, set[str]] = {}
    if not project_root.is_dir():
        return index
    for module_path in discover_modules(project_root):
        name = display_module_name(module_path.name)
        try:
            rows = collect_all_module_rows(module_path)
        except Exception:
            continue
        for row in rows:
            src = (row.source or "").strip()
            if src:
                index.setdefault(src, set()).add(name)
    return index


def merge_module_indexes(*indexes: dict[str, set[str]]) -> dict[str, set[str]]:
    merged: dict[str, set[str]] = {}
    for idx in indexes:
        for src, mods in idx.items():
            merged.setdefault(src, set()).update(mods)
    return merged


def load_dictionary_hits(module_index: dict[str, set[str]] | None = None) -> list[DictSearchHit]:
    idx = module_index or {}
    hits: list[DictSearchHit] = []
    for track, path in (("en", DICT_EN), ("zh-CN", DICT_ZH)):
        if not path.is_file():
            continue
        try:
            smap = load_track_map(path)
        except (OSError, ValueError):
            continue
        for src, ru in smap.items():
            mods = tuple(sorted(idx.get(src, ())))
            hits.append(
                DictSearchHit(
                    track=track,
                    source=src,
                    ru=ru or "",
                    modules=mods,
                    is_placeholder=is_placeholder_ru(ru),
                )
            )
    hits.sort(key=lambda h: (h.track, h.source.lower()))
    return hits


def filter_hits(
    hits: list[DictSearchHit],
    query: str,
    *,
    track: str = "all",
    field: str = "all",
    placeholders_only: bool = False,
    limit: int = 500,
) -> list[DictSearchHit]:
    q = (query or "").strip().lower()
    out: list[DictSearchHit] = []
    for hit in hits:
        if placeholders_only and not hit.is_placeholder:
            continue
        if track != "all" and hit.track != track:
            continue
        if q:
            if field == "source":
                if q not in hit.source.lower():
                    continue
            elif field == "ru":
                if q not in hit.ru.lower():
                    continue
            elif field == "module":
                if not any(q in mod.lower() for mod in hit.modules):
                    continue
            else:
                in_src = q in hit.source.lower()
                in_ru = q in hit.ru.lower()
                in_mod = any(q in mod.lower() for mod in hit.modules)
                if not (in_src or in_ru or in_mod):
                    continue
        out.append(hit)
        if len(out) >= limit:
            break
    return out


def save_dictionary_translation(hit: DictSearchHit, new_ru: str) -> None:
    path = dictionary_path_for_track_key(hit.track)
    track_maps: dict[Track, dict[str, str]] = {hit.track_key: load_track_map(path) if path.is_file() else {}}
    if hit.source not in track_maps[hit.track_key]:
        raise KeyError(hit.source)
    variants = [
        SourceVariant(track=hit.track_key, text=hit.source, locale="dictionary"),
    ]
    dirty = apply_ru_to_track_maps(track_maps, variants, new_ru)
    if not dirty:
        raise ValueError(
            "перевод не принят: заглушка, техническая строка или несовместим с исходником"
        )
    save_track_map(path, hit.track_key, track_maps[hit.track_key])
