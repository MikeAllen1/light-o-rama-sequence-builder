# GitHub contribution and merge policy

This repository uses one phase-sized issue, branch, and pull request at a time. The project is intentionally small, so the controls should be meaningful without adding enterprise process overhead.

## Branches and pull requests

- `master` is the protected integration branch and should remain releasable.
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
4. Required CI is green on the latest PR commit: pytest, Ruff, strict mypy, dependency audit, and CodeQL.
5. All review conversations are resolved or explicitly dispositioned.
6. Documentation and `docs/PLAN.md` reflect the actual result.
7. The project owner explicitly approves the phase gate. CI passing or automated review does not count as owner approval.
8. The PR is merged with a merge commit (the repository's history keeps each PR's own commits). Use a descriptive commit subject. The topic branch is deleted automatically after merge.

Never merge with failing/pending checks, never use admin bypass to work around a failed gate, and never merge automatically just because checks pass. Do not force-push shared branches.

## Recommended repository rules for `master`

Configure these in GitHub Settings → Rules → Rulesets (or Branches → Branch protection rules):

- Target branch: `master`.
- Require a pull request before merging.
- Require the status checks `Tests, lint, types, and dependency audit` and `Windows compatibility tests`.
- Require `Analyze Python and JavaScript` (CodeQL) to complete successfully.
- Require all review conversations to be resolved.
- Block force pushes and branch deletion.
- Do not allow bypassing the rules for routine work.

For a solo-maintainer repository, a required independent approval can be counterproductive because GitHub does not allow authors to approve their own PRs. Keep the explicit owner approval gate in this document and the phase plan. If another trusted maintainer is added later, require at least one approval and dismiss stale approvals after new commits.

A merge queue is unnecessary for this low-volume, single-contributor project. Signed commits are a reasonable optional hardening measure if signing is configured reliably.

## Dependency updates

Dependabot PRs are not exempt from review. Check the upstream release notes, exact version/SHA, compatibility, and CI. Keep the existing weekly update cadence and small PR limit.

## Current repository settings (2026-11-15)

- Tests (pytest, Ruff, strict mypy, pip-audit, Windows tests) and CodeQL run on every pull request and push to `master`; CodeQL also runs weekly. The desktop builds (Windows, macOS, Linux) run on every pull request and attach to releases.
- Every third-party GitHub Action is pinned to a full commit SHA, and the repository requires it. The default workflow token is read-only; jobs that need more ask for it, and Actions may not create or approve pull requests. Checkout credentials are not persisted.
- Dependabot alerts, security updates and weekly version updates are on; secret scanning with push protection and private vulnerability reporting are on.
- Pull requests offer "Update branch", and head branches are deleted after merge.
- **`master` is not protected yet.** The `Protect` ruleset exists but is disabled, targets no branch, and requires one approving review, which a solo owner cannot give their own pull request. To turn it on: Settings → Rules → Rulesets → Protect → Target branches: *Include default branch*; Require a pull request: required approvals **0**; Require status checks: the three checks above; keep *Block force pushes* and *Restrict deletions*; Enforcement: **Active**.

## Phase gate rule

A phase is not complete until implementation, CI, owner verification (where required), merge, and explicit owner approval are all recorded. Stop after each phase and wait for approval before starting the next one.
