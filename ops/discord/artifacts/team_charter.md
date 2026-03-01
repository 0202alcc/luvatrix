# CHARTER: Luvatrix Engineering Team Charter (Non-Private)

## 1) Mission
Build a robust custom app protocol and rendering runtime that enables safe, high-performance, cross-platform interactive applications, starting with a hardened macOS-first path.

## 2) Success Criteria
1. Core runtime remains stable under deterministic test suite.
2. macOS rendering path reaches production-ready reliability.
3. Protocol governance remains explicit, auditable, and backward-compatible where intended.
4. Security and safety controls (capabilities, sensor controls, energy safety, audit) remain enforced by default.
5. New contributors (human or AI) can onboard and deliver a scoped contribution quickly.

## 3) Scope Boundaries
In scope:
1. App protocol runtime and lifecycle.
2. Matrix/rendering pipeline.
3. HDI and sensor management.
4. Audit, energy safety, protocol governance.
5. Developer tooling and collaboration operating model.

Out of scope for current phase:
1. Full web renderer completion.
2. Mobile backend rollout.
3. Full out-of-process sandbox redesign.

## 4) Stakeholders
1. CEO (product/strategy owner).
2. Engineering leads (technical direction and quality governance).
3. Contributors (human and AI).
4. Future partners/users (indirect, via product outcomes).

## 5) Operating Principles
1. Put important decisions in writing (RFC + ADR for major changes).
2. Test-first rigor before implementation.
3. Small, reversible increments.
4. Evidence over opinion in reviews.
5. Clear ownership and accountability.

## 6) Decision Policy
1. Major pivots require RFC + ADR + implementation evidence.
2. Minor tactical changes may be logged in iteration notes if non-architectural.
3. Risk and safety concerns can block merge regardless of schedule pressure.

## 7) Quality Bar
A feature is not done unless it includes:
1. success criteria,
2. safety tests,
3. implementation tests,
4. edge-case tests,
5. performance/regression checks,
6. passing CI evidence.
