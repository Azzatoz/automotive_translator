# APK tools (vendor/apktools)

Инструменты для распаковки, сборки и подписи APK **внутри репозитория** — без привязки к `/usr/local/bin` или домашним путям.

## Первый запуск

```bash
python3 scripts/setup_apk_tools.py
```

Скрипт копирует в эту папку:

- `apktool.jar`, `apksigner.jar`, `zipalign`
- ключи Deepal и testkey (`keys/`)

Источники (по порядку): переменная `APKTOOLS_ROOT`, `/opt/apktools/Resources`, `zipalign` из `ANDROID_HOME`.

## Требования на ПК

- **Java** (OpenJDK 11+) в `PATH`
- **adb** — только для push на устройство (platform-tools)

## CLI

```bash
python3 scripts/apk_toolchain_cli.py status
python3 scripts/apk_toolchain_cli.py decompile /path/app.apk
python3 scripts/apk_toolchain_cli.py build /path/App_src --sign deepal
python3 scripts/apk_toolchain_cli.py push --module /path/App_src --package com.example.app
```

## GUI

Вкладка **Действия → 3. APK** или ПКМ по модулю: «Собрать APK», «Push APK на устройство».

Signed APK создаётся рядом с модулем: `ИмяМодуля_src-signed.apk`.
