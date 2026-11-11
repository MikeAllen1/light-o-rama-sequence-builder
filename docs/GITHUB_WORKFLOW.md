# GitHub contribution and merge policy

This repository uses one phase-sized issue, branch, and pull request at a time. The project is intentionally small, so the controls should be meaningful without adding enterprise process overhead.

## Branches and pull requests

- `master` is intended to be the integration branch and should remain releasable. As of 2026-11-11, GitHub reports `protected: false`; the existing `Protect` ruleset is disabled. Do not assume the policy is enforced until the owner activates it.
- Never push implementation commits directly to `master`.
- Phase branches use `phase-N/short-description`; maintenance branches use a descriptive topic name; Dependabot branches are managed by Dependabot.
- Open work-in-progress PRs as drafts. Mark ready for review only when the acceptance criteria, implementation, tests, and PR description are complete.
- Keep each PR focused on one issue and one logical change. Avoid unrelated refactors and future-phase work.
- Include a concise summary, linked issue, scope/non-goals, implementation notes, test evidence, risk/compatibility notes, and human-verification status.
- Use GitHub's `Closes #N` syntax only when the PR actually completes that issue.

## Review and merge requirements

Before merge, verify all of the following:

1. The PR targets `master` and is based on the current branch head.
2. The full diff has been reviewed for correctness, scope, secrets, private paths/metadata, copyrighted media, and generated noise.
3. The acceptance criteria are met; tests cover normal behavior and failure cases.
4. Required CI is green on the latest PR commit: the `Tests, lint, types, and dependency audit` job and `CodeQL / Analyze Python and Actions` job.
5. All review conversations are resolved or explicitly dispositioned.
6. Documentation and `docs/PLAN.md` reflect the actual result.
7. The project owner explicitly approves the phase gate. CI passing or automated review does not count as owner approval.
8. The PR is merged with **Squash and merge**. Use a descriptive commit subject. Delete the topic branch after merge.

Never merge with failing/pending checks, never use admin bypass to work around a failed gate, and never merge automatically just because checks pass. Do not force-push shared branches.

## Recommended repository rules for `master`

Configure these in GitHub Settings → Rules → Rulesets (or Branches → Branch protection rules):

- Target branch: `master`.
- Require a pull request before merging.
- Require the Tests workflow check: `Tests, lint, types, and dependency audit` (the job check name, not a non-existent `Tests / test`).
- Require CodeQL analysis to complete successfully.
- Require branches to be up to date before merging.
- Require all review conversations to be resolved.
- Require linear history.
- Block force pushes and branch deletion.
- Do not allow bypassing the rules for routine work.

For a solo-maintainer repository, a required independent approval can be counterproductive because GitHub does not allow authors to approve their own PRs. Keep the explicit owner approval gate in this document and the phase plan. If another trusted maintainer is added later, require at least one approval and dismiss stale approvals after new commits.

A merge queue is unnecessary for this low-volume, single-contributor project. Signed commits are a reasonable optional hardening measure if signing is configured reliably.

## Dependency updates

Dependabot PRs are not exempt from review. Check the upstream release notes, exact version/SHA, compatibility, and CI. Keep the existing weekly update cadence and small PR limit.

## Current repository audit (2026-11-10)

- Tests workflow runs on pushes to `master` and pull requests targeting `master`; it executes pytest, Ruff, strict mypy, and a production-dependency `pip-audit` scan. Developer tools are pinned in `requirements-dev.txt` but are not yet included in `uv.lock`.
- CodeQL runs on pushes/PRs to `master` and weekly.
- Third-party GitHub Actions are pinned to full commit SHAs; checkout credentials are not persisted.
- Dependabot is enabled for Python dependencies and GitHub Actions.
- GitHub API verification on 2026-11-11 found an existing `Protect` ruleset with `enforcement: disabled`; `master` reports `protected: false` and no required status checks. Branch protection is **not active**.
- Repository history shows the written process was not consistently followed: implementation commits were pushed directly to `master`, merge commits were used despite the linear-history policy, and stale branches remained. These are historical facts, not claims that this PR caused them. The policy below applies prospectively; enforcing it requires GitHub settings.
- The initial Phase 4 baseline had already reached `master` outside a PR, contrary to the documented phase-sized PR rule. This follow-up is being kept on PR #12.

## Phase gate rule

A phase is not complete until implementation, CI, owner verification (where required), merge, and explicit owner approval are all recorded. Stop after each phase and wait for approval before starting the next one.
