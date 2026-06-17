"""Чтение словарей, pending и отчёта Google fill."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from gui_pkg.config import DICT_EN, DICT_ZH, REPO_ROOT, REPORTS_DIR

sys.path.insert(0, str(REPO_ROOT / "library"))
from library_persist import load_track_map  # noqa: E402
from source_resolve import is_placeholder_ru  # noqa: E402

GOOGLE_FILL_REPORT = REPORTS_DIR / "fill_values_ru_google_report.json"

PENDING_FILES: list[tuple[str, Path]] = [
    ("en", REPO_ROOT / "data" / "pending" / "translation_library_ru_en_pending.json"),
    ("zh-CN", REPO_ROOT / "data" / "pending" / "translation_library_ru_zh-rCN_pending.json"),
]

DICT_FILES: list[tuple[str, Path]] = [
    ("en", DICT_EN),
    ("zh-CN", DICT_ZH),
]


@dataclass
class DictListRow:
    track: str
    source: str
    ru: str
    kind: str  # placeholder | pending | google


@dataclass
class GoogleFillIndex:
    modules: set[str] = field(default_factory=set)
    sources_by_module: dict[str, set[str]] = field(default_factory=dict)
    resources_by_module: dict[str, set[str]] = field(default_factory=dict)
    entries: list[dict] = field(default_factory=list)

    def sources_for(self, module_name: str) -> set[str]:
        return self.sources_by_module.get(module_name, set())

    def resources_for(self, module_name: str) -> set[str]:
        return self.resources_by_module.get(module_name, set())

    def matches_row(self, module_name: str, *, source: str, resource_id: str) -> bool:
        sources = self.sources_by_module.get(module_name)
        if sources and source in sources:
            return True
        resources = self.resources_by_module.get(module_name)
        if not resources:
            return False
        rid = resource_id
        for key in resources:
            if rid in key or key.endswith(f"/{rid}"):
                return True
        return False


def open_path_in_system(path: Path) -> bool:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved)))


def dictionary_path_for_track(track: str) -> Path:
    if track.startswith("zh"):
        return DICT_ZH
    return DICT_EN


def load_dictionary_placeholders() -> list[DictListRow]:
    rows: list[DictListRow] = []
    for track, path in DICT_FILES:
        if not path.is_file():
            continue
        try:
            sm = load_track_map(path)
        except (OSError, json.JSONDecodeError):
            continue
        for src, ru in sm.items():
            if is_placeholder_ru(ru):
                rows.append(
                    DictListRow(track=track, source=src, ru=ru or "", kind="placeholder")
                )
    rows.sort(key=lambda r: (r.track, r.source.lower()))
    return rows


def load_pending_rows() -> list[DictListRow]:
    rows: list[DictListRow] = []
    for track, path in PENDING_FILES:
        if not path.is_file():
            continue
        try:
            sm = load_track_map(path)
        except (OSError, json.JSONDecodeError):
            continue
        for src, ru in sm.items():
            rows.append(
                DictListRow(
                    track=track,
                    source=src,
                    ru=ru or "",
                    kind="pending",
                )
            )
    rows.sort(key=lambda r: (r.track, r.source.lower()))
    return rows


def load_google_fill_index(path: Path | None = None) -> GoogleFillIndex:
    report_path = path or GOOGLE_FILL_REPORT
    idx = GoogleFillIndex()
    if not report_path.is_file():
        return idx
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return idx
    entries = data.get("google_translations") or []
    if not isinstance(entries, list):
        return idx
    idx.entries = [e for e in entries if isinstance(e, dict)]
    for entry in idx.entries:
        mod = str(entry.get("module") or "")
        src = str(entry.get("source") or "")
        res = str(entry.get("resource") or "")
        if not mod:
            continue
        idx.modules.add(mod)
        if src:
            idx.sources_by_module.setdefault(mod, set()).add(src)
        if res:
            idx.resources_by_module.setdefault(mod, set()).add(res)
    return idx


def load_google_rows(index: GoogleFillIndex | None = None) -> list[DictListRow]:
    idx = index or load_google_fill_index()
    rows: list[DictListRow] = []
    for entry in idx.entries:
        mod = str(entry.get("module") or "")
        src = str(entry.get("source") or "")
        ru = str(entry.get("ru") or "")
        rows.append(
            DictListRow(
                track=mod,
                source=src,
                ru=ru,
                kind="google",
            )
        )
    rows.sort(key=lambda r: (r.track.lower(), r.source.lower()))
    return rows
