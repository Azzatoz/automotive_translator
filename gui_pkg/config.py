from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_ORG = "AutomotiveTranslator"
SETTINGS_APP = "GUI"
TRANSLATABLE_XML = ("strings.xml", "plurals.xml", "arrays.xml")

TRACKS: list[tuple[str, Path, Path, Path]] = [
    (
        "en",
        REPO_ROOT / "reports" / "translation_library_ru_en_conflicts.json",
        REPO_ROOT / "translation_library_ru_en.json",
        REPO_ROOT / "library" / "translation_library_ru_en_resolutions.json",
    ),
    (
        "zh-CN",
        REPO_ROOT / "reports" / "translation_library_ru_zh-rCN_conflicts.json",
        REPO_ROOT / "translation_library_ru_zh-rCN.json",
        REPO_ROOT / "library" / "translation_library_ru_zh-rCN_resolutions.json",
    ),
]

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
