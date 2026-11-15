# GitHub Security Setup

This document distinguishes security controls committed to the repository from hosted GitHub settings.

## Configured in the repository

- **Dependabot version updates:** `.github/dependabot.yml` checks Python dependencies and GitHub Actions weekly and opens update pull requests.
- **Automated tests and dependency audit:** `.github/workflows/tests.yml` runs tests, Ruff, strict mypy and `pip-audit` for the default dependencies; a separate job audits the combined optional `vocals`, `lyrics` and `desktop` dependency graph. The workflow has read-only repository permissions and disables persisted checkout credentials.
- **CodeQL:** `.github/workflows/codeql.yml` runs Python and JavaScript code scanning on pushes and pull requests to `master`, plus a weekly scheduled scan. The analysis job receives only the permissions needed to publish code-scanning results.
- **Desktop builds:** `.github/workflows/desktop.yml` downloads FFmpeg and appimagetool by pinned URL and checks their SHA-256 (the macOS FFmpeg is built from a pinned tag, checked by commit), self-tests every build, and only the release job has write access.
- **Third-party notices:** every desktop build ships `THIRD-PARTY-NOTICES.txt` with the license of each bundled library, plus FFmpeg's license.
- **Security policy:** `SECURITY.md` explains responsible vulnerability reporting and safe handling of user files.
- **Local-file exclusions:** `.gitignore` excludes local secrets, private keys, audio, and Light-O-Rama sequence files. Only the explicitly named fictional preview fixture is allowlisted.

## Hosted GitHub settings (checked 2026-11-15)

On: Dependabot alerts, malware alerts, security updates (grouped) and version updates; secret scanning with push protection; private vulnerability reporting; CodeQL (advanced setup) with Copilot Autofix suggestions; read-only default workflow token; Actions may not create or approve pull requests; actions must be pinned to a full commit SHA; approval required for first-time contributors' workflow runs.

**Not yet on: branch protection for `master`.** See [GITHUB_WORKFLOW.md](GITHUB_WORKFLOW.md#current-repository-settings-2026-11-15) for the exact ruleset settings. For a solo-maintained repository, do not require an approval count: GitHub does not let authors approve their own pull requests. Status checks and blocking force-pushes and deletion still provide value.

CodeQL is configured as a workflow in this repository; results appear under **Security → Code scanning**. Do not also enable CodeQL default setup unless you intentionally replace this workflow.

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
