from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_LIB = _REPO / "library"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from paths import (  # noqa: E402
    CONFLICTS_EN,
    CONFLICTS_ZH,
    DICT_EN,
    DICT_ZH,
    LAYOUT_DIR,
    LIBRARY_DIR,
    REPO_ROOT,
    REPORTS_DIR,
    RESOLUTIONS_EN,
    RESOLUTIONS_ZH,
    SCRIPTS_DIR,
)

SETTINGS_ORG = "AutomotiveTranslator"
SETTINGS_APP = "GUI"
TRANSLATABLE_XML = ("strings.xml", "plurals.xml", "arrays.xml")

TRACKS: list[tuple[str, Path, Path, Path]] = [
    ("en", CONFLICTS_EN, DICT_EN, RESOLUTIONS_EN),
    ("zh-CN", CONFLICTS_ZH, DICT_ZH, RESOLUTIONS_ZH),
]

# Индексы вкладок QTabWidget в MainWindow (порядок addTab)
TAB_OVERVIEW = 0
TAB_ACTIONS = 1
TAB_CONFLICTS = 2
TAB_PENDING = 3
TAB_LOG = 4

ROOT_PRESETS: list[tuple[str, Path]] = [
    ("../Translated", REPO_ROOT.parent / "Translated"),
    (
        "../../Rest 4.1.1/Translated",
        REPO_ROOT.parent.parent / "Rest 4.1.1" / "Translated",
    ),
    (
        "../../Dorest 3.2.0/dorest 320",
        REPO_ROOT.parent.parent / "Dorest 3.2.0" / "dorest 320",
    ),
    (
        "D:/Voyah/Dorest translate/Translated",
        Path("D:/Voyah/Dorest translate/Translated"),
    ),
]

__all__ = [
    "LAYOUT_DIR",
    "LIBRARY_DIR",
    "REPO_ROOT",
    "REPORTS_DIR",
    "RESOLUTIONS_EN",
    "RESOLUTIONS_ZH",
    "ROOT_PRESETS",
    "SCRIPTS_DIR",
    "SETTINGS_APP",
    "SETTINGS_ORG",
    "TAB_ACTIONS",
    "TAB_CONFLICTS",
    "TAB_LOG",
    "TAB_OVERVIEW",
    "TAB_PENDING",
    "TRACKS",
    "TRANSLATABLE_XML",
]
