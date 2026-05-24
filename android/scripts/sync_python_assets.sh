#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-examples/full_suite_interactive}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY_DST="$REPO_ROOT/android/app/src/main/python"
if [[ "$APP_DIR" = /* ]]; then
  APP_SRC="$APP_DIR"
  APP_LABEL="${APP_DIR#$REPO_ROOT/}"
else
  APP_SRC="$REPO_ROOT/$APP_DIR"
  APP_LABEL="$APP_DIR"
fi

mkdir -p "$PY_DST"

copy_tree() {
  local src="$1"
  local dst="$2"
  rm -rf "$dst"
  rsync -a --delete \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    --exclude ".pytest_cache" \
    "$src/" "$dst/"
}

copy_tree "$REPO_ROOT/luvatrix" "$PY_DST/luvatrix"
copy_tree "$REPO_ROOT/luvatrix_core" "$PY_DST/luvatrix_core"
copy_tree "$REPO_ROOT/luvatrix_ui" "$PY_DST/luvatrix_ui"
copy_tree "$REPO_ROOT/luvatrix_plot" "$PY_DST/luvatrix_plot"

rm -rf "$PY_DST/examples"
mkdir -p "$PY_DST/examples"
copy_tree "$APP_SRC" "$PY_DST/luvatrix_app"
copy_tree "$APP_SRC" "$PY_DST/examples/$(basename "$APP_SRC")"

cat > "$PY_DST/examples/__init__.py" <<'PY'
# Namespace marker for bundled Luvatrix examples.
PY

touch "$PY_DST/examples/$(basename "$APP_SRC")/__init__.py"
touch "$PY_DST/luvatrix_app/__init__.py"

"${PYTHON:-python3}" - "$APP_SRC" "$PY_DST/examples/$(basename "$APP_SRC")/_luvatrix_bundle.py" <<'PY'
import pathlib
import pprint
import sys

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
bundle = {
    "APP_TOML": (src / "app.toml").read_text(encoding="utf-8"),
    "APP_MAIN": (src / "app_main.py").read_text(encoding="utf-8"),
}
dst.write_text(
    "APP_TOML = " + pprint.pformat(bundle["APP_TOML"]) + "\n"
    "APP_MAIN = " + pprint.pformat(bundle["APP_MAIN"]) + "\n",
    encoding="utf-8",
)
PY

CONFIG="$REPO_ROOT/android/app/src/main/assets/luvatrix_launch_config.json"
if [[ ! -f "$CONFIG" ]]; then
  cat > "$CONFIG" <<JSON
{
  "app_dir": "luvatrix_app",
  "source_app_dir": "$APP_LABEL",
  "native_width": 393,
  "native_height": 852,
  "render_mode": "auto",
  "render_scale": 1.0,
  "target_fps": 60,
  "present_fps": 60
}
JSON
fi
cp "$CONFIG" "$PY_DST/luvatrix_launch_config.json"

echo "[android] synced Python assets for $APP_LABEL"
