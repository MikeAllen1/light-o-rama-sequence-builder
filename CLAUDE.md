# Instructions for AI coding sessions

This repository is built in gated phases. Read these before doing anything:

1. `docs/PLAN.md` — authoritative phase status, acceptance criteria, open decisions, and handoff log.
2. The GitHub Issue for the active phase — the contract for scope and acceptance.
3. `docs/ARCHITECTURE.md` — stage boundaries and data contracts.
4. `docs/GITHUB_WORKFLOW.md` — branch, PR, and merge rules.

If these documents disagree, `docs/PLAN.md` wins. If PLAN.md is ambiguous or stale, stop and ask.

## Hard rules

- Work only on the active phase. Do not start the next phase until the owner explicitly approves it in writing.
- If you find a problem in an earlier phase, stop and report it. Do not fix it as a side effect.
- Before coding, list the files you plan to create or change and wait for approval.
- One phase = one issue = one branch (`phase-N/short-description`) = one PR to `master`. Never push to `master`.
- Fixtures in `tests/fixtures/` are the format authority. Never guess LOR file schemas from memory. If a fixture does not answer a format question, ask.
- Never invent, assume, or reassign props, channels, or controller identities. They come from the preview or a reviewed prop map only.
- Nothing about any specific display may be hardcoded. This tool is for any Light-O-Rama display.
- Never modify or overwrite input files. Outputs are always new paths.
- Never commit real show files, previews, audio, local paths, or secrets. Commit only sanitized fixtures, as base64 transport copies.
- Never claim the owner opened, played, or approved anything. Human gates are recorded only from the owner's own words.
- Not-yet-applicable tests are marked pending, never reported as passing.

## Checks (must pass before a PR is marked ready)

```
uv sync --locked
uv run --no-sync --with pytest==9.2.0 python -m pytest
uv run --no-sync --with ruff==0.17.4 ruff check .
uv run --no-sync --with mypy==1.18.2 --with types-defusedxml==0.7.0.20260504 --with pytest==9.2.0 mypy --strict src tests
```

## End of every session

Update the active phase entry in `docs/PLAN.md` (what was built, decisions, exact test results, unverified items, human-gate status), then summarize: what is verified by tests, what needs the owner to test in Light-O-Rama, and open questions.
