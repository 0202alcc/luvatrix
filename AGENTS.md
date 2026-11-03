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
   - `macos`: PyObjC/AppKit/Quartz/Metal runtime support, plus torch. `--render macos-metal` checks this extra. `--render macos` also checks `vulkan`.
   - `desktop`: torch for the CPU frame pipeline and parts of the repository test suite.
   - `dev`: matplotlib for development and examples.
   - `vulkan`: Python Vulkan binding only; native Vulkan SDK/MoltenVK is still installed outside pip. `--render macos` also requires this extra.
   - `web`: reserved extra with no pip dependencies. Browser apps use `build-web` and `serve-web`.
   - `ios`: reserved extra with no pip dependencies; native Xcode packaging remains outside pip.
   - `android`: reserved extra with no pip dependencies; the Android SDK and Gradle stay outside pip.
   - Trading-dashboard examples import a separate Coinbase API package. There is no `luvatrix[trading]` extra. `[tool.uv.sources]` names `coinbasetraderbot`, and that package is not a project dependency.
4. Do not add eager top-level imports of macOS, iOS, Vulkan, or web modules from public API or CLI import paths. Missing extras should fail only when the matching renderer is selected, with an actionable install hint.

## App Protocol Conventions
1. App folders use `app.toml` plus a Python entrypoint such as `app_main:create`.
2. `app.toml` is the source of truth for app support declarations:
   - Use `platform_support = ["macos", "ios"]` for a shared Apple-platform app.
   - Use `[[variants]]` only when a platform or architecture needs a different `module_root` or `entrypoint`.
3. Keep app lifecycle objects compatible with `init(ctx)`, `loop(ctx, dt)`, and `stop(ctx)`.
4. Validate platform support and optional dependency availability through `luvatrix.app.check_app_install` or `luvatrix.app.validate_app_install`.
5. Scroll-heavy scene apps should build stable content-space primitives with `App.frame(..., retained=True, content_offset=(x, y))`. After the retained scene exists, use `App.set_scene_content_offset(x, y)` for transform-only revisions that do not rebuild nodes. On native Metal this preserves geometry buffers and applies scrolling as a GPU transform; do not pre-translate every primitive unless its content actually changed.
6. Apps without continuous animation may call `set_continuous_render(False)` and use `invalidate()` after data or state changes. Input consumed through `InputManager.snapshot()` invalidates automatically.
7. Use `luvatrix.app.ScrollbarController` for custom scene scrollbars. It supplies track clicking, thumb-anchor dragging, pointer capture outside the track, release handling, and horizontal/vertical parity; keep painted scrollbar geometry separate from a comfortably sized interaction target.

## Python Tooling Policy
1. Use `uv` for Python workflows. Python is 3.14, and `.python-version` selects `3.14+freethreaded`.
   - `uv sync --extra desktop`
   - `uv run --extra desktop --with pytest pytest ...`
   - `uv run python ...`
2. `pytest` is not a project dependency. Several runtime tests import `torch` at collection time, so pass `--extra desktop` as well as `--with pytest`.
3. Do not use bare `python` or `pip` unless blocked by environment constraints. If blocked, document the reason and fallback.
4. For tests, prefer focused coverage first, then broaden only when the touched surface warrants it.

## Test-First Development Policy
1. For every behavior change or bug fix, write or update the test that defines the expected behavior before implementing the production change.
2. Confirm the new or changed test fails for the expected reason before implementation, then make the smallest change that makes it pass.
3. Tests must describe externally meaningful behavior and include relevant error or boundary cases; do not couple assertions to implementation details merely to raise coverage.
4. Keep tests and implementation on the same feature branch. Separate test and implementation commits are encouraged when practical, but commit shape is not a merge requirement.
5. Behavior-changing pull requests must complete the test-first evidence in the pull request template and pass the `required-tests` check before merging into `dev`.
6. Documentation, metadata, generated artifacts, and provably behavior-neutral mechanical refactors may use the documented exception, with the reason recorded in the pull request.
7. See `CONTRIBUTING.md` for the complete workflow and reviewer expectations.

## Security Gate Policy
1. Pull requests into `dev`, `staging`, and `main` must pass the aggregate `security-review` check described in `SECURITY.md`.
2. Do not weaken or suppress dependency, secret, Python SAST, or GitHub Actions findings merely to make CI green. Document narrow false-positive or accepted-risk exceptions.
3. The agent-review files under `.github/security/` are a provider-neutral contract only. Do not add credentials or enable model execution without an explicit security review of the workflow trust boundary.

## Git and Branch Policy
1. Use one descriptive feature branch per feature, such as `feature/platform-scoped-package` or `fix/lazy-platform-imports`.
2. Use the promotion ladder `feature/* -> dev -> staging -> main`.
3. Every promotion happens through a pull request: feature branches target `dev`, `dev` targets `staging`, and `staging` targets `main`.
4. Treat `main` as production and `staging` as the pre-production soak branch for catching integration issues before release.
5. Local git inspection, staging, commits, and branch-local checks are allowed without extra permission.
6. Merge, rebase, pull request, or push activity involving `main` requires explicit human permission.
7. Stage only files that belong to the current task. If unrelated changes exist, leave them untouched and mention them in the handoff.
8. Never use destructive git commands such as `git reset --hard` or broad restore/checkout commands unless the human explicitly asks.

## Pull Request Format
1. Use a concise title that names the behavior changed.
2. Include:
   - what changed,
   - why it changed,
   - tests or commands run,
   - any known limitations or follow-up work.
3. For behavior changes, include the expected behavior, the test-first failure observed, and the passing verification. Do not mark both test-first checklist alternatives.

## Useful Verification Commands
1. Public API and optional install validation:
   - `uv run --extra desktop --with pytest pytest tests/test_luvatrix_public_app_api.py`
2. App manifest and variant routing:
   - `uv run --extra desktop --with pytest pytest tests/test_app_runtime.py -k "manifest or variant or platform_support"`
3. Headless CLI smoke:
   - `uv run python main.py validate-app examples/hello_world --render headless`
   - `uv run python main.py run-app examples/hello_world --render headless --ticks 1 --energy-safety off`
   - `uv run python main.py validate-app examples/full_suite_interactive --render web`
4. `examples/full_suite_interactive` lists `macos`, `ios`, `android`, and `web`. Headless validation on Linux cannot pick one of those platforms. Use `--render web`, or another single platform target, for that app.
5. Broader runtime checks should be chosen based on touched modules, for example macOS renderer tests for `luvatrix_core/platform/macos/*` changes or planes tests for `luvatrix_ui/planes_*` changes.
6. Retained scene-scroll throughput: `uv run python tools/perf/macos_scene_scroll_harness.py`.

## Cursor Cloud specific instructions
1. This repo pins Python `3.14+freethreaded` in `.python-version`. Ubuntu's system Python is too old. Install that interpreter with `uv python install 3.14+freethreaded`. Cloud Agent login shells do not load `~/.bashrc`, so `uv` and `uvx` must be on the default PATH (`/usr/local/bin`).
2. Install locked dependencies with `uv sync --frozen --extra desktop`. The required tests import torch from that extra. `pytest` is not a project dependency; invoke it as `uv run --extra desktop --with pytest pytest`.
3. On Linux, headless smoke uses `examples/hello_world`, which declares no `platform_support`: `uv run python main.py validate-app examples/hello_world --render headless` and `uv run python main.py run-app examples/hello_world --render headless --ticks 1 --energy-safety off`. `examples/full_suite_interactive --render headless` cannot infer a platform among android, ios, macos, and web; pass an explicit target such as `--render web`.
4. macOS, iOS, and Android GUI targets do not run in this Linux VM. `validate-app` can still check a platform-scoped manifest, such as `examples/camera --render android-emulator`, without the Android SDK or Xcode. Launching those renderers needs the native toolchain.
5. `[tool.uv.sources] coinbasetraderbot` points at `../CoinbaseTraderBot` and is not a lockfile dependency. `uv sync` succeeds without that sibling checkout.
