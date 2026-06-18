#!/usr/bin/env python3
"""Скопировать apktool/apksigner/zipalign/ключи в vendor/apktools (автономный режим)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent.parent / "library"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from apk_toolchain import setup_vendor_tools, toolchain_status  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Установка APK-инструментов в vendor/apktools")
    ap.add_argument("--force", action="store_true", help="Перезаписать существующие файлы")
    args = ap.parse_args()

    result = setup_vendor_tools(force=args.force)
    print(f"vendor: {result['vendor']}")
    if result["copied"]:
        print("скопировано:", ", ".join(result["copied"]))
    if result["missing"]:
        print("не найдено:", ", ".join(result["missing"]), file=sys.stderr)

    status = toolchain_status()
    if status.get("ok"):
        print("✅ toolchain готов")
        print(f"   источник: {status.get('source')}")
        return 0

    print("⚠️ toolchain неполный:", status.get("error") or status.get("issues"), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
