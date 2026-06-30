#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-.}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$APP_DIR" "$PROJECT_DIR" <<'PY'
from pathlib import Path
import sys

from luvatrix_core.platform.android.runner import sync_android_python_assets, write_android_launch_config

app_dir = Path(sys.argv[1]).resolve()
project_dir = Path(sys.argv[2]).resolve()
write_android_launch_config(app_dir, project_dir=project_dir)
sync_android_python_assets(app_dir, project_dir=project_dir)
PY
