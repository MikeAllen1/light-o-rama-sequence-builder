# GitHub Security Setup

This document distinguishes security controls committed to the repository from hosted GitHub settings.

## Configured in the repository

- **Dependabot version updates:** `.github/dependabot.yml` checks Python dependencies and GitHub Actions weekly and opens update pull requests.
- **Automated tests and dependency audit:** `.github/workflows/tests.yml` runs tests, Ruff, and `pip-audit` for the default dependencies; a separate job audits the combined optional `vocals` and `lyrics` dependency graph. The workflow has read-only repository permissions and disables persisted checkout credentials.
- **CodeQL:** `.github/workflows/codeql.yml` runs Python and JavaScript code scanning on pushes and pull requests to `master`, plus a weekly scheduled scan. The analysis job receives only the permissions needed to publish code-scanning results.
- **Security policy:** `SECURITY.md` explains responsible vulnerability reporting and safe handling of user files.
- **Local-file exclusions:** `.gitignore` excludes local secrets, private keys, audio, and Light-O-Rama sequence files. Only the explicitly named fictional preview fixture is allowlisted.

## Hosted GitHub settings — owner-reported status

The repository owner reported on 2026-11-11 that the requested GitHub security-settings work had been completed. The connected GitHub integration cannot independently inspect all repository security feature toggles, so this is recorded as owner-reported rather than independently verified.

**Branch protection is a separate verification item.** The connected integration verified that `master` reports `protected: false` and that the `Protect` ruleset exists with enforcement disabled. Enable it in GitHub Settings → Rules → Rulesets and verify that it targets `master`. Recommended protections:

- Require a pull request before changes merge to `master`.
- Require the **Tests / test** status check.
- Require the **CodeQL / Analyze Python and JavaScript** status check after it has appeared successfully.
- Block force pushes.
- Block branch deletion.
- Require conversation resolution if review comments are used.

For a solo-maintained repository, one approval is not useful unless another trusted reviewer is available. Do not require an approval count that would prevent you from merging your own work. Status checks and blocking force-pushes/deletion still provide value.

CodeQL is configured as a workflow in this repository. Confirm that results appear under the repository's **Security → Code scanning** area. Do not also enable a second CodeQL workflow unless you intentionally replace this configuration.

## Safe handling rules

- Keep original `.LOREDIT`, `.LMS`, and `.LAS` files, audio tracks, and unredacted display previews out of the public repository.
- Inspect `git status` and `git diff --cached` before committing. Ignored files can still be force-added.
- If a credential is ever committed, revoke or rotate it immediately. Deleting the file in a later commit does not make the exposed credential safe.
- Use synthetic XML fixtures for tests. Do not add owner/customer names, GUIDs, machine paths, media references, or other private details.
- Do not put real credentials in issues, pull requests, logs, screenshots, or example configuration files.

## References

- [GitHub: Quickstart for securing your repository](https://docs.github.com/en/code-security/getting-started/quickstart-for-securing-your-repository)
- [GitHub: Managing security and analysis settings](https://docs.github.com/en/enterprise-cloud@latest/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-security-and-analysis-settings-for-your-repository)
- [GitHub: Security features](https://docs.github.com/en/code-security/getting-started/github-security-features)
