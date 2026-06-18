from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from gui_pkg.config import TRACKS
from gui_pkg.module_align import count_module_dict_mismatches
from gui_pkg.placeholder_editor import module_translation_stats


def display_module_name(folder_name: str) -> str:
    if folder_name.endswith("_src"):
        return folder_name[:-4]
    return folder_name


def apk_entry_name(apk_filename: str) -> str:
    return f"@apk:{apk_filename}"


def is_artifact_apk(filename: str) -> bool:
    """Промежуточные/собранные APK — не показываем в списке проекта."""
    lower = filename.lower()
    if lower.endswith("-signed.apk") or lower.endswith("-aligned.apk"):
        return True
    if filename.endswith("_src.apk"):
        return True
    return False


def src_stem_from_dir(src_name: str) -> str:
    if src_name.endswith("_src"):
        return src_name[:-4]
    return src_name


def apk_only_stats() -> dict[str, Any]:
    return {
        "total": 0,
        "translated": 0,
        "placeholders": 0,
        "conflicts": 0,
        "dict_mismatches": 0,
        "status": "apk_only",
    }


def discover_modules(root: Path) -> list[Path]:
    """Только распакованные *_src (для скриптов и обратной совместимости)."""
    return [info.path for info in discover_project_entries(root) if info.kind == "src"]


def discover_project_entries(root: Path) -> list[ModuleInfo]:
    """Модули *_src и нераспакованные .apk в папке проекта."""
    if not root.is_dir():
        return []

    src_dirs: dict[str, Path] = {}
    apks: dict[str, Path] = {}

    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "res").is_dir():
            src_dirs[child.name] = child
        elif child.is_file() and child.suffix.lower() == ".apk":
            if not is_artifact_apk(child.name):
                apks[child.stem] = child

    entries: list[ModuleInfo] = []
    paired_stems: set[str] = set()

    for src_name in sorted(src_dirs):
        src_path = src_dirs[src_name]
        stem = src_stem_from_dir(src_name)
        apk_path = apks.get(stem)
        if apk_path is not None:
            paired_stems.add(stem)
        entries.append(
            ModuleInfo(
                path=src_path,
                name=src_name,
                display=display_module_name(src_name),
                kind="src",
                apk_path=apk_path,
            )
        )

    for stem in sorted(apks):
        if stem in paired_stems:
            continue
        apk_path = apks[stem]
        entries.append(
            ModuleInfo(
                path=apk_path,
                name=apk_entry_name(apk_path.name),
                display=stem,
                kind="apk",
                apk_path=apk_path,
                stats=apk_only_stats(),
            )
        )

    return entries


def prune_conflicts_file(conflicts_path: Path, sources: set[str]) -> int:
    """Убрать решённые конфликты из отчёта reports/. Возвращает число удалённых."""
    if not sources or not conflicts_path.is_file():
        return 0
    try:
        data = json.loads(conflicts_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    conflicts = data.get("conflicts") or []
    if not isinstance(conflicts, list):
        return 0
    keep = [c for c in conflicts if str(c.get("source") or "") not in sources]
    removed = len(conflicts) - len(keep)
    if removed <= 0:
        return 0
    data["conflicts"] = keep
    meta = data.get("meta")
    if isinstance(meta, dict):
        meta["pruned_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        meta["conflict_count"] = len(keep)
    conflicts_path.parent.mkdir(parents=True, exist_ok=True)
    conflicts_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return removed


def load_conflicts_cache() -> dict[str, list[dict[str, Any]]]:
    cache: dict[str, list[dict[str, Any]]] = {}
    for track, conflicts_path, _, _ in TRACKS:
        if not conflicts_path.is_file():
            cache[track] = []
            continue
        try:
            data = json.loads(conflicts_path.read_text(encoding="utf-8"))
            cache[track] = list(data.get("conflicts") or [])
        except (OSError, json.JSONDecodeError):
            cache[track] = []
    return cache


def modules_in_conflict(item: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for mods in item.get("modules") or []:
        if isinstance(mods, str):
            found.add(mods)
    translations = item.get("translations") or {}
    if isinstance(translations, dict):
        for mod_list in translations.values():
            if isinstance(mod_list, list):
                for m in mod_list:
                    if isinstance(m, str):
                        found.add(m)
    return found


def count_conflicts_for_module(
    module_folder: str,
    conflicts_cache: dict[str, list[dict[str, Any]]] | None = None,
) -> int:
    cache = conflicts_cache if conflicts_cache is not None else load_conflicts_cache()
    count = 0
    for items in cache.values():
        for item in items:
            if module_folder in modules_in_conflict(item):
                count += 1
    return count


def resolve_module_status(
    *,
    total: int,
    placeholders: int,
    conflicts: int,
    dict_mismatches: int,
) -> str:
    if conflicts > 0:
        return "conflicts"
    if placeholders > 0:
        return "placeholders"
    if total > 0:
        if dict_mismatches > 0:
            return "ready_drift"
        return "ready"
    return "unprocessed"


def scan_module(
    module_path: Path,
    conflicts_cache: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    values_ru = module_path / "res" / "values-ru"
    folder = module_path.name
    conflicts = count_conflicts_for_module(folder, conflicts_cache)

    if not values_ru.is_dir():
        return {
            "total": 0,
            "translated": 0,
            "placeholders": 0,
            "conflicts": conflicts,
            "dict_mismatches": 0,
            "status": "unprocessed",
        }

    total, translated, placeholders = module_translation_stats(module_path)
    dict_mismatches = count_module_dict_mismatches(module_path)
    status = resolve_module_status(
        total=total,
        placeholders=placeholders,
        conflicts=conflicts,
        dict_mismatches=dict_mismatches,
    )

    return {
        "total": total,
        "translated": translated,
        "placeholders": placeholders,
        "conflicts": conflicts,
        "dict_mismatches": dict_mismatches,
        "status": status,
    }


def badge_text(stats: dict[str, Any]) -> str:
    status = stats.get("status", "unprocessed")
    if status == "conflicts":
        n = stats.get("conflicts", 0)
        if n == 1:
            return "1 конфликт"
        if 2 <= n % 10 <= 4 and n not in (12, 13, 14):
            return f"{n} конфликта"
        return f"{n} конфликтов"
    if status == "placeholders":
        n = stats.get("placeholders", 0)
        if n == 1:
            return "1 заглушка"
        if 2 <= n % 10 <= 4 and n not in (12, 13, 14):
            return f"{n} заглушки"
        return f"{n} заглушек"
    if status == "ready_drift":
        n = int(stats.get("dict_mismatches", 0))
        if n == 1:
            return "✓ готов · 1 расхожд."
        if 2 <= n % 10 <= 4 and n not in (12, 13, 14):
            return f"✓ готов · {n} расхожд."
        return f"✓ готов · {n} расхожд."
    if status == "ready":
        return "✓ готов"
    if status == "apk_only":
        return "не распакован"
    return "не обработан"


def aggregate_project_stats(modules: dict[str, ModuleInfo]) -> dict[str, int]:
    """Суммарная статистика по всем модулям проекта."""
    total = translated = placeholders = conflicts = dict_mismatches = 0
    module_count = len(modules)
    src_modules = apk_only = with_placeholders = with_conflicts = ready = ready_drift = 0
    for info in modules.values():
        if info.kind == "apk":
            apk_only += 1
            continue
        src_modules += 1
        stats = info.stats or {}
        total += int(stats.get("total", 0))
        translated += int(stats.get("translated", 0))
        placeholders += int(stats.get("placeholders", 0))
        conflicts += int(stats.get("conflicts", 0))
        dict_mismatches += int(stats.get("dict_mismatches", 0))
        status = stats.get("status", "unprocessed")
        if status == "placeholders":
            with_placeholders += 1
        elif status == "conflicts":
            with_conflicts += 1
        elif status == "ready_drift":
            ready_drift += 1
            ready += 1
        elif status == "ready":
            ready += 1
    return {
        "modules": module_count,
        "src_modules": src_modules,
        "apk_only": apk_only,
        "total": total,
        "translated": translated,
        "placeholders": placeholders,
        "conflicts": conflicts,
        "dict_mismatches": dict_mismatches,
        "with_placeholders": with_placeholders,
        "with_conflicts": with_conflicts,
        "ready_modules": ready,
        "ready_drift_modules": ready_drift,
    }


@dataclass
class ModuleInfo:
    path: Path
    name: str
    display: str
    kind: Literal["src", "apk"] = "src"
    apk_path: Path | None = None
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def is_src(self) -> bool:
        return self.kind == "src"

    @property
    def is_apk_only(self) -> bool:
        return self.kind == "apk"

    def resolved_apk_path(self) -> Path | None:
        if self.kind == "apk":
            return self.path
        return self.apk_path
