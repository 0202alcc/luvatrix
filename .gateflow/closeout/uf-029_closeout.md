# Objective Summary
- Completed canonical Planes IR compiler parity closeout for `UF-029` by implementing split-file compile, monolith adapter compile, parity contract tests, and deterministic digest artifacts tied to the training demo project.

# Task Final States
- `T-3421`: `Done` via controlled close; closeout harness spec and command profile authored.
- `T-3406`: `Done` via controlled close; canonical IR mapping contract and blockers documented.
- `T-3407`: `Done` via controlled close; split-file canonical compiler entrypoint added and validated.
- `T-3408`: `Done` via controlled close; monolith compatibility adapter to canonical IR added and validated.
- `T-3409`: `Done` via controlled close; parity digest suite and required scenario checks implemented.

# Evidence
- Contract and harness docs:
  - `docs/uf_029_closeout_harness.md`
  - `docs/planes_canonical_ir_contract.md`
- Deterministic artifacts:
  - `artifacts/uf029/parity_digest.json`
  - `artifacts/uf029/compiler_contract_summary.json`
- Command evidence:
  - `UV_CACHE_DIR=.uv-cache PYTHONPATH=. uv run pytest tests -k "planes_split_compile or planes_parity_equivalence or planes_ir_contract" -q` -> `8 passed`
  - `UV_CACHE_DIR=.uv-cache PYTHONPATH=. uv run --with pytest pytest tests -k "planes_v2 and (debug_screenshot or debug_recording or debug_overlay or debug_replay or debug_frame_step or debug_bundle)" -q` -> `2 passed`
  - `UV_CACHE_DIR=.uv-cache PYTHONPATH=. uv run python ops/ci/uf029_generate_parity_digest.py` -> `all_pass=true`
  - `UV_TOOL_DIR=.uv-tools UV_CACHE_DIR=.uv-cache uvx --from gateflow==0.1.0a3 gateflow --root /Users/aleccandidato/Projects/luvatrix validate links` -> `PASS`
  - `UV_TOOL_DIR=.uv-tools UV_CACHE_DIR=.uv-cache uvx --from gateflow==0.1.0a3 gateflow --root /Users/aleccandidato/Projects/luvatrix validate closeout` -> `PASS`
  - `UV_TOOL_DIR=.uv-tools UV_CACHE_DIR=.uv-cache uvx --from gateflow==0.1.0a3 gateflow --root /Users/aleccandidato/Projects/luvatrix validate all` -> `PASS`

# Determinism
- Canonical parity digest output is deterministic for fixed inputs and emitted to versioned artifact paths under `artifacts/uf029/`.
- Digest scenarios explicitly gate ordering/overlay semantics and split-vs-monolith canonical equivalence.

# Protocol Compatibility
- Compiler paths now converge to canonical `planes-v2` IR contract with ordering contract version `plane-z-local-z-overlay-v1`.
- Monolith adapter path preserves app-facing semantics while removing direct non-canonical runtime dependency.

# Modularity
- Mapping contract documentation, compiler adapters, and parity digest harness are independently testable and composable.
- Digest generation lives in `ops/ci/uf029_generate_parity_digest.py`, separate from compile primitives in `luvatrix_ui/planes_protocol.py`.

# Residual Risks
- macOS runtime smoke command for `r040` reports action preflight pass with runtime runs skipped when host prerequisites are unavailable; this does not invalidate UF-029 compiler parity but should be monitored for downstream runtime milestones.
- Any future canonical IR schema changes must keep digest contract fields stable or intentionally version the parity harness.

# Training Demonstration Evidence
- Project ID: `camera_overlay_basics`
- Run command(s):
  - `UV_CACHE_DIR=.uv-cache PYTHONPATH=. uv run pytest tests -k "planes_split_compile or planes_parity_equivalence or planes_ir_contract" -q`
  - `UV_CACHE_DIR=.uv-cache PYTHONPATH=. uv run python ops/ci/uf029_generate_parity_digest.py`
- Deterministic artifact references:
  - `artifacts/uf029/parity_digest.json`
  - `artifacts/uf029/compiler_contract_summary.json`
- Demo scope verdicts:
  - split vs monolith compile parity to canonical IR: `pass` (matching digest values)
  - overlay parity semantics: `pass` (camera overlay ordering contract satisfied)
