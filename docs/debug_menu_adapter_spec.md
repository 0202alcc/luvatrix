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
