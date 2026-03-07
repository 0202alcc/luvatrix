# Debug Menu Adapter Spec (T-2903)

## Contract
1. The debug menu adapter surface must declare per-platform support explicitly.
2. Supported platforms declare full menu IDs plus capability IDs.
3. Unsupported platforms declare stub capabilities and an explicit unsupported reason.

## Phase Policy
1. Current phase is macOS-first.
2. `windows` and `linux` adapters are explicit stubs in this phase.
3. No implicit fallback behavior is allowed for unsupported platforms.

## Platform Matrix
1. `macos`
   - `supported=true`
   - menu IDs: canonical default debug menu IDs
   - capabilities: canonical one-to-one debug capability IDs
2. `windows`
   - `supported=false`
   - `supported_menu_ids=[]`
   - `declared_capabilities=["debug.adapter.windows.stub"]`
   - `unsupported_reason="macOS-first phase: explicit stub only"`
3. `linux`
   - `supported=false`
   - `supported_menu_ids=[]`
   - `declared_capabilities=["debug.adapter.linux.stub"]`
   - `unsupported_reason="macOS-first phase: explicit stub only"`

## Bootstrap and Verification Flow (R-039)
1. Sync runtime dependencies before running any macOS menu verification:
   - `uv sync --extra macos --extra vulkan`
2. Run deterministic preflight and smoke manifest generation:
   - `PYTHONPATH=. uv run python ops/ci/r039_macos_menu_smoke.py`
3. Execute required verification sequence in this order:
   - `PYTHONPATH=. uv run --with pytest pytest tests -k "debug_menu_dispatch or debug_manifest_policy or macos_menu_integration" -q`
   - `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render macos --ticks 120`
   - `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/input_sensor_logger --render macos --ticks 120`
   - `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py`
   - `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id R-039`
