from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


MILESTONES_PATH = Path('.gateflow/milestones.json')
CLOSEOUT_DIR = Path('.gateflow/closeout')


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def is_active_or_recent(milestone: dict[str, object], cutoff: dt.date) -> bool:
    status = str(milestone.get('status', '')).strip()
    if status in {'In Progress', 'Planned'}:
        return True
    events = milestone.get('lifecycle_events', [])
    if not isinstance(events, list):
        return False
    for event in events:
        if not isinstance(event, dict):
            continue
        date_value = event.get('date')
        if isinstance(date_value, str):
            try:
                if parse_date(date_value) >= cutoff:
                    return True
            except ValueError:
                continue
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description='Reconcile active/recent milestones against .gateflow closeout packets.')
    parser.add_argument('--days', type=int, default=14, help='recent window in days')
    parser.add_argument('--out', type=Path, default=Path('.gateflow/reconciliation/p-048_active_milestone_reconciliation.json'))
    args = parser.parse_args()

    payload = json.loads(MILESTONES_PATH.read_text(encoding='utf-8'))
    items = payload.get('items', [])
    if not isinstance(items, list):
        raise ValueError('milestones items must be a list')

    today = dt.date.today()
    cutoff = today - dt.timedelta(days=max(args.days, 0))

    checked: list[dict[str, object]] = []
    missing: list[str] = []

    for milestone in items:
        if not isinstance(milestone, dict):
            continue
        if not is_active_or_recent(milestone, cutoff):
            continue
        milestone_id = str(milestone.get('id', '')).strip()
        if not milestone_id:
            continue
        closeout_path = CLOSEOUT_DIR / f'{milestone_id.lower()}_closeout.md'
        exists = closeout_path.exists()
        checked.append(
            {
                'id': milestone_id,
                'status': milestone.get('status'),
                'closeout_path': str(closeout_path),
                'closeout_exists': exists,
            }
        )
        if not exists:
            missing.append(milestone_id)

    result = {
        'generated_at': dt.datetime.now(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'window_days': args.days,
        'checked_count': len(checked),
        'missing_count': len(missing),
        'missing_milestone_ids': missing,
        'items': checked,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding='utf-8')

    if missing:
        print(json.dumps(result, indent=2))
        print('FAIL: missing .gateflow closeout packets for active/recent milestones')
        return 1

    print(json.dumps(result, indent=2))
    print('PASS: all active/recent milestones have .gateflow closeout packets')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
