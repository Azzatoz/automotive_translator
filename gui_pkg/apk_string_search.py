"""Поиск подстроки в values-ru по модулям проекта."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from gui_pkg.config import TRANSLATABLE_XML
from gui_pkg.scanner import ModuleInfo


@dataclass(frozen=True)
class ApkRuSearchHit:
    module_name: str
    module_display: str
    module_path: Path
    resource_id: str
    xml_file: str
    ru: str
    row_id: str


def _matches(text: str, query: str, *, case_sensitive: bool) -> bool:
    if not query:
        return False
    hay = text or ""
    if case_sensitive:
        return query in hay
    return query.casefold() in hay.casefold()


def search_module_values_ru(
    module_path: Path,
    *,
    module_name: str,
    module_display: str,
    query: str,
    case_sensitive: bool = False,
) -> list[ApkRuSearchHit]:
    q = (query or "").strip()
    if not q:
        return []
    hits: list[ApkRuSearchHit] = []
    for xml_name in TRANSLATABLE_XML:
        ru_path = module_path / "res" / "values-ru" / xml_name
        if not ru_path.is_file():
            continue
        try:
            root = ET.parse(ru_path).getroot()
        except ET.ParseError:
            continue
        for child in root:
            name = child.attrib.get("name")
            if not name:
                continue
            if child.tag == "string":
                text = child.text or ""
                if _matches(text, q, case_sensitive=case_sensitive):
                    hits.append(
                        ApkRuSearchHit(
                            module_name=module_name,
                            module_display=module_display,
                            module_path=module_path,
                            resource_id=f"string/{name}",
                            xml_file=xml_name,
                            ru=text,
                            row_id=f"{xml_name}::string/{name}",
                        )
                    )
            elif child.tag == "plurals":
                for item in child.findall("item"):
                    qty = item.attrib.get("quantity", "")
                    text = item.text or ""
                    if _matches(text, q, case_sensitive=case_sensitive):
                        hits.append(
                            ApkRuSearchHit(
                                module_name=module_name,
                                module_display=module_display,
                                module_path=module_path,
                                resource_id=f"plurals/{name} ({qty})",
                                xml_file=xml_name,
                                ru=text,
                                row_id=f"{xml_name}::plurals/{name}#q={qty}",
                            )
                        )
            elif child.tag == "string-array":
                for idx, item in enumerate(child.findall("item")):
                    text = item.text or ""
                    if _matches(text, q, case_sensitive=case_sensitive):
                        hits.append(
                            ApkRuSearchHit(
                                module_name=module_name,
                                module_display=module_display,
                                module_path=module_path,
                                resource_id=f"array/{name} [{idx}]",
                                xml_file=xml_name,
                                ru=text,
                                row_id=f"{xml_name}::array/{name}#[{idx}]",
                            )
                        )
    return hits


def search_all_modules(
    modules: dict[str, ModuleInfo],
    query: str,
    *,
    case_sensitive: bool = False,
    limit: int = 2000,
) -> list[ApkRuSearchHit]:
    q = (query or "").strip()
    if not q:
        return []
    out: list[ApkRuSearchHit] = []
    for info in sorted(modules.values(), key=lambda m: m.display.lower()):
        out.extend(
            search_module_values_ru(
                info.path,
                module_name=info.name,
                module_display=info.display,
                query=q,
                case_sensitive=case_sensitive,
            )
        )
        if len(out) >= limit:
            return out[:limit]
    return out
