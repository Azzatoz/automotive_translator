#!/usr/bin/env bash
# Запуск fill_values_ru.py; при отсутствии deep-translator ставит его тем же Python (PEP 668).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REQ="$TOOLS_ROOT/requirements/fill-values-ru.txt"
PY="${PYTHON:-python3}"

if ! "$PY" -c "from deep_translator import GoogleTranslator" 2>/dev/null; then
  echo "[run_fill_values_ru] не найден deep-translator для $("$PY" -c 'import sys; print(sys.executable)') — ставлю..."
  if [[ -f "$REQ" ]]; then
    "$PY" -m pip install --user --break-system-packages -r "$REQ"
  else
    "$PY" -m pip install --user --break-system-packages deep-translator
  fi
fi

exec "$PY" "$SCRIPT_DIR/fill_values_ru.py" "$@"
