#!/usr/bin/env bash
# fill_values_ru_from_library.py — библиотека, затем Google; отчёт в tools/reports/
set -euo pipefail
TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
REQ="$TOOLS_DIR/requirements-fill-values-ru.txt"
PY="${PYTHON:-python3}"
PROJECT_ROOT="$(cd "$TOOLS_DIR/.." && pwd)"

# Предустановленные корни (если каталог существует)
declare -a ROOT_PRESET_LABELS=()
declare -a ROOT_PRESET_PATHS=()

_add_root_preset() {
  local label="$1"
  local path="$2"
  if [[ -d "$path" ]]; then
    ROOT_PRESET_LABELS+=("$label")
    ROOT_PRESET_PATHS+=("$(cd "$path" && pwd)")
  fi
}

_add_root_preset "Текущий проект (On translate)" "$PROJECT_ROOT"
_add_root_preset "Dorest translate/Translated" "$PROJECT_ROOT/../Translated"

# Типичные пути прошивок (см. tools/README)
for candidate in \
  "$PROJECT_ROOT/../../Rest 4.1.1/Translated" \
  "$PROJECT_ROOT/../../Dorest 3.2.0/dorest 320" \
  "/media/devv/10949c9f-ce94-43f9-9784-be7b8cc34bc92/Voyah/Dorest translate/Translated"; do
  [[ -d "$candidate" ]] || continue
  resolved="$(cd "$candidate" && pwd)"
  seen=0
  for p in "${ROOT_PRESET_PATHS[@]}"; do
    [[ "$p" == "$resolved" ]] && seen=1 && break
  done
  [[ "$seen" -eq 1 ]] && continue
  case "$candidate" in
    *"Rest 4.1.1"*) _add_root_preset "Rest 4.1.1/Translated" "$candidate" ;;
    *"dorest 320"*) _add_root_preset "Dorest 3.2.0/dorest 320" "$candidate" ;;
    *) _add_root_preset "$(basename "$(dirname "$candidate")")/$(basename "$candidate")" "$candidate" ;;
  esac
done

_interactive_fill() {
  echo ""
  echo "=== Перевод APK → values-ru ==="
  echo ""
  echo "С какого языка переводить (оригинал в res/values)?"
  local lang_items=("Китайский (zh-CN)" "Английский (en)")
  PS3=$'\nВыберите язык [1-2]: '
  select _ in "${lang_items[@]}"; do
    case "${REPLY:-}" in
      1) SOURCE_LANG="zh-CN"; break ;;
      2) SOURCE_LANG="en"; break ;;
      *) echo "Введите 1 или 2." ;;
    esac
  done
  echo "→ --source-lang $SOURCE_LANG"
  echo ""

  local default_root="${ROOT_PRESET_PATHS[0]:-$PROJECT_ROOT}"
  echo "Папка --root: внутри лежат модули *_src с res/values и res/values-ru."
  echo "(Подсказка: Rest 4.1.1 → .../Translated; Dorest 3.2.0 → .../dorest 320)"
  echo ""

  local root_items=("${ROOT_PRESET_LABELS[@]}" "Ввести путь вручную")
  PS3=$'\nВыберите каталог [1-'"${#root_items[@]}"']: '
  select _ in "${root_items[@]}"; do
    local idx=$((REPLY - 1))
    if [[ "$idx" -ge 0 && "$idx" -lt "${#ROOT_PRESET_PATHS[@]}" ]]; then
      ROOT_PATH="${ROOT_PRESET_PATHS[$idx]}"
      break
    fi
    if [[ "$idx" -eq "${#ROOT_PRESET_PATHS[@]}" ]]; then
      local input
      read -r -e -p "Путь к каталогу [$default_root]: " input
      ROOT_PATH="${input:-$default_root}"
      ROOT_PATH="${ROOT_PATH/#\~/$HOME}"
      break
    fi
    echo "Введите номер из списка."
  done

  if [[ ! -d "$ROOT_PATH" ]]; then
    echo "Ошибка: каталог не найден: $ROOT_PATH" >&2
    exit 1
  fi
  ROOT_PATH="$(cd "$ROOT_PATH" && pwd)"
  echo "→ --root $ROOT_PATH"
  echo ""
}

if [[ $# -eq 0 ]]; then
  _interactive_fill
  set -- --root "$ROOT_PATH" --source-lang "$SOURCE_LANG"
fi

if ! "$PY" -c "from deep_translator import GoogleTranslator" 2>/dev/null; then
  echo "[run_fill_values_ru_from_library] ставлю deep-translator для $("$PY" -c 'import sys; print(sys.executable)')..."
  if [[ -f "$REQ" ]]; then
    "$PY" -m pip install --user --break-system-packages -r "$REQ"
  else
    "$PY" -m pip install --user --break-system-packages deep-translator
  fi
fi

export PYTHONUNBUFFERED=1
exec "$PY" "$TOOLS_DIR/fill_values_ru_from_library.py" "$@"
