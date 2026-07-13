# Performance Evidence

This directory keeps measured before-and-after evidence for Luvatrix runtime and tooling changes. Records are append-only: later measurements should add a new document and raw data file rather than rewriting prior release results.

Each record should include:

- Hardware, operating conditions, refresh rate, and relevant runtime settings.
- Raw per-trial values in `data/`.
- The sampling or instrumentation method and its known measurement floor.
- Recomputed medians or percentiles and percentage changes.
- A test that verifies the published summary against raw measurements.
- Limitations that prevent treating a single-device result as a universal claim.

## Records

| Release | Area | Evidence | Result |
| --- | --- | --- | --- |
| 0.2.3 | Android cold launch and Activity recreation | [Android Activity rebind](android_activity_rebind_0_2_3.md) | 19.08% faster median cold launch; 81.46% faster median Activity recreation |
