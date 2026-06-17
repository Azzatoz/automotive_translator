#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Общая логика выбора исходника (en / zh) для collect и fill."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Literal

Track = Literal["en", "zh"]

PLACEHOLDER_RU = " "

# Доля имён ресурсов в values-en от values: при ≥30% модуль считается en-ориентированным.
VALUES_EN_MIN_COVERAGE = 0.30

TRANSLATABLE_XML = ("strings.xml", "plurals.xml", "arrays.xml")
_NAMED_RESOURCE_TAGS = frozenset({"string", "plurals", "string-array"})

_FQCN_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", re.I)
_JAVA_CLASS_RE = re.compile(r"^[\w.]+\$[\w]+$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
_TIME_PATTERN_RE = re.compile(r"^h{1,2}:mm", re.I)
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_SIGNED_INT_RE = re.compile(r"^-?\d+$")
_DECIMAL_LITERAL_RE = re.compile(r"^-?\d*\.\d+$")
_CONTENT_URI_RE = re.compile(r"^(?:content|android\.resource)://", re.I)
_URI_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
_ANDROID_COMPONENT_RE = re.compile(r"^[a-z][\w.]*(?:/[\w.$]+)+$", re.I)
_SNAKE_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]+$")
_COMMA_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*(?:,[a-z][a-z0-9_]*)+$")
_FONT_FAMILY_RE = re.compile(r"^google-sans", re.I)
_HYPHENATED_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")
_ANDROID_FORMAT_PREFIX_RE = re.compile(r"^%[\d$]*[dfs@]")
# 2–3 буквы: коды локали (de, deu), не короткие англ. слова
_SHORT_ASCII_WORDS = frozenset(
    "a an am as at be by do go he if in is it me my no of ok on or so to up us we".split()
)
_LOCALE_CODE_RE = re.compile(r"^[a-z]{2,3}$")
# @android:string/foo, @string/foo, @com.pkg:drawable/icon
_ANDROID_RESOURCE_REF_RE = re.compile(
    r"^@(?:(?:android|[\w.]+):)?"
    r"(?:string|drawable|plurals|array|layout|color|dimen|bool|integer|"
    r"fraction|attr|style|raw|xml|anim|mipmap|font)/[\w.]+$",
    re.IGNORECASE,
)
_ASSIST_NAME_RE = re.compile(r"^\{assistName:")
CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufadf]")
CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")
# Не английский исходник для en-трека (кириллица, тайский, арабский, иврит, корейский, кана)
NON_EN_SCRIPT_RE = re.compile(
    r"[\u0400-\u04FF"
    r"\u0E00-\u0E7F"
    r"\u0600-\u06FF"
    r"\u0590-\u05FF"
    r"\u1100-\u11FF\uAC00-\uD7AF"
    r"\u3040-\u30FF"
    r"]"
)


def is_placeholder_ru(ru: str | None) -> bool:
    if ru is None:
        return False
    s = ru.strip()
    return s == "" or ru == PLACEHOLDER_RU


def is_real_translation(source: str, ru: str | None) -> bool:
    src = (source or "").strip()
    ru_s = (ru or "").strip()
    if not src or not ru_s:
        return False
    if ru_s == src:
        return False
    if is_placeholder_ru(ru):
        return False
    # en-ключ с «переводом»-иероглифами из zh-модулей — не русский
    if has_cjk(ru_s) and not has_cjk(src):
        return False
    # zh→zh (другой знак препинания) — не перевод
    if has_cjk(src) and not CYRILLIC_RE.search(ru_s):
        return False
    return True


def is_preserved_dictionary_ru(source: str, ru: str | None) -> bool:
    """Готовое значение в словаре: реальный перевод или copy-as-is (ru = source)."""
    if is_real_translation(source, ru):
        return True
    src = (source or "").strip()
    ru_s = (ru or "").strip()
    return bool(src) and src == ru_s


def _copy_source_as_ru_for_track(source: str, *, track: Track) -> bool:
    from resolve_dictionary_placeholders import should_copy_source_as_ru

    return should_copy_source_as_ru(source, track=track)


def is_usable_library_ru(source: str, ru: str | None) -> bool:
    """Значение из словаря можно записать в values-ru (перевод или copy-as-is)."""
    src = (source or "").strip()
    ru_s = (ru or "").strip()
    if not src or not ru_s:
        return False
    if is_placeholder_ru(ru):
        return False
    if has_cjk(ru_s) and not has_cjk(src):
        return False
    return True


def has_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text))


def is_android_resource_reference(text: str) -> bool:
    """Ссылка на ресурс Android (@android:string/…, @string/…). Не переводить."""
    s = (text or "").strip()
    if not s.startswith("@"):
        return False
    return bool(_ANDROID_RESOURCE_REF_RE.match(s))


def is_assist_name_string(text: str) -> bool:
    """Голосовые метки {assistName:…} — не в словари, копировать как есть."""
    return bool(_ASSIST_NAME_RE.match((text or "").strip()))


def skip_for_translation_library(text: str) -> bool:
    """Не сканировать и не добавлять в словари (@string/…, {assistName:…})."""
    s = (text or "").strip()
    return is_android_resource_reference(s) or is_assist_name_string(s)


def pick_android_resource_reference(*texts: str | None) -> str | None:
    """Первая ссылка на ресурс среди текстов locale (values → en → zh)."""
    for t in texts:
        if t and is_android_resource_reference(t):
            return t.strip()
    return None


def pick_assist_name_string(*texts: str | None) -> str | None:
    """Первая {assistName:…} среди текстов locale."""
    for t in texts:
        if t and is_assist_name_string(t):
            return t.strip()
    return None


def pick_assist_name_from_elements(
    *,
    def_el: ET.Element | None,
    en_el: ET.Element | None,
    zh_cn_el: ET.Element | None,
    zh_el: ET.Element | None,
    get_text: Callable[[ET.Element], str],
) -> str | None:
    return pick_assist_name_string(
        get_text(def_el) if def_el is not None else None,
        get_text(en_el) if en_el is not None else None,
        get_text(zh_cn_el) if zh_cn_el is not None else None,
        get_text(zh_el) if zh_el is not None else None,
    )


def pick_android_resource_reference_from_elements(
    *,
    def_el: ET.Element | None,
    en_el: ET.Element | None,
    zh_cn_el: ET.Element | None,
    zh_el: ET.Element | None,
    get_text: Callable[[ET.Element], str],
) -> str | None:
    return pick_android_resource_reference(
        get_text(def_el) if def_el is not None else None,
        get_text(en_el) if en_el is not None else None,
        get_text(zh_cn_el) if zh_cn_el is not None else None,
        get_text(zh_el) if zh_el is not None else None,
    )


def is_digits_only_source(text: str) -> bool:
    """Исходник из одних цифр (00, 123) — не для словаря/pending."""
    s = (text or "").strip()
    return bool(s) and s.isdigit()


_SVG_PATH_CMD_RE = re.compile(r"[CLHVQSATclhvqsat]")
_NULLISH_RE = re.compile(r"^@null$", re.I)
_BOOL_LITERAL_RE = re.compile(r"^(?:true|false)$", re.I)
_RESOLUTION_RE = re.compile(r"^\d+x\d+")
_MMDD_QUOTED_RE = re.compile(r'^"\d{4}')
_MMDD_NAME_RE = re.compile(r"^\d{4}[A-Za-z]")
_MMDD_CJK_RE = re.compile(r"^\d{4}[\u4e00-\u9fff]")
_ZH_ENGINEERING_RE = re.compile(
    r"chargeState|parkingBrake|proflashLockState|rideableState|alertState|"
    r"gearState|HVActiveState|batteryState|powerBatteryState|dischargeState|"
    r"speedState|carSpeedZero|powerMode|batteryLevel|DA_UNIQUE_ID|CDC_log|"
    r"配置字FLAG|重启TBOX|CCM|Dump CPUMemory|tcp adb|bit位置|字节序列|"
    r"非行驶档位|"
    r"系统属性名|Eeprom|QPST|UFS分区|车型切换说明",
    re.I,
)
_NAVBAR_SPEC_RE = re.compile(r"\[[^\]]+\].*;")
_HEX_HASH_RE = re.compile(r"^[a-f0-9]{6,}$", re.I)
_ABS_PATH_RE = re.compile(r"^/")
_MONTH_ABBR = frozenset("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())
_VEHICLE_CFG_RE = re.compile(
    r"^(?:C\d+[-_]|H53A_|REEV\d|BEV\d|Upper_|(?:EV|EVE|ICA)_[A-Z0-9_]+|\d[a-f][A-Z0-9_]+)",
    re.I,
)
_ALLCAPS_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_LOCALE_TAG_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
_PUNCT_ONLY_RE = re.compile(r'^["\s/、,•—\-°F…]+$')
_WEEKDAY_DATE_FMT_RE = re.compile(r"^EEE")
_DATE_FMT_MMM_RE = re.compile(r"^MMMd$")
_TCP_DUMP_RE = re.compile(r"^Start tcp dump", re.I)
_DEBUG_LOG_RE = re.compile(r"^(?:Debug|Verbose|Fatal)$")
_DIM_SCREEN_RE = re.compile(r"^dim screen,", re.I)
_AUDIO_DUMP_RE = re.compile(r"^audio dump_", re.I)
_MP4_RE = re.compile(r"\.mp4$", re.I)
_8021X_RE = re.compile(r"^802\.1x$", re.I)
_MPG_UNIT_RE = re.compile(r"^mpg \(", re.I)
_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")
_DEV_PKG_LIST_RE = re.compile(r"^com\.[a-z0-9_.]+,com\.")
_DOMAIN_LIST_RE = re.compile(r"example\.com|\.test\.|localhost")
_HEX_VEHICLE_RE = re.compile(r"^\d{2}[A-Z0-9_]*(?:EV|EVE)_", re.I)
_CHIP_NAME_RE = re.compile(r"^S32G$")
_TEST_TOOLS_RE = re.compile(r"TestTools$")
_VERSION_FIELD_RE = re.compile(
    r"_(?:VERSION|HW|SW[AM]?|SN|PORT|ID|ICCID|TUID|CONFIG|DUMP|MODE|LOG|RX|TX)$",
    re.I,
)


def _looks_like_svg_path(text: str) -> bool:
    s = text.strip()
    if not s.startswith(("M", "m")):
        return False
    if len(s) < 8:
        return False
    if _SVG_PATH_CMD_RE.search(s) and re.search(r"\d", s):
        return True
    if len(s) >= 12 and (
        re.search(r"\s[AHVahv]\d", s) or s.rstrip().endswith(("Z", "z"))
    ):
        return True
    return False


def looks_technical(text: str) -> bool:
    s = text.strip()
    if not s:
        return True
    if len(s) == 1:
        return True
    if is_android_resource_reference(s):
        return True
    if _FQCN_RE.match(s) or _JAVA_CLASS_RE.match(s):
        return True
    if is_digits_only_source(s):
        return True
    if (
        _SIGNED_INT_RE.match(s)
        or _DECIMAL_LITERAL_RE.match(s)
        or _TIME_RE.match(s)
        or _TIME_PATTERN_RE.match(s)
        or _IPV4_RE.match(s)
    ):
        return True
    if _CONTENT_URI_RE.match(s) or _URI_SCHEME_RE.match(s):
        return True
    if _ANDROID_COMPONENT_RE.match(s) or _COMMA_IDENT_RE.match(s):
        return True
    if _looks_like_svg_path(s):
        return True
    if _FONT_FAMILY_RE.match(s) or _HYPHENATED_ID_RE.match(s):
        return True
    if _ANDROID_FORMAT_PREFIX_RE.match(s):
        return True
    if _LOCALE_CODE_RE.match(s) and s.lower() not in _SHORT_ASCII_WORDS:
        return True
    if "_" in s and _SNAKE_IDENTIFIER_RE.match(s):
        return True
    if (
        _NULLISH_RE.match(s)
        or _BOOL_LITERAL_RE.match(s)
        or _RESOLUTION_RE.match(s)
        or _MMDD_QUOTED_RE.match(s)
        or _MMDD_NAME_RE.match(s)
        or _MMDD_CJK_RE.match(s)
        or is_assist_name_string(s)
        or _ZH_ENGINEERING_RE.search(s)
        or _NAVBAR_SPEC_RE.search(s)
        or _HEX_HASH_RE.match(s)
        or _ABS_PATH_RE.match(s)
        or _LOCALE_TAG_RE.match(s)
        or _PUNCT_ONLY_RE.match(s)
        or _WEEKDAY_DATE_FMT_RE.match(s)
        or _DATE_FMT_MMM_RE.match(s)
        or _TCP_DUMP_RE.match(s)
        or _DEBUG_LOG_RE.match(s)
        or _DIM_SCREEN_RE.match(s)
        or _AUDIO_DUMP_RE.match(s)
        or _MP4_RE.search(s)
        or _8021X_RE.match(s)
        or _MPG_UNIT_RE.match(s)
        or _DEV_PKG_LIST_RE.match(s)
        or _DOMAIN_LIST_RE.search(s)
        or _HEX_VEHICLE_RE.match(s)
        or _CHIP_NAME_RE.match(s)
        or _TEST_TOOLS_RE.search(s)
        or _VEHICLE_CFG_RE.match(s)
    ):
        return True
    if s in _MONTH_ABBR:
        return True
    if _COUNTRY_CODE_RE.match(s) and s not in ("OK", "ON", "OFF"):
        return True
    if (
        len(s) == 2
        and s.islower()
        and s in ("be", "in", "it", "my")
    ):
        return True
    if s in ('"AKA\'"', "AKA'"):
        return True
    if _ALLCAPS_ID_RE.match(s) and (
        "_" in s or _VERSION_FIELD_RE.search(s) or len(s) >= 4
    ):
        return True
    if s in (
        "ADAS",
        "AKA",
        "ALL",
        "ANDROID",
        "ANDROID MEMORY",
        "SECURE BOOT",
        "Sentry_",
        "DHCP",
        "TLS",
        "PEAP",
        "PAP",
        "TTLS",
        "MSCHAP",
        "MSCHAPV2",
        "PSI",
        "PWD",
        "HUD",
        "RPM",
        "SIM",
        "QNX",
        "GTC",
        "FCV",
        "TBOX",
        "VID",
        "Hm",
        "Hz",
        "Ah",
        "Wh",
        "mA",
        "mV",
        "mW",
        "kPa",
        "kWh",
        "MPG",
        "mm",
        "PH",
        "°F",
        "——",
        "••••••",
        "rndis",
        "midi",
        "systrace",
        "tfaa",
        "tfca",
        "CalendarView",
        "screen, touchscreen",
    ):
        return True
    return False


def elements_by_key(root: ET.Element | None) -> dict[tuple[str, str], ET.Element]:
    if root is None:
        return {}
    out: dict[tuple[str, str], ET.Element] = {}
    for el in root:
        name = el.attrib.get("name")
        if name:
            out[(el.tag, name)] = el
    return out


def find_item_quantity(plurals_el: ET.Element | None, quantity: str) -> ET.Element | None:
    if plurals_el is None:
        return None
    for it in plurals_el.findall("item"):
        if it.attrib.get("quantity") == quantity:
            return it
    return None


def resolve_source_en(
    en_el: ET.Element | None,
    def_el: ET.Element | None,
    *,
    get_text: Callable[[ET.Element], str],
) -> tuple[str | None, str]:
    if en_el is not None:
        text = get_text(en_el)
        if not looks_technical(text):
            return text, "values-en"
    if def_el is not None:
        text = get_text(def_el)
        if looks_technical(text):
            return None, ""
        if has_cjk(text):
            return None, ""
        return text, "values"
    return None, ""


def resolve_source_zh(
    zh_cn_el: ET.Element | None,
    zh_el: ET.Element | None,
    def_el: ET.Element | None,
    *,
    get_text: Callable[[ET.Element], str],
) -> tuple[str | None, str]:
    if zh_cn_el is not None:
        text = get_text(zh_cn_el)
        if not looks_technical(text):
            return text, "values-zh-rCN"
    if zh_el is not None:
        text = get_text(zh_el)
        if not looks_technical(text):
            return text, "values-zh"
    if def_el is not None:
        text = get_text(def_el)
        if looks_technical(text):
            return None, ""
        if not has_cjk(text):
            return None, ""
        return text, "values"
    return None, ""


def pick_track_and_source(
    en_src: str | None,
    zh_src: str | None,
    default_text: str | None,
    *,
    values_en_first: bool = False,
) -> tuple[Track | None, str | None]:
    """Один ресурс — один трек: en, zh или пропуск."""
    en_s = (en_src or "").strip() or None
    zh_s = (zh_src or "").strip() or None
    if en_s and not zh_s:
        return "en", en_s
    if zh_s and not en_s:
        return "zh", zh_s
    if en_s and zh_s:
        if values_en_first:
            return "en", en_s
        if has_cjk(default_text or ""):
            return "zh", zh_s
        return "en", en_s
    return None, None


def count_named_resources(root: ET.Element | None) -> int:
    if root is None:
        return 0
    return sum(
        1
        for el in root
        if el.tag in _NAMED_RESOURCE_TAGS and el.attrib.get("name")
    )


@dataclass(frozen=True)
class ValuesEnCoverage:
    """Покрытие values-en относительно values по числу именованных ресурсов."""

    values_en_first: bool
    ratio: float
    named_in_values: int
    named_in_values_en: int

    @property
    def warning(self) -> str:
        if self.values_en_first or self.named_in_values_en == 0:
            return ""
        pct = int(VALUES_EN_MIN_COVERAGE * 100)
        return (
            f"values-en {self.named_in_values_en}/{self.named_in_values} "
            f"({self.ratio:.0%}) < {pct}% — приоритет values, не values-en"
        )


def module_values_en_coverage(
    module_dir: Path,
    xml_names: tuple[str, ...] = TRANSLATABLE_XML,
    *,
    min_ratio: float = VALUES_EN_MIN_COVERAGE,
) -> ValuesEnCoverage:
    res = module_dir / "res"
    n_def = n_en = 0
    for xml_name in xml_names:
        n_def += count_named_resources(parse_xml(res / "values" / xml_name))
        n_en += count_named_resources(parse_xml(res / "values-en" / xml_name))
    if n_def == 0:
        ratio = 1.0 if n_en else 0.0
        usable = n_en > 0
    else:
        ratio = n_en / n_def
        usable = n_en > 0 and ratio >= min_ratio
    return ValuesEnCoverage(
        values_en_first=usable,
        ratio=ratio,
        named_in_values=n_def,
        named_in_values_en=n_en,
    )


def parse_xml(path: Path) -> ET.Element | None:
    if not path.is_file():
        return None
    try:
        return ET.parse(path).getroot()
    except ET.ParseError:
        return None


def load_locale_roots(module_dir: Path, xml_name: str) -> dict[str, ET.Element | None]:
    res = module_dir / "res"
    return {
        "def": parse_xml(res / "values" / xml_name),
        "en": parse_xml(res / "values-en" / xml_name),
        "zh_cn": parse_xml(res / "values-zh-rCN" / xml_name),
        "zh": parse_xml(res / "values-zh" / xml_name),
        "ru": parse_xml(res / "values-ru" / xml_name),
    }


def library_path_for_track(tools_root: Path, track: Track) -> Path:
    base = tools_root / "data" / "dictionaries"
    if track == "en":
        return base / "translation_library_ru_en.json"
    return base / "translation_library_ru_zh-rCN.json"


def resolve_array_item_zh(
    index: int,
    *,
    zh_cn_items: list[ET.Element],
    zh_items: list[ET.Element],
    def_items: list[ET.Element],
) -> tuple[str | None, str]:
    if index < len(zh_cn_items):
        text = zh_cn_items[index].text or ""
        if not looks_technical(text):
            return text, "values-zh-rCN"
    if index < len(zh_items):
        text = zh_items[index].text or ""
        if not looks_technical(text):
            return text, "values-zh"
    if index < len(def_items):
        text = def_items[index].text or ""
        if not looks_technical(text) and has_cjk(text):
            return text, "values"
    return None, ""


def resolve_array_item_en(
    index: int,
    *,
    en_items: list[ET.Element],
    def_items: list[ET.Element],
) -> tuple[str | None, str]:
    if index < len(en_items):
        text = en_items[index].text or ""
        if not looks_technical(text):
            return text, "values-en"
    if index < len(def_items):
        text = def_items[index].text or ""
        if looks_technical(text):
            return None, ""
        if has_cjk(text):
            return None, ""
        return text, "values"
    return None, ""


@dataclass(frozen=True)
class SourceVariant:
    track: Track
    text: str
    locale: str


def is_valid_en_source_key(text: str) -> bool:
    """Текст подходит как ключ en-словаря (латиница / цифры / пунктуация)."""
    s = (text or "").strip()
    if not s:
        return False
    if has_cjk(s) or NON_EN_SCRIPT_RE.search(s):
        return False
    return True


def classify_track_for_text(text: str) -> Track | None:
    s = (text or "").strip()
    if not s or looks_technical(s):
        return None
    if has_cjk(s):
        return "zh"
    if not is_valid_en_source_key(s):
        return None
    return "en"


def collect_source_variants(
    *,
    def_el: ET.Element | None,
    en_el: ET.Element | None,
    zh_cn_el: ET.Element | None,
    zh_el: ET.Element | None,
    get_text: Callable[[ET.Element], str],
) -> list[SourceVariant]:
    """
    Все уникальные исходники строки из values / values-en / values-zh-rCN / values-zh.
    Один текст может попасть только в один трек (en или zh).
    """
    seen: set[tuple[Track, str]] = set()
    out: list[SourceVariant] = []
    for el in (def_el, en_el, zh_cn_el, zh_el):
        if el is None:
            continue
        if skip_for_translation_library(get_text(el) or ""):
            return []

    for el, locale in (
        (en_el, "values-en"),
        (zh_cn_el, "values-zh-rCN"),
        (zh_el, "values-zh"),
        (def_el, "values"),
    ):
        if el is None:
            continue
        text = (get_text(el) or "").strip()
        if not text:
            continue
        track = classify_track_for_text(text)
        if track is None:
            continue
        key = (track, text)
        if key in seen:
            continue
        seen.add(key)
        out.append(SourceVariant(track=track, text=text, locale=locale))
    return out


def variants_for_track(variants: list[SourceVariant], track: Track) -> list[SourceVariant]:
    return [v for v in variants if v.track == track]


def sort_variants_for_lookup(
    variants: list[SourceVariant],
    *,
    values_en_first: bool = False,
) -> list[SourceVariant]:
    if not variants:
        return variants
    if values_en_first:
        return sorted(
            variants,
            key=lambda v: (
                0 if v.track == "en" else 1,
                0 if v.locale == "values-en" else (1 if v.locale == "values" else 2),
                v.text,
            ),
        )
    if any(v.track == "zh" for v in variants) and any(v.track == "en" for v in variants):
        return sorted(variants, key=lambda v: (0 if v.track == "zh" else 1, v.locale, v.text))
    return variants


def canonical_variant(
    variants: list[SourceVariant],
    *,
    values_en_first: bool,
    track: Track | None = None,
) -> SourceVariant | None:
    """Главный исходник для строки: values-en → values (en/zh по тексту)."""
    if not variants:
        return None
    pool = variants if track is None else variants_for_track(variants, track)
    if not pool:
        return None
    if values_en_first:
        for locale in ("values-en", "values", "values-zh-rCN", "values-zh"):
            for v in pool:
                if v.locale == locale:
                    return v
    return sort_variants_for_lookup(pool, values_en_first=values_en_first)[0]


def canonical_source_text(
    variants: list[SourceVariant],
    fallback: str | None,
    *,
    values_en_first: bool,
) -> str:
    v = canonical_variant(variants, values_en_first=values_en_first)
    if v is not None:
        return v.text
    return (fallback or "").strip()


def lookup_ru_in_track_maps(
    track_maps: dict[Track, dict[str, str]],
    variants: list[SourceVariant],
    *,
    values_en_first: bool = False,
) -> tuple[str | None, SourceVariant | None]:
    """Поиск реального перевода по всем вариантам в en- и zh-словарях."""
    for v in sort_variants_for_lookup(variants, values_en_first=values_en_first):
        ru = track_maps.get(v.track, {}).get(v.text)
        if is_real_translation(v.text, ru):
            return ru, v
    return None, None


def lookup_library_ru_for_apply(
    track_maps: dict[Track, dict[str, str]],
    variants: list[SourceVariant],
    *,
    values_en_first: bool = False,
) -> tuple[str | None, SourceVariant | None]:
    """Поиск в словарях для записи в APK: перевод или copy-as-is (map13 → map13)."""
    for v in sort_variants_for_lookup(variants, values_en_first=values_en_first):
        ru = track_maps.get(v.track, {}).get(v.text)
        if is_usable_library_ru(v.text, ru):
            return ru, v
    return None, None


def lookup_ru_in_merged_map(
    merged_map: dict[str, str],
    variants: list[SourceVariant],
    *,
    values_en_first: bool = False,
) -> tuple[str | None, str | None]:
    for v in sort_variants_for_lookup(variants, values_en_first=values_en_first):
        ru = merged_map.get(v.text)
        if is_real_translation(v.text, ru):
            return ru, v.text
    return None, None


def any_variant_in_merged_map(
    merged_map: dict[str, str],
    variants: list[SourceVariant],
    *,
    values_en_first: bool = False,
) -> bool:
    return (
        lookup_ru_in_merged_map(
            merged_map, variants, values_en_first=values_en_first
        )[0]
        is not None
    )


def register_placeholders_in_track_maps(
    track_maps: dict[Track, dict[str, str]],
    variants: list[SourceVariant],
    *,
    placeholder_ru: str = PLACEHOLDER_RU,
) -> set[Track]:
    """Заглушка для новых ключей и для записей без реального ru."""
    dirty: set[Track] = set()
    for v in variants:
        if skip_for_translation_library(v.text):
            continue
        m = track_maps.setdefault(v.track, {})
        cur = m.get(v.text)
        if cur is not None and is_preserved_dictionary_ru(v.text, cur):
            continue
        if _copy_source_as_ru_for_track(v.text, track=v.track):
            if m.get(v.text) != v.text:
                m[v.text] = v.text
                dirty.add(v.track)
            continue
        if m.get(v.text) != placeholder_ru:
            m[v.text] = placeholder_ru
            dirty.add(v.track)
    return dirty


def ensure_placeholders_in_map(
    string_map: dict[str, str],
    sources: Iterable[str],
    *,
    placeholder_ru: str = PLACEHOLDER_RU,
    track: Track = "en",
) -> int:
    """Проставить заглушку всем исходникам без готового перевода в string_map."""
    changed = 0
    for raw in sources:
        src = (raw or "").strip()
        if not src or skip_for_translation_library(src) or looks_technical(src):
            continue
        cur = string_map.get(src)
        if cur is not None and is_preserved_dictionary_ru(src, cur):
            continue
        if _copy_source_as_ru_for_track(src, track=track):
            if string_map.get(src) != src:
                string_map[src] = src
                changed += 1
            continue
        if cur != placeholder_ru:
            string_map[src] = placeholder_ru
            changed += 1
    return changed


def sync_ru_to_variant_keys(
    track_maps: dict[Track, dict[str, str]],
    variants: list[SourceVariant],
    ru_text: str,
) -> set[Track]:
    """Записать один ru под каждый вариант исходника в соответствующий трек-словарь."""
    dirty: set[Track] = set()
    if not variants:
        return dirty
    ru_s = (ru_text or "").strip()
    if not ru_s or is_placeholder_ru(ru_text):
        return dirty
    if skip_for_translation_library(ru_text):
        return dirty
    if all(ru_s == v.text for v in variants):
        return dirty
    for v in variants:
        if skip_for_translation_library(v.text):
            continue
        if not is_real_translation(v.text, ru_text):
            continue
        m = track_maps.setdefault(v.track, {})
        if m.get(v.text) != ru_text:
            m[v.text] = ru_text
            dirty.add(v.track)
    return dirty


def ensure_ru_from_track_maps(
    track_maps: dict[Track, dict[str, str]],
    variants: list[SourceVariant],
    *,
    placeholder_ru: str = PLACEHOLDER_RU,
    values_en_first: bool = False,
) -> tuple[str, set[Track], bool]:
    """
    Найти ru в словарях по любому варианту; иначе зарегистрировать заглушки.
    Возвращает (ru, dirty_tracks, applied_from_library).
    """
    if variants and all(skip_for_translation_library(v.text) for v in variants):
        return variants[0].text, set(), False
    ru, _ = lookup_ru_in_track_maps(
        track_maps, variants, values_en_first=values_en_first
    )
    if ru is not None:
        return ru, set(), True
    for v in variants:
        if _copy_source_as_ru_for_track(v.text, track=v.track):
            m = track_maps.setdefault(v.track, {})
            dirty: set[Track] = set()
            if m.get(v.text) != v.text:
                m[v.text] = v.text
                dirty.add(v.track)
            return v.text, dirty, False
    dirty = register_placeholders_in_track_maps(
        track_maps, variants, placeholder_ru=placeholder_ru
    )
    return placeholder_ru, dirty, False
