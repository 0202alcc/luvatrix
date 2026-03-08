# Objective Summary
- Establish and execute a deterministic closeout harness for canonical Planes IR parity between split-file compile input and monolith adapter input for milestone `UF-029`.

# Task Final States
- `T-3421`: In progress in this packet; harness specification, command profile, and evidence contracts defined.
- `T-3406`: Pending execution.
- `T-3407`: Pending execution.
- `T-3408`: Pending execution.
- `T-3409`: Pending execution.

# Evidence
- Harness specification: `docs/uf_029_closeout_harness.md`
- Planned deterministic artifacts:
  - `artifacts/uf029/parity_digest.json`
  - `artifacts/uf029/compiler_contract_summary.json`

# Determinism
- Gate conditions bind to deterministic commands and artifact paths.
- Required parity proof targets ordering, transform resolution, and hit-test semantics.

# Protocol Compatibility
- Harness assumes canonical runtime basis and enforces split/monolith compiler output equivalence in canonical IR contract tests.

# Modularity
- Compiler contract, monolith adapter behavior, and parity digest checks are decoupled so each can be validated independently.

# Residual Risks
- If parity selectors return no tests or parity artifacts are missing, closeout must be blocked as `NO-GO`.

# Training Demonstration Evidence
- Project ID: `camera_overlay_basics`
- Run command(s):
  - `UV_CACHE_DIR=.uv-cache PYTHONPATH=. uv run pytest tests -k "planes_split_compile or planes_parity_equivalence or planes_ir_contract" -q`
- Deterministic artifact references:
  - `artifacts/uf029/parity_digest.json`
  - `artifacts/uf029/compiler_contract_summary.json`
- Demo scope verdicts:
  - split vs monolith compile parity to canonical IR: `pending`
  - overlay parity semantics: `pending`
