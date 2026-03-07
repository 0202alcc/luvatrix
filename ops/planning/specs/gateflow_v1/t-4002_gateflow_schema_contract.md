# T-4002 `.gateflow/` Canonical Schema and Determinism Contract

## Canonical Directory Contract

Required v1 scaffold:
1. `.gateflow/config.json`
2. `.gateflow/milestones.json`
3. `.gateflow/tasks.json`
4. `.gateflow/boards.json`
5. `.gateflow/backlog.json`
6. `.gateflow/closeout/`

## Canonical JSON Rules

1. UTF-8 text, LF newlines only.
2. Two-space indentation.
3. Keys sorted lexicographically at every object depth.
4. Arrays preserve semantic ordering where order is meaning-bearing; otherwise sorted by primary id.
5. No trailing commas.
6. Exactly one final newline.

## Core Ledger IDs

1. Milestone id pattern: `^[A-Z]{1,3}-[0-9]{3}$`
2. Task id pattern: `^T-[0-9]{4}$`
3. Board id pattern: `^(milestone|team):[A-Z0-9-]+$`

## Minimal JSON Shape (Normative)

```json
{
  "version": "gateflow_v1",
  "updated_at": "YYYY-MM-DD",
  "items": []
}
```

## Determinism Guarantees

1. Serializer output is byte-stable for semantically equivalent input.
2. Validation errors are emitted in deterministic `(file, line, key)` order.
3. Render/summary commands consume only canonicalized documents.

## Compatibility Rules

1. Optional fields must not alter required-field semantics.
2. Unknown fields in strict mode fail with exit code `2`.
3. Unknown fields in permissive mode are surfaced as warnings and preserved.

## Canonical Object Key Order (Reference)

1. Milestone object keys:
  - `id`, `emoji`, `name`, `descriptions`, `start_week`, `end_week`, `status`, `task_ids`, `success_criteria`, `closeout_criteria`, `ci_required_checks`, `lifecycle_events`
2. Task object keys:
  - `id`, `title`, `task_type`, `milestone_id`, `status`, `depends_on`, `board_refs`, `notes`, `actuals`, `done_gate`

## Canonicalization Rule

All ledgers MUST pass a normalize-then-serialize pipeline before write, and all commands that mutate ledgers MUST write canonicalized output.
