# App Protocol Variant Routing Guide

This guide expands App Protocol variant routing behavior for first-party Luvatrix apps.

## 1. Routing Inputs

Runtime variant selection uses:

1. host OS (normalized, for example `Darwin` -> `macos`)
2. host architecture (normalized, for example `aarch64` -> `arm64`)
3. `platform_support` from `app.toml` (optional gate)
4. `[[variants]]` list from `app.toml` (optional variant mapping)

## 2. Resolution Precedence

Selection order is deterministic:

1. reject early if `platform_support` exists and does not include host OS
2. collect variants matching host OS
3. if a variant declares `arch`, keep it only when host arch matches
4. choose most specific variant: arch-specific variants before OS-only variants
5. break ties by variant `id` lexicographic order
6. if no variants are declared, use manifest default entrypoint/module root

## 3. Single-Variant Manifest Example

`app.toml`:

```toml
app_id = "sample.single_variant"
protocol_version = "1"
entrypoint = "app_main:create"
required_capabilities = ["window.write"]
optional_capabilities = []
platform_support = ["macos"]

[[variants]]
id = "mac-arm64"
os = ["macos"]
arch = ["arm64"]
module_root = "variants/macos_arm64"
entrypoint = "variant_main:create"
```

Run command:

```bash
uv run --python 3.14 python main.py run-app /path/to/sample.single_variant --render headless --ticks 120
```

Expected behavior on `macos/arm64`:

1. selected variant id: `mac-arm64`
2. effective entrypoint: `variant_main:create`
3. effective module root: `variants/macos_arm64`

## 4. Multi-Variant Manifest Example

`app.toml`:

```toml
app_id = "sample.multi_variant"
protocol_version = "1"
entrypoint = "app_main:create"
required_capabilities = ["window.write"]
optional_capabilities = []
platform_support = ["macos", "linux"]

[[variants]]
id = "mac-any"
os = ["macos"]

[[variants]]
id = "mac-arm64"
os = ["macos"]
arch = ["arm64"]
module_root = "variants/macos_arm64"
entrypoint = "variant_main:create"

[[variants]]
id = "linux-x86_64"
os = ["linux"]
arch = ["x86_64"]
module_root = "variants/linux_x86_64"
```

Resolution examples:

1. host `macos/arm64` -> `mac-arm64`
2. host `macos/x86_64` -> `mac-any`
3. host `linux/x86_64` -> `linux-x86_64`

Run command:

```bash
uv run --python 3.14 python main.py run-app /path/to/sample.multi_variant --render headless --ticks 120
```

## 5. Failure Case: Unsupported Platform

Manifest:

```toml
app_id = "sample.unsupported"
protocol_version = "1"
entrypoint = "app_main:create"
required_capabilities = ["window.write"]
optional_capabilities = []
platform_support = ["linux"]
```

On host OS `macos`, runtime rejects before lifecycle load with an error equivalent to:

`app <id> does not support host os <host>; supported=<list>`

## 6. Failure Case: Escaping `module_root`

Manifest:

```toml
app_id = "sample.bad_module_root"
protocol_version = "1"
entrypoint = "app_main:create"
required_capabilities = ["window.write"]
optional_capabilities = []

[[variants]]
id = "bad"
os = ["macos"]
module_root = "../escape"
```

Runtime rejects with validation error equivalent to:

`variant <id> module_root escapes app directory`

## 7. Recommended Validation Commands

Variant/protocol governance tests:

```bash
uv run pytest tests/test_app_runtime.py tests/test_protocol_governance.py tests/test_unified_runtime.py
```

Focused variant tests:

```bash
uv run pytest tests/test_app_runtime.py -k "variant or platform_support"
```

## 8. First-Party Standardization Checklist

For first-party apps, require all items:

1. explicit `protocol_version`
2. explicit `required_capabilities` and `optional_capabilities`
3. `platform_support` when platform scope is intentionally limited
4. deterministic variant IDs and stable module roots
5. no `module_root` path traversal
6. CI coverage for variant match, unsupported platform, and bad module-root rejection
