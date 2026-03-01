# RISK-REGISTER: Baseline Risks and Mitigations

## Severity Scale
1. Impact: Low | Medium | High
2. Likelihood: Low | Medium | High
3. Status: Open | Mitigating | Accepted | Closed

## Active Risks

1. `R-001` Single-human bottleneck slows milestone throughput
- Impact: High
- Likelihood: High
- Status: Open
- Mitigation: Use automation + AI assistance; prioritize milestone slicing and cadence discipline.
- Owner: CEO
- Review date: Weekly

2. `R-002` Context loss during project switching
- Impact: High
- Likelihood: Medium
- Status: Open
- Mitigation: Maintain weekly executive digest and strict ADR/meeting records.
- Owner: CEO
- Review date: Weekly

3. `R-003` Experimental Vulkan instability delays hardening
- Impact: High
- Likelihood: Medium
- Status: Open
- Mitigation: Add targeted regression suite and fallback parity checks.
- Owner: Runtime/Rendering
- Review date: Weekly

4. `R-004` Flaky tests undermine CI trust
- Impact: Medium
- Likelihood: Medium
- Status: Open
- Mitigation: Apply flaky governance with quarantine/fix SLA and reporting.
- Owner: Quality Function
- Review date: Weekly

5. `R-005` Bot misconfiguration causes governance gaps
- Impact: Medium
- Likelihood: Medium
- Status: Mitigating
- Mitigation: Run automated rollout checker and monthly access review.
- Owner: CEO
- Review date: Monthly

6. `R-006` Incomplete safety/quality evidence before merge
- Impact: High
- Likelihood: Medium
- Status: Open
- Mitigation: Enforce test lifecycle and merge gate checklist.
- Owner: Quality Function
- Review date: Weekly

## Risk Entry Template
1. Risk statement:
2. Trigger condition:
3. Early warning signals:
4. Mitigation plan:
5. Owner:
6. Next review date:
