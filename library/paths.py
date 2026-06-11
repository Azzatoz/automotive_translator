"""Канонические пути репозитория automotive_translator."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

TrackName = Literal["en", "zh"]

REPO_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = REPO_ROOT / "data"
DICTIONARIES_DIR = DATA_DIR / "dictionaries"
PENDING_DIR = DATA_DIR / "pending"
RESOLUTIONS_DIR = DATA_DIR / "resolutions"

REPORTS_DIR = REPO_ROOT / "reports"
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIBRARY_DIR = REPO_ROOT / "library"
LAYOUT_DIR = REPO_ROOT / "layout"
FUNCTIONS_DIR = REPO_ROOT / "functions"
TOR_DIR = REPO_ROOT / "tor"
DOCS_DIR = REPO_ROOT / "docs"
REQUIREMENTS_DIR = REPO_ROOT / "requirements"
CHECKPOINTS_DIR = REPO_ROOT / "checkpoints"

DICT_EN = DICTIONARIES_DIR / "translation_library_ru_en.json"
DICT_ZH = DICTIONARIES_DIR / "translation_library_ru_zh-rCN.json"
DICT_LEGACY = DICTIONARIES_DIR / "translation_library_ru.json"

PENDING_EN = PENDING_DIR / "translation_library_ru_en_pending.json"
PENDING_ZH = PENDING_DIR / "translation_library_ru_zh-rCN_pending.json"

RESOLUTIONS_LEGACY = RESOLUTIONS_DIR / "translation_library_ru_resolutions.json"
RESOLUTIONS_EN = RESOLUTIONS_DIR / "translation_library_ru_en_resolutions.json"
RESOLUTIONS_ZH = RESOLUTIONS_DIR / "translation_library_ru_zh-rCN_resolutions.json"

CONFLICTS_EN = REPORTS_DIR / "translation_library_ru_en_conflicts.json"
CONFLICTS_ZH = REPORTS_DIR / "translation_library_ru_zh-rCN_conflicts.json"
CONFLICTS_LEGACY = REPORTS_DIR / "translation_library_ru_conflicts.json"

REQ_GUI = REQUIREMENTS_DIR / "gui.txt"
REQ_FILL = REQUIREMENTS_DIR / "fill-values-ru.txt"

SCRIPT_FILL = SCRIPTS_DIR / "fill_values_ru_from_library.py"
SCRIPT_SORT = SCRIPTS_DIR / "sort_translation_libraries.py"


def dictionaries_dir(tools_root: Path | None = None) -> Path:
    return (tools_root or REPO_ROOT) / "data" / "dictionaries"


def pending_dir(tools_root: Path | None = None) -> Path:
    return (tools_root or REPO_ROOT) / "data" / "pending"


def dictionary_path(track: TrackName, tools_root: Path | None = None) -> Path:
    base = dictionaries_dir(tools_root)
    if track == "en":
        return base / "translation_library_ru_en.json"
    return base / "translation_library_ru_zh-rCN.json"


def pending_path(track: TrackName, tools_root: Path | None = None) -> Path:
    base = pending_dir(tools_root)
    if track == "en":
        return base / "translation_library_ru_en_pending.json"
    return base / "translation_library_ru_zh-rCN_pending.json"
