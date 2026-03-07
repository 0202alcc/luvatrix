# T-4003 Profile Contract and Scaffold Boundaries

## Profile Set (Frozen for v1)

1. `minimal`
2. `discord`
3. `enterprise`

## Base vs Overlay Model

1. `minimal` is the base profile and defines required scaffold contracts.
2. `discord` overlays notification and board-channel metadata only.
3. `enterprise` overlays governance/audit defaults and stricter policy presets.

## `minimal` Profile

Required:
1. Canonical `.gateflow/*.json` ledgers.
2. Local validation and render command support.
3. No chat/distribution integrations enabled by default.

## `discord` Profile

Adds:
1. Board metadata for channel mapping.
2. Message formatting templates.
3. Validation rules for channel-id presence on mapped boards.

Boundaries:
1. Must not modify milestone/task schema core fields.
2. Must not bypass policy gates.

## `enterprise` Profile

Adds:
1. Strict policy defaults (`protected_branch`, done-gate completeness).
2. Audit evidence path requirements.
3. Optional warning-as-error mode for closeout harness checks.

Boundaries:
1. No profile may redefine core id schemas.
2. No profile may change deterministic formatting rules.

## Scaffold Behavior

1. `gateflow init --profile minimal` creates only base files.
2. `gateflow init --profile discord` creates base + discord overlay config.
3. `gateflow init --profile enterprise` creates base + enterprise overlay config.
4. Re-running `init` is idempotent and deterministic under same profile.

## Profile Selection Contract

1. Profile is immutable for a scaffold root unless explicit migration command is used.
2. `discord` and `enterprise` overlays may be combined only through additive keys under profile namespace.
3. `minimal` remains required compatibility baseline for all future profiles.

## Migration Boundary

1. Upgrading profile level must preserve existing canonical ledgers without lossy transforms.
2. Downgrading from `enterprise` to `minimal` is allowed only when enterprise-only keys are removed or mapped deterministically.
