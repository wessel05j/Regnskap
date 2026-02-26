# Security and Architecture Hardening Review

Date: 2026-02-26
Branch: `release-prep/source-available`
Scope: pre-public-release review, excluding core accounting logic changes

## Checklist Results

1. Hardcoded secrets scan: **Pass (with notes)**
- No committed API keys/private keys/tokens were detected in tracked source files.
- One test-only credential literal is used in UI tests (`TestPassord123!`), which is acceptable for isolated test fixtures.

2. Local file path scan: **Pass**
- No hardcoded absolute local paths (Windows/Linux/macOS) were detected in source/docs.

3. Test/demo data realism check: **Pass (hardened)**
- Demo/default sample values were anonymized to generic names.
- Brand-specific sample references were removed from seed/tests/UI placeholders.

4. Logging sensitivity review: **Pass (improved)**
- Legacy import logging no longer writes source file path.
- Legacy migration logging no longer dumps the full result object.
- Current logs still include operational metadata (actor, voucher IDs), but no credentials.

5. Backup ignore policy: **Pass (hardened)**
- Backup outputs under `data/backups/**` are ignored, including nested zip/sqlite artifacts.

6. Runtime artifact ignore policy: **Pass (hardened)**
- `.gitignore` now covers additional runtime artifacts (`.coverage.*`, `*.pid`, `*.tmp`, `*.temp`, `data/app.log`, nested data artifacts).

7. README production warnings: **Pass (improved)**
- Explicit `Production Warning` section added.
- Clear statement that system is not production ready.

## Architecture Risk Summary

### High

- Session cookie is configured with `secure=False` in current app code.
  - Impact: if deployed beyond localhost without TLS handling, session theft risk increases.
  - Recommendation: gate `secure` by environment and enforce HTTPS in production profile.

### Medium

- CSRF model appears coupled to session token usage in forms/templates.
  - Impact: weaker separation of authentication and CSRF protection.
  - Recommendation: introduce dedicated per-request/per-session CSRF token strategy.

- No visible login rate limiting or account lockout policy.
  - Impact: brute-force risk on exposed deployments.
  - Recommendation: add rate limiting + exponential backoff + audit alerts.

- Backup archives are not encrypted by default.
  - Impact: data exposure if backup files are copied/leaked.
  - Recommendation: add optional encrypted backup mode and key management guidance.

### Low

- Startup/event and template APIs emit framework deprecation warnings.
  - Impact: maintenance risk over time.
  - Recommendation: migrate to FastAPI lifespan handlers and updated template signature.

## Changes Applied in This Review

- Hardened `.gitignore` for runtime and backup artifacts.
- Sanitized legacy import/migration logging to reduce leakage of path/detail data.
- Anonymized default and demo/test sample identity data.
- Added stronger production-use warning in README.

## Out of Scope / Not Changed

- Core accounting engine behavior (`ledger`, VAT calculation rules, posting logic) was not modified.
