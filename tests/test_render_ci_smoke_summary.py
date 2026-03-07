from __future__ import annotations

from ops.ci.render_ci_smoke_summary import render_summary


def test_render_summary_with_base_url() -> None:
    payload = {
        "checks": [
            {"name": "gateflow-links", "status": "PASS", "artifact": "gateflow-links.txt"},
            {"name": "flaky-quarantine", "status": "PASS", "artifact": "flaky-quarantine.txt"},
        ]
    }
    output = render_summary(payload, "https://example.invalid/artifacts")
    assert "P-013 CI Smoke Signals" in output
    assert "[gateflow-links.txt](https://example.invalid/artifacts/gateflow-links.txt)" in output


def test_render_summary_without_artifact_file() -> None:
    payload = {"checks": [{"name": "x", "status": "FAIL", "artifact": ""}]}
    output = render_summary(payload, "")
    assert "| x | FAIL | n/a |" in output
