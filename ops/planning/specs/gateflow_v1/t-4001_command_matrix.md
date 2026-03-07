# T-4001 Command Matrix Contract (GateFlow CLI v1)

## Scope Lock

This contract freezes the v1 command matrix for standalone GateFlow CLI:
1. `init`
2. `resources`
3. `validate`
4. `render`
5. `config`
6. `api` (shim lane)

## Top-Level Command Surface

1. `gateflow init`
- Purpose: scaffold `.gateflow/` directory and baseline ledgers.
- Required flags:
  - `--profile <minimal|discord|enterprise>`
  - `--root <path>` (optional, defaults to current directory)
- Determinism rule: same inputs produce byte-equivalent scaffold output.

2. `gateflow resources`
- Purpose: list and validate static templates/spec resources bundled with CLI.
- Required subcommands:
  - `list`
  - `show <resource_id>`
  - `check`
- Determinism rule: stable sort order by resource id.

3. `gateflow validate`
- Purpose: validate `.gateflow/` ledgers and policy contracts.
- Required subcommands:
  - `all`
  - `schema`
  - `links`
  - `closeout`
- Determinism rule: deterministic exit codes and stable error ordering.

4. `gateflow render`
- Purpose: render Gantt/board/status views from canonical ledgers.
- Required subcommands:
  - `gantt`
  - `board`
  - `summary`
- Determinism rule: same canonical input produces stable output digests.

5. `gateflow config`
- Purpose: read/write deterministic CLI workspace configuration.
- Required subcommands:
  - `get <key>`
  - `set <key> <value>`
  - `show`
- Determinism rule: `show` outputs canonical key order.

6. `gateflow api`
- Purpose: compatibility shim for existing planning-api workflows.
- Required subcommands:
  - `get <endpoint>`
  - `post <endpoint> --body <json>`
  - `patch <endpoint> --body <json>`
  - `delete <endpoint>`
- Determinism rule: shim request/response contract is schema-validated and logs explicit compatibility mode.

## Exit Code Contract

1. `0`: success.
2. `2`: validation failure (user-correctable input contract issue).
3. `3`: policy gate failure.
4. `4`: internal runtime error.

## Non-Goals (v1)

1. No plugin runtime.
2. No remote state backend.
3. No implicit migration side-effects during validation.
