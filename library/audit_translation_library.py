#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Эвристический аудит словарей en/zh: типичные ошибки автоперевода (Win→Победа, Trunk→Ствол и т.д.).

Не заменяет ручную вычитку; пишет отчёт для просмотра и правки.

Пример:
  python3 "tools Linux/library/audit_translation_library.py"
  python3 "tools Linux/library/audit_translation_library.py" --rule win_pobeda
  python3 "tools Linux/library/audit_translation_library.py" --min-severity high
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT / "library"))

from source_resolve import (  # noqa: E402
    CJK_RE,
    CYRILLIC_RE,
    is_android_resource_reference,
    is_placeholder_ru,
)

DEFAULT_EN = TOOLS_ROOT / "translation_library_ru_en.json"
DEFAULT_ZH = TOOLS_ROOT / "translation_library_ru_zh-rCN.json"
DEFAULT_REPORT = TOOLS_ROOT / "reports" / "translation_library_audit.json"

_WIN_EN_RE = re.compile(r"\bWin\b|All\s+Win\b|Vent\s+Win\b", re.I)
_DATE_CYRILLIC_RE = re.compile(r"ЭЭЭЭ|ММММ\s+д\b", re.I)
_CAR_WINDOW_ZH = "车窗"
_TRUNK_EN = re.compile(r"\bTrunk\b", re.I)
_WINDOW_RU_RE = re.compile(r"окн|стекл", re.I)
_TRUNK_RU_STVOL = re.compile(r"\bствол\b", re.I)
_POBEDA_RU = re.compile(r"побед", re.I)


@dataclass
class Finding:
    rule: str
    severity: str  # high | medium | low
    track: str
    source: str
    ru: str
    hint: str


def _load_map(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Ожидался object JSON: {path}")
    return {str(k): str(v) for k, v in data.items()}


def check_win_pobeda(track: str, source: str, ru: str) -> Finding | None:
    if not _POBEDA_RU.search(ru):
        return None
    if track == "en" and _WIN_EN_RE.search(source):
        return Finding(
            rule="win_pobeda",
            severity="high",
            track=track,
            source=source,
            ru=ru,
            hint="В английском «Win» = window, не victory; в ru не должно быть «побед*».",
        )
    if track == "zh" and _CAR_WINDOW_ZH in source:
        return Finding(
            rule="win_pobeda",
            severity="high",
            track=track,
            source=source,
            ru=ru,
            hint="Исходник про автомобильные окна (车窗); «побед*» — ошибка перевода.",
        )
    return None


def check_car_window_no_okno(track: str, source: str, ru: str) -> Finding | None:
    if track != "zh" or _CAR_WINDOW_ZH not in source:
        return None
    if len(source) > 120:
        return None
    if _WINDOW_RU_RE.search(ru):
        return None
    if is_placeholder_ru(ru) or is_android_resource_reference(source):
        return None
    return Finding(
        rule="car_window_no_okno",
        severity="medium",
        track=track,
        source=source,
        ru=ru,
        hint="В исходнике 车窗, в переводе нет «окн/стекл» — проверьте вручную.",
    )


def check_trunk_stvol(track: str, source: str, ru: str) -> Finding | None:
    trunk_src = (track == "en" and _TRUNK_EN.search(source)) or (
        track == "zh" and "后备箱" in source and len(source) < 80
    )
    if not trunk_src:
        return None
    if not _TRUNK_RU_STVOL.search(ru):
        return None
    if re.search(r"багажник", ru, re.I):
        return None
    return Finding(
        rule="trunk_stvol",
        severity="high",
        track=track,
        source=source,
        ru=ru,
        hint="Trunk/后备箱 → «багажник», не «ствол».",
    )


def check_date_format_cyrillic(track: str, source: str, ru: str) -> Finding | None:
    if not re.fullmatch(r"[EMd,\s]+", (source or "").strip()):
        return None
    if not _DATE_CYRILLIC_RE.search(ru):
        return None
    return Finding(
        rule="date_format_cyrillic",
        severity="high",
        track=track,
        source=source,
        ru=ru,
        hint="Шаблон даты: оставить латинские E/M/d (например EEEE, MMMM d).",
    )


def check_cjk_in_ru(track: str, source: str, ru: str) -> Finding | None:
    if not CJK_RE.search(ru) or CJK_RE.search(source):
        return None
    if len(ru) > 200:
        return None
    return Finding(
        rule="cjk_in_ru",
        severity="medium",
        track=track,
        source=source,
        ru=ru,
        hint="В русском остались иероглифы — возможно непереведённая строка.",
    )


def check_untranslated_en(track: str, source: str, ru: str) -> Finding | None:
    if track != "en":
        return None
    if len(source) > 60 or len(source) < 2:
        return None
    if source.strip() != ru.strip():
        return None
    if not re.search(r"[A-Za-z]{3,}", source):
        return None
    if source.startswith("{assistName:"):
        return None
    return Finding(
        rule="untranslated_en",
        severity="low",
        track=track,
        source=source,
        ru=ru,
        hint="ru совпадает с английским исходником.",
    )


CHECKS = (
    check_win_pobeda,
    check_car_window_no_okno,
    check_trunk_stvol,
    check_date_format_cyrillic,
    check_cjk_in_ru,
    check_untranslated_en,
)


def audit_library(
    string_map: dict[str, str],
    track: str,
    *,
    rules: set[str] | None,
    min_severity: str,
) -> list[Finding]:
    severity_rank = {"high": 3, "medium": 2, "low": 1}
    min_rank = severity_rank.get(min_severity, 1)
    out: list[Finding] = []
    for source, ru in string_map.items():
        if is_placeholder_ru(ru):
            continue
        for fn in CHECKS:
            if rules is not None and fn.__name__.removeprefix("check_") not in rules:
                continue
            finding = fn(track, source, ru)
            if finding is None:
                continue
            if severity_rank.get(finding.severity, 0) < min_rank:
                continue
            out.append(finding)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Аудит translation_library_ru_*.json")
    ap.add_argument("--en", type=Path, default=DEFAULT_EN)
    ap.add_argument("--zh", type=Path, default=DEFAULT_ZH)
    ap.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    ap.add_argument(
        "--rule",
        action="append",
        dest="rules",
        help="Только указанное правило (win_pobeda, trunk_stvol, …)",
    )
    ap.add_argument(
        "--min-severity",
        choices=("high", "medium", "low"),
        default="medium",
        help="Минимальная важность в отчёте (по умолчанию medium)",
    )
    args = ap.parse_args()
    rule_set = set(args.rules) if args.rules else None

    all_findings: list[Finding] = []
    for track, path in (("en", args.en), ("zh", args.zh)):
        if not path.is_file():
            print(f"[warn] нет файла: {path}", file=sys.stderr)
            continue
        m = _load_map(path)
        findings = audit_library(m, track, rules=rule_set, min_severity=args.min_severity)
        all_findings.extend(findings)
        print(f"[{track}] {path.name}: {len(findings)} замечаний", flush=True)

    by_rule: dict[str, int] = {}
    for f in all_findings:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1

    payload = {
        "findings": [asdict(f) for f in all_findings],
        "summary": {"total": len(all_findings), "by_rule": by_rule},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[write] {args.output} — всего {len(all_findings)}", flush=True)
    for rule, n in sorted(by_rule.items()):
        print(f"  {rule}: {n}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
