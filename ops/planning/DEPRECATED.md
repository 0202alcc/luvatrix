# Deprecated: ops/planning (Legacy Archive)

Status: Frozen legacy archive as of 2026-03-08T21:06:27Z.

`ops/planning/*` is no longer the active planning ledger.
Use `.gateflow/*` and standalone GateFlow CLI commands for all active planning operations:

- `uvx --from gateflow==0.1.0a3 gateflow --root /Users/aleccandidato/Projects/luvatrix ...`

Archive provenance:
- Freeze mode: in-place (non-destructive)
- Freeze commit SHA: b9b7501b1ade134a560045fb893ab8e5a13919a6
- Archive manifest: `.gateflow/legacy_ops_planning_manifest.json`

Policy:
- New planning writes must not target `ops/planning/*`.
- Only explicitly approved archival/deprecation updates are allowed during bounded archive windows.
