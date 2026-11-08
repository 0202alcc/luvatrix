# Contributing to Luvatrix

## Branch and Promotion Model

Keep tests and implementation together on one task-focused branch. The integration ladder is:

`feature/* -> dev (local) -> staging -> main`

`dev` is a local integration branch, not a remote branch. Integrate feature and fix branches into local `dev` as work progresses. When the local `dev` state is ready for integration testing, push it to the remote `staging` branch; repository automations land validated staging state onto `main`, and pushes to `main` trigger the PyPI publish workflow, which publishes when it detects a version not yet on PyPI. The `dev`-scoped `required-tests` workflow stays dormant until a `dev` branch exists on the remote; while it does not, run the same check locally before pushing to `staging`. Test-first development is a requirement within feature work, not an additional long-lived branch.

## Test-First Workflow

For every behavior change or bug fix:

1. State the expected behavior in observable terms, including important error and boundary cases.
2. Write or update the test before implementing the behavior.
3. Run the focused test and confirm that it fails for the expected reason. A failure caused by a typo, broken fixture, or unrelated defect is not useful test-first evidence.
4. Implement the smallest production change that satisfies the behavior.
5. Re-run the focused test, then broaden verification in proportion to the affected surface.
6. Record the before-and-after evidence and commands in the pull request template.

Tests should verify public contracts or meaningful component behavior rather than mirror private implementation details. A regression test must fail without the fix. Avoid weakening, deleting, or broadly mocking an existing assertion solely to make a change pass.

### Commit Shape

Separate test and implementation commits are encouraged when the history remains clear, for example:

- `test: define calendar refresh behavior`
- `feat: implement calendar refresh behavior`

This split is supporting evidence, not a merge requirement. Tests and implementation must stay on the same feature branch, and every pushed commit intended for review should be kept green when practical.

## Pull Request Requirements

Behavior-changing pull requests must:

- describe the expected behavior;
- identify the test added or updated before implementation;
- state how that test failed before the implementation;
- include focused and relevant broader verification commands;
- include negative, boundary, or error-path coverage when relevant; and
- run the same checks the `required-tests` GitHub Actions workflow enforces; that check triggers on `dev` activity, and while `dev` is local-only the equivalent commands must pass on the feature branch before pushing to `staging`.

All pushes and pull requests touching `dev`, `staging`, or `main` must pass the aggregate `security-review` check. See `SECURITY.md` for its deterministic scanners and finding-handling policy.

Reviewers should evaluate whether the tests independently express the intended contract. Passing tests are necessary but are not sufficient when the test merely repeats the implementation's assumptions.

If a `dev` branch is later published to the remote, repository administrators should configure the `dev` branch protection ruleset to require the `required-tests` status check. Workflow files define the check, but GitHub branch protection makes it mandatory.

## Exceptions

An automated test may not apply to documentation-only changes, repository metadata, generated artifacts, or a provably behavior-neutral mechanical refactor. In that case, select the exception in the pull request template and explain:

- why runtime behavior cannot change;
- what validation was performed instead; and
- whether follow-up automated coverage is needed.

Changes to public APIs, runtime behavior, bug fixes, dependency behavior, build logic, or CI enforcement do not qualify merely because they are small.

## Running Tests

Use `uv` for repository Python workflows. Start with the narrowest relevant command, for example:

```sh
uv run --extra desktop --with pytest pytest -q tests/test_app_runtime.py
```

Before requesting review, run the cross-platform contract suite used by the required `dev` gate when the touched surface warrants it:

```sh
uv run --extra desktop --with pytest pytest -q \
  tests/test_repository_test_policy.py \
  tests/test_luvatrix_public_app_api.py \
  tests/test_app_runtime.py \
  tests/test_main_cli.py \
  tests/test_scene_runtime.py \
  tests/test_planes_runtime.py \
  tests/test_display_runtime.py
```

This baseline does not replace focused tests for the changed code. Platform-specific changes should add or run the focused tests named in `AGENTS.md`. Optional workflows such as `macos-gui-smoke.yml` and `android-accelerator-wheels.yml` are not required checks on every pull request.
