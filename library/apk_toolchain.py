"""Распаковка, сборка, подпись и push APK — без привязки к /usr/local/bin."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from paths import REPO_ROOT

VENDOR_APKTOOLS = REPO_ROOT / "vendor" / "apktools"
MANIFEST_PATH = VENDOR_APKTOOLS / "manifest.json"

SIGN_PROFILES = ("deepal", "testkey", "custom")


@dataclass(frozen=True)
class ApkToolchain:
    java: str
    adb: str | None
    apktool_jar: Path
    apksigner_jar: Path
    zipalign: Path
    keys_root: Path
    source: str

    def sign_key_paths(self, profile: str, *, custom_pk8: Path | None = None, custom_x509: Path | None = None) -> tuple[Path, Path]:
        if profile == "deepal":
            return (
                self.keys_root / "deepal" / "deepal_cert.pk8",
                self.keys_root / "deepal" / "deepal_cert.x509.pem",
            )
        if profile == "testkey":
            return (
                self.keys_root / "testkey.pk8",
                self.keys_root / "testkey.x509.pem",
            )
        if profile == "custom":
            if custom_pk8 is None or custom_x509 is None:
                raise ValueError("Для профиля custom укажите пути к .pk8 и .x509.pem")
            return custom_pk8, custom_x509
        raise ValueError(f"Неизвестный профиль подписи: {profile}")


class ApkToolchainError(RuntimeError):
    pass


def _run(cmd: list[str], *, cwd: Path | None = None, label: str = "") -> None:
    prefix = f"[{label}] " if label else ""
    print(f"{prefix}$ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=False,
    )
    if proc.returncode != 0:
        raise ApkToolchainError(f"Команда завершилась с кодом {proc.returncode}: {' '.join(cmd)}")


def _which(name: str) -> str | None:
    return shutil.which(name)


def _find_zipalign_in_android_home() -> Path | None:
    android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not android_home:
        return None
    root = Path(android_home) / "build-tools"
    if not root.is_dir():
        return None
    candidates = sorted(root.glob("*/zipalign"), key=lambda p: p.parent.name)
    for candidate in reversed(candidates):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _external_resource_roots() -> list[Path]:
    roots: list[Path] = []
    env_root = os.environ.get("APKTOOLS_ROOT")
    if env_root:
        roots.append(Path(env_root))
    roots.extend(
        [
            Path("/opt/apktools/Resources"),
            REPO_ROOT.parent / "apktools" / "Resources",
        ]
    )
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def setup_vendor_tools(*, force: bool = False) -> dict:
    """Скопировать apktool/apksigner/zipalign/ключи в vendor/apktools."""
    VENDOR_APKTOOLS.mkdir(parents=True, exist_ok=True)
    (VENDOR_APKTOOLS / "keys" / "deepal").mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    missing: list[str] = []

    def copy_if_needed(src: Path, dst: Path, *, executable: bool = False) -> None:
        if dst.is_file() and not force:
            return
        if not src.is_file():
            missing.append(str(src))
            return
        shutil.copy2(src, dst)
        if executable:
            dst.chmod(dst.stat().st_mode | 0o111)
        copied.append(dst.name)

    source_label = "bundled"
    for root in _external_resource_roots():
        apktool = root / "apktool.jar"
        if apktool.is_file():
            source_label = str(root)
            copy_if_needed(apktool, VENDOR_APKTOOLS / "apktool.jar")
            copy_if_needed(root / "apksigner.jar", VENDOR_APKTOOLS / "apksigner.jar")
            zipalign_src = root / "zipalign"
            if zipalign_src.is_file():
                copy_if_needed(zipalign_src, VENDOR_APKTOOLS / "zipalign", executable=True)
            copy_if_needed(
                root / "Deepal" / "deepal_cert.pk8",
                VENDOR_APKTOOLS / "keys" / "deepal" / "deepal_cert.pk8",
            )
            copy_if_needed(
                root / "Deepal" / "deepal_cert.x509.pem",
                VENDOR_APKTOOLS / "keys" / "deepal" / "deepal_cert.x509.pem",
            )
            copy_if_needed(root / "testkey.pk8", VENDOR_APKTOOLS / "keys" / "testkey.pk8")
            copy_if_needed(root / "testkey.x509.pem", VENDOR_APKTOOLS / "keys" / "testkey.x509.pem")
            break

    zipalign_dst = VENDOR_APKTOOLS / "zipalign"
    if not zipalign_dst.is_file():
        found = _find_zipalign_in_android_home()
        if found is not None:
            copy_if_needed(found, zipalign_dst, executable=True)

    manifest = {
        "source": source_label,
        "files": sorted(p.name for p in VENDOR_APKTOOLS.iterdir() if p.is_file()),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {"copied": copied, "missing": missing, "vendor": str(VENDOR_APKTOOLS)}


def resolve_toolchain(
    *,
    custom_pk8: Path | None = None,
    custom_x509: Path | None = None,
) -> ApkToolchain:
    java = _which("java")
    if not java:
        raise ApkToolchainError("Не найден java в PATH. Установите JDK (OpenJDK 11+).")

    adb = _which("adb")

    apktool_jar = VENDOR_APKTOOLS / "apktool.jar"
    apksigner_jar = VENDOR_APKTOOLS / "apksigner.jar"
    zipalign = VENDOR_APKTOOLS / "zipalign"
    keys_root = VENDOR_APKTOOLS / "keys"

    if not apktool_jar.is_file() or not apksigner_jar.is_file():
        setup_vendor_tools()
    if not apktool_jar.is_file():
        raise ApkToolchainError(
            f"Не найден apktool.jar в {VENDOR_APKTOOLS}. "
            "Запустите: python3 scripts/setup_apk_tools.py"
        )
    if not apksigner_jar.is_file():
        raise ApkToolchainError(
            f"Не найден apksigner.jar в {VENDOR_APKTOOLS}. "
            "Запустите: python3 scripts/setup_apk_tools.py"
        )

    if not zipalign.is_file():
        found = _find_zipalign_in_android_home()
        if found is not None:
            zipalign = found
        else:
            raise ApkToolchainError(
                "Не найден zipalign. Укажите ANDROID_HOME или скопируйте zipalign в vendor/apktools."
            )

    source = "vendor"
    if MANIFEST_PATH.is_file():
        try:
            source = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("source", source)
        except (OSError, json.JSONDecodeError):
            pass

    tc = ApkToolchain(
        java=java,
        adb=adb,
        apktool_jar=apktool_jar,
        apksigner_jar=apksigner_jar,
        zipalign=zipalign,
        keys_root=keys_root,
        source=source,
    )
    return tc


def toolchain_status() -> dict[str, str | bool]:
    issues: list[str] = []
    java = _which("java")
    adb = _which("adb")
    if not java:
        issues.append("java")
    if not adb:
        issues.append("adb (push недоступен)")
    try:
        tc = resolve_toolchain()
    except ApkToolchainError as exc:
        return {
            "ok": False,
            "java": bool(java),
            "adb": bool(adb),
            "vendor": str(VENDOR_APKTOOLS),
            "error": str(exc),
            "issues": issues,
        }
    pk8, x509 = tc.sign_key_paths("deepal")
    if not pk8.is_file() or not x509.is_file():
        issues.append("ключи Deepal")
    return {
        "ok": not issues or issues == ["adb (push недоступен)"],
        "java": True,
        "adb": bool(adb),
        "vendor": str(VENDOR_APKTOOLS),
        "source": tc.source,
        "apktool": str(tc.apktool_jar),
        "issues": issues,
    }


def read_package_name(src_dir: Path) -> str | None:
    manifest = src_dir / "AndroidManifest.xml"
    if not manifest.is_file():
        return None
    try:
        import xml.etree.ElementTree as ET

        root = ET.parse(manifest).getroot()
        pkg = root.attrib.get("package")
        if pkg:
            return pkg.strip()
    except Exception:
        pass
    text = manifest.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'\bpackage="([^"]+)"', text)
    return match.group(1).strip() if match else None


def decompile_apk(apk_path: Path, *, force: bool = True) -> Path:
    apk_path = apk_path.resolve()
    if not apk_path.is_file():
        raise ApkToolchainError(f"APK не найден: {apk_path}")
    tc = resolve_toolchain()
    out_dir = apk_path.parent / f"{apk_path.stem}_src"
    if out_dir.exists() and force:
        shutil.rmtree(out_dir)
    cmd = [tc.java, "-jar", str(tc.apktool_jar), "d"]
    if force:
        cmd.append("-f")
    cmd.extend([str(apk_path), "-o", str(out_dir)])
    _run(cmd, label="apktool d")
    print(f"✅ Распаковано: {out_dir}", flush=True)
    return out_dir


def build_signed_apk(
    src_dir: Path,
    *,
    sign_profile: str = "deepal",
    custom_pk8: Path | None = None,
    custom_x509: Path | None = None,
    keep_src: bool = True,
) -> Path:
    src_dir = src_dir.resolve()
    if not src_dir.is_dir():
        raise ApkToolchainError(f"Папка исходников не найдена: {src_dir}")

    tc = resolve_toolchain()
    pk8, x509 = tc.sign_key_paths(sign_profile, custom_pk8=custom_pk8, custom_x509=custom_x509)
    if not pk8.is_file() or not x509.is_file():
        raise ApkToolchainError(f"Ключи подписи не найдены: {pk8} / {x509}")

    out_dir = src_dir.parent
    app_basename = src_dir.name
    build_apk = out_dir / f"{app_basename}.apk"
    aligned_apk = out_dir / f"{app_basename}-aligned.apk"
    signed_apk = out_dir / f"{app_basename}-signed.apk"

    for path in (build_apk, aligned_apk, signed_apk, Path(f"{signed_apk}.idsig")):
        if path.is_file():
            path.unlink()

    print(f"🏗️ Сборка: {src_dir}", flush=True)
    _run(
        [tc.java, "-jar", str(tc.apktool_jar), "b", str(src_dir), "-o", str(build_apk)],
        label="apktool b",
    )

    print(f"📏 zipalign → {aligned_apk}", flush=True)
    _run([str(tc.zipalign), "-f", "4", str(build_apk), str(aligned_apk)], label="zipalign")

    print(f"🔐 apksigner → {signed_apk}", flush=True)
    _run(
        [
            tc.java,
            "-jar",
            str(tc.apksigner_jar),
            "sign",
            "--v1-signing-enabled",
            "true",
            "--key",
            str(pk8),
            "--cert",
            str(x509),
            "--out",
            str(signed_apk),
            str(aligned_apk),
        ],
        label="apksigner",
    )

    _run(
        [tc.java, "-jar", str(tc.apksigner_jar), "verify", "--verbose", str(signed_apk)],
        label="verify",
    )

    for path in (build_apk, aligned_apk, Path(f"{signed_apk}.idsig")):
        if path.is_file():
            path.unlink()

    if not keep_src:
        shutil.rmtree(src_dir)

    print(f"✅ Готово: {signed_apk}", flush=True)
    return signed_apk


def find_signed_apk_for_module(module_dir: Path, package: str | None = None) -> Path | None:
    module_dir = module_dir.resolve()
    parent = module_dir.parent
    base = module_dir.name

    primary = parent / f"{base}-signed.apk"
    if primary.is_file():
        return primary

    if package:
        for candidate in sorted(parent.glob(f"*{package}*_src-signed.apk")):
            if candidate.is_file():
                return candidate
        for candidate in sorted(parent.glob(f"*{package}*-signed.apk")):
            if candidate.is_file():
                return candidate

    for candidate in sorted(parent.glob(f"{base}*.apk")):
        if candidate.name.endswith("-signed.apk"):
            return candidate
    return None


def _adb_run(tc: ApkToolchain, args: list[str], *, label: str = "adb") -> subprocess.CompletedProcess:
    if not tc.adb:
        raise ApkToolchainError("adb не найден в PATH. Установите Android platform-tools.")
    cmd = [tc.adb, *args]
    print(f"[{label}] $ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout.rstrip(), flush=True)
    if proc.stderr:
        print(proc.stderr.rstrip(), flush=True)
    return proc


def push_signed_apk(
    apk_path: Path,
    package: str,
    *,
    clear_cache: bool = True,
    kill_app: bool = True,
) -> None:
    apk_path = apk_path.resolve()
    if not apk_path.is_file():
        raise ApkToolchainError(f"Signed APK не найден: {apk_path}")
    if not package.strip():
        raise ApkToolchainError("Укажите package name (из AndroidManifest.xml).")

    tc = resolve_toolchain()
    pkg = package.strip()

    proc = _adb_run(tc, ["shell", "pm", "path", pkg], label="pm path")
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ApkToolchainError(
            f"adb: не удалось получить путь для {pkg}. Устройство подключено? pm path пустой."
        )
    line = proc.stdout.strip().splitlines()[0].strip()
    remote = line.removeprefix("package:").strip()
    if not remote:
        raise ApkToolchainError(f"adb: пустой remote path для {pkg}")

    print(f"📦 {pkg}", flush=True)
    print(f"   local:  {apk_path}", flush=True)
    print(f"   remote: {remote}", flush=True)

    _adb_run(tc, ["root"], label="adb root")
    _adb_run(tc, ["remount"], label="adb remount")
    proc = _adb_run(tc, ["push", str(apk_path), remote], label="adb push")
    if proc.returncode != 0:
        raise ApkToolchainError("adb push завершился с ошибкой")

    if clear_cache:
        print(f"🧹 Очистка dalvik-кэша для {pkg}", flush=True)
        _adb_run(
            tc,
            [
                "shell",
                f"rm -rf /data/dalvik-cache/arm64/*{pkg}* /data/dalvik-cache/arm/*{pkg}* "
                f"/data/resource-cache/*{pkg}* 2>/dev/null; true",
            ],
            label="cache",
        )

    if kill_app:
        proc = _adb_run(tc, ["shell", "pidof", pkg], label="pidof")
        pids = (proc.stdout or "").strip().replace("\r", "")
        if pids:
            _adb_run(tc, ["shell", "kill", "-9", *pids.split()], label="kill")

    print(f"✅ {pkg}", flush=True)


def push_module(module_dir: Path, *, package: str | None = None) -> None:
    module_dir = module_dir.resolve()
    pkg = (package or read_package_name(module_dir) or "").strip()
    if not pkg:
        raise ApkToolchainError(
            "Не удалось определить package из AndroidManifest.xml. Укажите вручную."
        )
    apk = find_signed_apk_for_module(module_dir, pkg)
    if apk is None:
        raise ApkToolchainError(
            f"Signed APK не найден рядом с модулем. Ожидается {module_dir.name}-signed.apk"
        )
    push_signed_apk(apk, pkg)
