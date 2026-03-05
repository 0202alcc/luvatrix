# F-034 PR Recovery Pass

Date: 2026-03-05

Scope: PR artifacts only. No implementation code changes.

## Branch PR Artifact Results

| Branch | Base | PR Artifact | PR URL | Tip SHA | Merge-Base SHA | Compare URL | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `codex/t-t-2920-closeout-harness` | `codex/m-f-034-debug-menu-foundation` | Created | https://github.com/0202alcc/luvatrix/pull/17 | `4a147d24c7178cb4e9b9eaef1dc2fd3486df14b0` | `633942ae70a0197af56ebbc3711cc89a422a160d` | https://github.com/0202alcc/luvatrix/compare/codex/m-f-034-debug-menu-foundation...codex/t-t-2920-closeout-harness | Retroactive task PR artifact successfully created. |
| `codex/t-t-2901-menu-crash-hardening` | `codex/m-f-034-debug-menu-foundation` | Created | https://github.com/0202alcc/luvatrix/pull/18 | `62c491095b38313fa4a3778f6ea5e522beeb1111` | `62a56a2425a15bce43785f0dd06e3691f0b795ea` | https://github.com/0202alcc/luvatrix/compare/codex/m-f-034-debug-menu-foundation...codex/t-t-2901-menu-crash-hardening | Retroactive task PR artifact successfully created. |
| `codex/t-t-2902-capability-registry` | `codex/m-f-034-debug-menu-foundation` | Created | https://github.com/0202alcc/luvatrix/pull/19 | `dd79c29ee73b10f0fefa50581ceb0f2df650dd5d` | `cd06999656769b36bfc52918ffedf12da8b159f2` | https://github.com/0202alcc/luvatrix/compare/codex/m-f-034-debug-menu-foundation...codex/t-t-2902-capability-registry | Retroactive task PR artifact successfully created. |
| `codex/t-t-2903-menu-adapter-spec` | `codex/m-f-034-debug-menu-foundation` | Created | https://github.com/0202alcc/luvatrix/pull/20 | `5b82953f0e6eef82042274b084dfcf882eaa0c0a` | `6258eb2fdc69078c088996f039c6bf57985f47fa` | https://github.com/0202alcc/luvatrix/compare/codex/m-f-034-debug-menu-foundation...codex/t-t-2903-menu-adapter-spec | Retroactive task PR artifact successfully created. |
| `codex/m-f-034-debug-menu-foundation` | `main` | Not creatable | N/A | `66fee5f54b52e8c8de3cacdc5d80780543954aaf` | `66fee5f54b52e8c8de3cacdc5d80780543954aaf` | https://github.com/0202alcc/luvatrix/compare/main...codex/m-f-034-debug-menu-foundation | `gh pr create` failed with: `No commits between main and codex/m-f-034-debug-menu-foundation`; milestone already fully merged to `main`, so a retroactive PR cannot be created. |

## Required `gh pr list` Checks

`gh pr list --state all --head codex/t-t-2920-closeout-harness`  
Result: PR #17 (OPEN) against `codex/m-f-034-debug-menu-foundation`.

`gh pr list --state all --head codex/t-t-2901-menu-crash-hardening`  
Result: PR #18 (OPEN) against `codex/m-f-034-debug-menu-foundation`.

`gh pr list --state all --head codex/t-t-2902-capability-registry`  
Result: PR #19 (OPEN) against `codex/m-f-034-debug-menu-foundation`.

`gh pr list --state all --head codex/t-t-2903-menu-adapter-spec`  
Result: PR #20 (OPEN) against `codex/m-f-034-debug-menu-foundation`.

`gh pr list --state all --head codex/m-f-034-debug-menu-foundation`  
Result: no PRs returned.

## Final Status

retroactively not creatable; evidence attached
