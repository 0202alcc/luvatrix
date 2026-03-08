from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import subprocess
from pathlib import Path

ARCHIVE_WINDOW_PATH = Path('.gateflow/legacy_ops_planning_archive_window.json')
ALWAYS_ALLOWED = {
    'ops/planning/DEPRECATED.md',
}


def changed_files(base: str, head: str) -> list[str]:
    proc = subprocess.run(
        ['git', 'diff', '--name-only', f'{base}...{head}'],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or 'git diff failed')
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def load_window(today: dt.date) -> tuple[bool, list[str], str]:
    if not ARCHIVE_WINDOW_PATH.exists():
        return False, [], 'archive window file is missing'

    payload = json.loads(ARCHIVE_WINDOW_PATH.read_text(encoding='utf-8'))
    start = dt.date.fromisoformat(payload['start_date'])
    end = dt.date.fromisoformat(payload['end_date'])
    allow_paths = payload.get('allow_paths', [])
    if not isinstance(allow_paths, list):
        raise ValueError('allow_paths must be a list')

    is_active = start <= today <= end
    state = f'window active ({start}..{end})' if is_active else f'window inactive ({start}..{end})'
    return is_active, [str(item) for item in allow_paths], state


def is_allowed(path: str, *, window_active: bool, allow_patterns: list[str]) -> bool:
    if path in ALWAYS_ALLOWED:
        return True
    if not window_active:
        return False
    return any(fnmatch.fnmatch(path, pattern) for pattern in allow_patterns)


def main() -> int:
    parser = argparse.ArgumentParser(description='Fail CI when ops/planning files are modified outside approved archive window.')
    parser.add_argument('--base', default='HEAD~1', help='diff base ref/sha')
    parser.add_argument('--head', default='HEAD', help='diff head ref/sha')
    args = parser.parse_args()

    files = changed_files(args.base, args.head)
    planning_changes = sorted(path for path in files if path.startswith('ops/planning/'))
    if not planning_changes:
        print('PASS: no ops/planning changes detected')
        return 0

    window_active, allow_patterns, window_state = load_window(dt.date.today())
    violations = [
        path
        for path in planning_changes
        if not is_allowed(path, window_active=window_active, allow_patterns=allow_patterns)
    ]

    if not violations:
        print('PASS: ops/planning changes are within approved archive window allowlist')
        print(f'INFO: {window_state}')
        return 0

    print('FAIL: unauthorized ops/planning changes detected')
    print(f'INFO: {window_state}')
    print('Changed files under ops/planning:')
    for path in planning_changes:
        print(f'  - {path}')
    print('Violations:')
    for path in violations:
        print(f'  - {path}')
    print('Remediation:')
    print('  1. Move active planning changes to .gateflow/* instead of ops/planning/*.')
    print('  2. If this is approved archival work, update .gateflow/legacy_ops_planning_archive_window.json')
    print('     with bounded dates and allow_paths patterns, then rerun CI.')
    print('  3. Otherwise revert ops/planning edits from this PR.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
