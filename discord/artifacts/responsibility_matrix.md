# RACI: Responsibility Matrix (Current Single-Human + AI-Assisted Phase)

## Role Definitions
1. `CEO`: strategy owner, final decision authority, release/governance approvals.
2. `Leads`: technical reviewers and domain owners (future-state role).
3. `Contributors`: implementation and testing execution.
4. `AI Agent`: drafting, analysis, implementation support under policy constraints.
5. `Quality Function`: standards and cross-domain gate owner (may be CEO initially).

## RACI by Workstream

1. Milestone planning and sequencing
- Responsible: CEO
- Accountable: CEO
- Consulted: AI Agent
- Informed: Contributors

2. Task breakdown and board setup
- Responsible: CEO, AI Agent
- Accountable: CEO
- Consulted: Contributors
- Informed: All

3. Runtime/protocol implementation
- Responsible: Contributors, AI Agent
- Accountable: CEO
- Consulted: Leads
- Informed: All

4. Test strategy and evidence
- Responsible: Contributors, AI Agent
- Accountable: Quality Function
- Consulted: CEO
- Informed: All

5. CI and release gating
- Responsible: Quality Function
- Accountable: CEO
- Consulted: Leads
- Informed: All

6. RFC/ADR documentation
- Responsible: AI Agent, Contributors
- Accountable: CEO
- Consulted: Leads
- Informed: All

7. Risk register and incidents
- Responsible: CEO, AI Agent
- Accountable: CEO
- Consulted: Quality Function
- Informed: All

8. Executive digest publication
- Responsible: AI Agent
- Accountable: CEO
- Consulted: Leads
- Informed: All

## Transition Notes
1. As human team grows, split `Quality Function` into dedicated owners.
2. Shift domain accountability from CEO to engineering leads incrementally.
