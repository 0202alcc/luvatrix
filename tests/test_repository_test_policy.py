from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_test_first_policy_is_documented() -> None:
    policy = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "feature/* -> dev -> staging -> main" in policy
    assert "Write or update the test before implementing the behavior" in policy
    assert "separate test and implementation commits" in policy.lower()
    assert "Exceptions" in policy


def test_behavior_change_pr_template_requires_test_evidence() -> None:
    template = (ROOT / ".github" / "pull_request_template.md").read_text(
        encoding="utf-8"
    )

    assert "Expected behavior" in template
    assert "Test-first evidence" in template
    assert "Test added or updated before implementation" in template
    assert "No automated test applies" in template
    assert "Commands run" in template


def test_dev_prs_have_a_general_required_test_workflow() -> None:
    workflow = (ROOT / ".github" / "workflows" / "dev-required-tests.yml").read_text(
        encoding="utf-8"
    )

    assert "branches: [dev]" in workflow
    assert "name: required-tests" in workflow
    for suite in (
        "test_repository_test_policy.py",
        "test_luvatrix_public_app_api.py",
        "test_app_runtime.py",
        "test_main_cli.py",
        "test_scene_runtime.py",
        "test_planes_runtime.py",
        "test_display_runtime.py",
    ):
        assert suite in workflow


def test_promotions_have_a_deterministic_security_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "security-review.yml").read_text(
        encoding="utf-8"
    )

    assert "branches: [dev, staging, main]" in workflow
    assert "name: security-review" in workflow
    for scanner in ("pip-audit", "bandit", "gitleaks", "zizmor"):
        assert scanner in workflow.lower()


def test_agent_security_review_has_a_provider_neutral_contract() -> None:
    schema = (
        ROOT / ".github" / "security" / "agent-review-output.schema.json"
    ).read_text(encoding="utf-8")
    prompt = (ROOT / ".github" / "security" / "agent-review-prompt.md").read_text(
        encoding="utf-8"
    )

    for field in ("severity", "path", "line", "title", "rationale", "remediation"):
        assert f'"{field}"' in schema
    assert "untrusted" in prompt.lower()
    assert "Do not execute" in prompt
