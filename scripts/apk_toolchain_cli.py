#!/usr/bin/env python3
"""CLI: распаковка / сборка / push APK для GUI и терминала."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent.parent / "library"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from apk_toolchain import (  # noqa: E402
    ApkToolchainError,
    build_signed_apk,
    decompile_apk,
    push_module,
    push_signed_apk,
    read_package_name,
    resolve_toolchain,
    setup_vendor_tools,
    toolchain_status,
)


def _cmd_status(_args: argparse.Namespace) -> int:
    status = toolchain_status()
    for key, val in status.items():
        print(f"{key}: {val}")
    return 0 if status.get("ok") else 1


def _cmd_setup(args: argparse.Namespace) -> int:
    result = setup_vendor_tools(force=args.force)
    print(result)
    return 0


def _cmd_decompile(args: argparse.Namespace) -> int:
    decompile_apk(args.apk.resolve(), force=not args.no_force)
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    build_signed_apk(
        args.src.resolve(),
        sign_profile=args.sign,
        custom_pk8=args.pk8.resolve() if args.pk8 else None,
        custom_x509=args.x509.resolve() if args.x509 else None,
        keep_src=not args.remove_src,
    )
    return 0


def _cmd_push(args: argparse.Namespace) -> int:
    if args.module:
        push_module(args.module.resolve(), package=args.package)
    else:
        if not args.apk or not args.package:
            raise ApkToolchainError("Укажите --apk и --package или --module")
        push_signed_apk(args.apk.resolve(), args.package)
    return 0


def _cmd_package(args: argparse.Namespace) -> int:
    pkg = read_package_name(args.src.resolve())
    if not pkg:
        print("package: (не найден)", file=sys.stderr)
        return 1
    print(pkg)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="APK toolchain")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Проверка инструментов")
    p_status.set_defaults(func=_cmd_status)

    p_setup = sub.add_parser("setup", help="Скопировать инструменты в vendor/apktools")
    p_setup.add_argument("--force", action="store_true")
    p_setup.set_defaults(func=_cmd_setup)

    p_dec = sub.add_parser("decompile", help="apktool d → *_src")
    p_dec.add_argument("apk", type=Path)
    p_dec.add_argument("--no-force", action="store_true", help="Не перезаписывать существующую папку")
    p_dec.set_defaults(func=_cmd_decompile)

    p_build = sub.add_parser("build", help="apktool b + zipalign + sign")
    p_build.add_argument("src", type=Path, help="Папка *_src")
    p_build.add_argument("--sign", choices=("deepal", "testkey", "custom"), default="deepal")
    p_build.add_argument("--pk8", type=Path, default=None)
    p_build.add_argument("--x509", type=Path, default=None)
    p_build.add_argument(
        "--remove-src",
        action="store_true",
        help="Удалить папку исходников после сборки (как build-apk.sh)",
    )
    p_build.set_defaults(func=_cmd_build)

    p_push = sub.add_parser("push", help="adb push signed APK на устройство")
    p_push.add_argument("--module", type=Path, default=None, help="Папка *_src модуля")
    p_push.add_argument("--apk", type=Path, default=None)
    p_push.add_argument("--package", default=None)
    p_push.set_defaults(func=_cmd_push)

    p_pkg = sub.add_parser("package", help="Прочитать package из AndroidManifest.xml")
    p_pkg.add_argument("src", type=Path)
    p_pkg.set_defaults(func=_cmd_package)

    args = ap.parse_args()
    try:
        resolve_toolchain()
        return args.func(args)
    except ApkToolchainError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
