from __future__ import annotations

import json
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/performance/data/android_activity_rebind_0_2_3.json"


def test_android_activity_rebind_evidence_summary_matches_raw_trials() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    baseline = evidence["measurements"]["baseline_0_2_2"]
    candidate = evidence["measurements"]["candidate_0_2_3"]
    summary = evidence["summary"]

    for metric in ("cold_launch_s", "activity_recreation_s"):
        baseline_median = median(baseline[metric])
        candidate_median = median(candidate[metric])
        improvement = (baseline_median - candidate_median) / baseline_median * 100.0

        assert summary[metric]["baseline_median"] == round(baseline_median, 3)
        assert summary[metric]["candidate_median"] == round(candidate_median, 3)
        assert summary[metric]["improvement_percent"] == round(improvement, 2)
