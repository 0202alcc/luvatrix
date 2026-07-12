# Security Policy

## Pull Request Security Gate

Pull requests targeting `dev`, `staging`, or `main` run the required `security-review` workflow. It currently includes:

- `pip-audit` for known vulnerabilities in locked Python dependencies;
- Bandit for high-confidence, high-severity Python findings;
- Gitleaks for committed secrets;
- zizmor for GitHub Actions workflow risks; and
- validation of the provider-neutral agent-review contract.

The final `security-review` job succeeds only when every layer succeeds. Repository branch rulesets should require that stable job name rather than individual scanner job names, allowing scanners to evolve without repeatedly changing protection rules.

The agent-review framework does not call a model and does not receive credentials. Its trust boundary, prompt, and structured output schema live under `.github/security/` so a future provider can be integrated without redefining the review contract.

## Handling Findings

Do not suppress a scanner finding without documenting why it is a false positive or accepted risk. Keep suppressions narrow, identify the finding or rule explicitly, and include an owner or follow-up when remediation is deferred.

Do not include live secrets in issues, pull-request comments, logs, fixtures, or reproduction steps. Rotate any credential that may have entered Git history even if the committed value is later removed.
