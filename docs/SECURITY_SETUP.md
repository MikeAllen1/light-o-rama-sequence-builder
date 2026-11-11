# GitHub Security Setup

This document separates security controls committed to the repository from GitHub settings that must be enabled in the repository UI.

## Configured in the repository

- **Dependabot version updates:** `.github/dependabot.yml` checks Python dependencies and GitHub Actions weekly and opens update pull requests.
- **Automated tests and dependency audit:** `.github/workflows/tests.yml` runs tests, Ruff, strict mypy, and a `pip-audit` scan of the locked production dependency export; the audit executable is installed from the locked `dev` group. Developer tools are pinned in the locked `dev` dependency group in `pyproject.toml` and `uv.lock`. The workflow has read-only repository permissions and disables persisted checkout credentials.
- **CodeQL:** `.github/workflows/codeql.yml` runs Python and GitHub Actions code scanning on pushes and pull requests to `master`, plus a weekly scheduled scan. The analysis job receives only the permissions needed to publish code-scanning results.
- **Security policy:** `SECURITY.md` explains responsible vulnerability reporting and safe handling of user files.
- **Local-file exclusions:** `.gitignore` excludes local secrets, private keys, audio, and Light-O-Rama sequence files. This is a guardrail, not a substitute for checking staged files.

## GitHub settings that still need an owner action

The GitHub connection used to update repository files does not expose repository security-settings write controls. A repository ruleset named `Protect` exists, but its enforcement is **disabled**. The `master` branch API also reports `protected: false` and no required status checks. Do not treat `master` as protected until the ruleset is enabled and its requirements are verified.

On the repository page, open **Settings → Security → Advanced Security** (GitHub may label the page slightly differently) and enable the following where offered:

1. **Dependency graph**
2. **Dependabot alerts**
3. **Dependabot security updates**
4. **Secret scanning**
5. **Push protection** for secret scanning
6. **Private vulnerability reporting**

CodeQL is configured as a workflow in this repository. After its first successful run, confirm that results appear under the repository's **Security → Code scanning** area. Do not also enable a second CodeQL workflow unless you intentionally replace this configuration.

## Protect the default branch

Open **Settings → Rules → Rulesets**, edit the existing `Protect` ruleset, and change enforcement from **Disabled** to **Active**. Confirm that it targets `master`. Recommended protections for this project:

- Require a pull request before changes merge to `master`.
- Require the **Tests / Tests, lint, types, and dependency audit** status check (confirm the exact displayed name after a successful run).
- Require the **CodeQL / Analyze Python** status check after it has appeared successfully.
- Block force pushes.
- Block branch deletion.
- Require conversation resolution if review comments are used.
- Require linear history if you want to prevent future merge commits; this cannot retroactively rewrite existing history.

For a solo-maintained repository, one approval is not useful unless another trusted reviewer is available. Do not require an approval count that would prevent you from merging your own work. Status checks and blocking force-pushes/deletion still provide value.

## Safe handling rules

- Keep original `.LOREDIT`, `.LMS`, and `.LAS` files, audio tracks, and unredacted display previews out of the public repository.
- Inspect `git status` and `git diff --cached` before committing. Ignored files can still be force-added.
- Scan decoded/expanded fixtures as well as their transport wrappers; secret scanners do not inspect opaque compressed or base64 payloads reliably.
- If a credential is ever committed, revoke or rotate it immediately. Deleting the file in a later commit does not make the exposed credential safe.
- Use only hand-authored or runtime-generated synthetic XML fixtures in the repository. Do not commit owner/customer LOR files or sanitized/derived copies. Keep any owner-supplied source material outside the repository.
- Do not put real credentials in issues, pull requests, logs, screenshots, or example configuration files.

## References

- [GitHub: Quickstart for securing your repository](https://docs.github.com/en/code-security/getting-started/quickstart-for-securing-your-repository)
- [GitHub: Managing security and analysis settings](https://docs.github.com/en/enterprise-cloud@latest/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-security-and-analysis-settings-for-your-repository)
- [GitHub: Security features](https://docs.github.com/en/code-security/getting-started/github-security-features)
