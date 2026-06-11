from __future__ import annotations

import json
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gui_pkg.config import REPO_ROOT, TRACKS, TRANSLATABLE_XML

sys.path.insert(0, str(REPO_ROOT / "library"))
from source_resolve import is_placeholder_ru  # noqa: E402


def display_module_name(folder_name: str) -> str:
    if folder_name.endswith("_src"):
        return folder_name[:-4]
    return folder_name


def discover_modules(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    modules: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "res").is_dir():
            modules.append(child)
    return modules


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
            "status": "unprocessed",
        }

    total = 0
    placeholders = 0
    for xml_name in TRANSLATABLE_XML:
        xml_path = values_ru / xml_name
        if not xml_path.is_file():
            continue
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError:
            continue
        for el in root.iter():
            if el.tag not in ("string", "item"):
                continue
            total += 1
            if el.text is None or is_placeholder_ru(el.text):
                placeholders += 1

    translated = total - placeholders
    if conflicts > 0:
        status = "conflicts"
    elif placeholders > 0:
        status = "placeholders"
    elif total > 0:
        status = "ready"
    else:
        status = "unprocessed"

    return {
        "total": total,
        "translated": translated,
        "placeholders": placeholders,
        "conflicts": conflicts,
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
    if status == "ready":
        return "✓ готов"
    return "не обработан"


@dataclass
class ModuleInfo:
    path: Path
    name: str
    display: str
    stats: dict[str, Any] = field(default_factory=dict)
