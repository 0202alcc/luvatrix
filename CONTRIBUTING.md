# Contributing to Luvatrix

## Branch and Promotion Model

Keep tests and implementation together on one task-focused branch. The promotion ladder remains:

`feature/* -> dev -> staging -> main`

Feature and fix pull requests target `dev`; `dev` promotes to `staging`; and `staging` promotes to `main`. Test-first development is a requirement within feature work, not an additional long-lived branch.

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
- pass the `required-tests` GitHub Actions check before merging into `dev`.

All pull requests into `dev`, `staging`, or `main` must also pass the aggregate `security-review` check. See `SECURITY.md` for its deterministic scanners and finding-handling policy.

Reviewers should evaluate whether the tests independently express the intended contract. Passing tests are necessary but are not sufficient when the test merely repeats the implementation's assumptions.

Repository administrators should configure the `dev` branch protection ruleset to require the `required-tests` status check. Workflow files define the check, but GitHub branch protection makes it mandatory.

## Exceptions

An automated test may not apply to documentation-only changes, repository metadata, generated artifacts, or a provably behavior-neutral mechanical refactor. In that case, select the exception in the pull request template and explain:

- why runtime behavior cannot change;
- what validation was performed instead; and
- whether follow-up automated coverage is needed.

Changes to public APIs, runtime behavior, bug fixes, dependency behavior, build logic, or CI enforcement do not qualify merely because they are small.

## Running Tests

Use `uv` for repository Python workflows. Start with the narrowest relevant command, for example:

```sh
uv run --with pytest pytest -q tests/test_app_runtime.py
```

Before requesting review, run the cross-platform contract suite used by the required `dev` gate when the touched surface warrants it:

```sh
uv run --with pytest pytest -q \
  tests/test_repository_test_policy.py \
  tests/test_luvatrix_public_app_api.py \
  tests/test_app_runtime.py \
  tests/test_main_cli.py \
  tests/test_scene_runtime.py \
  tests/test_planes_runtime.py \
  tests/test_display_runtime.py
```

This baseline does not replace focused tests for the changed code. Platform-specific changes require the relevant macOS, iOS, Android, Vulkan, or web checks documented in `AGENTS.md` and enforced by specialized workflows.
