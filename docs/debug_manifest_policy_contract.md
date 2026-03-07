# Debug Manifest Policy Contract (T-2910)

## Scope
1. Introduce app-manifest-level debug policy controls without breaking legacy app behavior.
2. Keep milestone scope macOS-first in this phase.
3. Declare non-mac behavior explicitly as capability stubs.

## Manifest Table
Use optional `[debug_policy]` in `app.toml`:

```toml
[debug_policy]
schema_version = 1
enable_default_debug_root = true
non_macos_behavior = "explicit_stub"
non_macos_stub_capability = "debug.policy.non_macos.stub"
non_macos_unsupported_reason = "macOS-first phase: explicit stub only"
```

Optional explicit-disable path (approval required):

```toml
[debug_policy]
schema_version = 1
enable_default_debug_root = false
disable_debug_root_approval = "A-037-policy-review"
```

## Compatibility Rules
1. If `[debug_policy]` is absent, runtime defaults preserve legacy behavior (`enable_default_debug_root=true` on macOS).
2. `schema_version` must be `1` in this phase.
3. `non_macos_behavior` must be `explicit_stub` in this phase.
4. If `enable_default_debug_root=false`, `disable_debug_root_approval` is required.

## Platform Profile Resolution
1. `macos`: debug root is enabled by default unless explicitly disabled with approval.
2. `windows` and `linux`: debug root is unsupported in this phase and must expose explicit stub capability + unsupported reason.

## Verification
```bash
uv run pytest tests -k "debug_manifest or legacy_debug_conformance" -q
```
