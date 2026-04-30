# AGENTS

Repository-level operating rules and quick-start context for human and AI contributors.

## Read First
1. Inspect the code before planning or editing. Use `rg`, `rg --files`, targeted `sed`, and existing tests to understand current patterns.
2. Check `git status --short --branch` before changing files. The worktree may contain user or agent changes; do not revert unrelated work.
3. Prefer small, task-focused changes with matching tests. A task is complete only after relevant verification passes or the blocker is documented.

## Current Codebase Shape
1. `luvatrix/` is the public app-developer API package. Use `luvatrix.app` for stable app-facing imports such as `AppContext`, manifest helpers, platform constants, and install validation.
2. `luvatrix_core/` contains runtime internals:
   - `core/`: app protocol, manifest parsing, lifecycle/runtime loops, HDI, sensors, scene graph, window matrix, debug/audit support.
   - `targets/`: render target abstractions and adapters such as Metal, Vulkan, CPU scene, and web targets.
   - `platform/`: platform-specific integrations. Imports from `platform.macos`, `platform.ios`, and `platform.web` should stay lazy unless the selected render path needs them.
3. `luvatrix_ui/` contains first-party UI contracts, controls, text rendering, planes protocol/runtime, and planning/table helpers.
4. `luvatrix_plot/` contains plotting APIs, raster drawing, adapters, scales, and app-protocol compile helpers.
5. `main.py` is the CLI entrypoint. `luvatrix validate-app ...` validates app manifests and optional render dependencies; `luvatrix run-app ...` launches an app protocol folder.

## Packaging and Optional Runtime Policy
1. `luvatrix` is one Python distribution with optional extras, not split distributions.
2. Keep base dependencies usable for manifest loading, public API imports, and headless app validation/runs.
3. Platform-heavy dependencies must stay in extras:
   - `macos`: PyObjC/AppKit/Quartz/Metal runtime support.
   - `vulkan`: Python Vulkan binding only; native Vulkan SDK/MoltenVK is still installed outside pip.
   - `web`: websocket runtime support.
   - `ios`: reserved for Python-installable iOS helpers; native Xcode packaging remains outside pip.
   - `trading`: Coinbase/trading-dashboard dependencies.
4. Do not add eager top-level imports of macOS, iOS, Vulkan, or web modules from public API or CLI import paths. Missing extras should fail only when the matching renderer is selected, with an actionable install hint.

## App Protocol Conventions
1. App folders use `app.toml` plus a Python entrypoint such as `app_main:create`.
2. `app.toml` is the source of truth for app support declarations:
   - Use `platform_support = ["macos", "ios"]` for a shared Apple-platform app.
   - Use `[[variants]]` only when a platform or architecture needs a different `module_root` or `entrypoint`.
3. Keep app lifecycle objects compatible with `init(ctx)`, `loop(ctx, dt)`, and `stop(ctx)`.
4. Validate platform support and optional dependency availability through `luvatrix.app.check_app_install` or `luvatrix.app.validate_app_install`.

## Python Tooling Policy
1. Use `uv` for Python workflows:
   - `uv sync`
   - `uv run pytest ...`
   - `uv run python ...`
2. Do not use bare `python` or `pip` unless blocked by environment constraints. If blocked, document the reason and fallback.
3. For tests, prefer focused coverage first, then broaden only when the touched surface warrants it.

## Git and Branch Policy
1. Use descriptive branch names for significant work, such as `feature/platform-scoped-package` or `fix/lazy-platform-imports`.
2. Local git inspection, staging, commits, and branch-local checks are allowed without extra permission.
3. Merge, rebase, pull request, or push activity involving `main` requires explicit human permission.
4. Stage only files that belong to the current task. If unrelated changes exist, leave them untouched and mention them in the handoff.
5. Never use destructive git commands such as `git reset --hard` or broad restore/checkout commands unless the human explicitly asks.

## Pull Request Format
1. Use a concise title that names the behavior changed.
2. Include:
   - what changed,
   - why it changed,
   - tests or commands run,
   - any known limitations or follow-up work.

## Useful Verification Commands
1. Public API and optional install validation:
   - `uv run pytest tests/test_luvatrix_public_app_api.py`
2. App manifest and variant routing:
   - `uv run pytest tests/test_app_runtime.py -k "manifest or variant or platform_support"`
3. Headless CLI smoke:
   - `uv run python main.py validate-app examples/full_suite_interactive --render headless`
   - `uv run python main.py run-app examples/hello_world --render headless --ticks 1 --energy-safety off`
4. Broader runtime checks should be chosen based on touched modules, for example macOS renderer tests for `luvatrix_core/platform/macos/*` changes or planes tests for `luvatrix_ui/planes_*` changes.
