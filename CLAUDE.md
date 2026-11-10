# Project instructions for AI coding agents

Read `docs/ARCHITECTURE.md` and `docs/PLAN.md` before making changes.

## Non-negotiable workflow

- Work on one phase at a time.
- One phase = one GitHub Issue = one branch = one PR.
- The issue is the contract: scope, non-goals, acceptance criteria, tests, and human gates must be explicit.
- Do not begin the next phase until the current phase's acceptance criteria pass, CI is green, the PR is merged, and the project owner explicitly approves moving forward.
- Do not bundle future-phase work, opportunistic refactors, or unrelated cleanup.
- Keep `docs/PLAN.md` progress log current with issue/PR links, branch, commit, tests/results, human verification, and remaining unknowns.
- Prefer a fresh session for each phase. Use the issue and progress log as the handoff; do not rely on chat history.
- Before coding, inspect the current repository state and active issue. Do not assume prior work satisfies the current acceptance criteria.
- Be precise about what was actually executed and verified. Never claim the owner opened or played a file in LOR.

## Risk-first implementation order

Follow the exact phase sequence in `docs/PLAN.md`. Prove native LOR sequence read/write/semantic round-trip first. Then prove a fixed-tempo pulse walking skeleton through the writer and have the owner open/play it in LOR before implementing intelligent audio analysis or choreography.

## Product constraints

- Required display input is a Light-O-Rama `.lorprev`. It is mandatory for both `analyze` and `generate`. Missing, unreadable, malformed, unsupported-version, or zero-prop previews must fail clearly.
- Output is a new native S6 `.loredit` file. Never modify or overwrite inputs.
- Never invent, assume, or reassign props, channels, controllers, or channel mappings. They must come from the preview or reviewed user prop map.
- Prop classification must use multiple preview signals (type, shape, grouping, position, channel count, color, and name hints); never rely on names alone.
- Initial supported channel types are single-color AC/DC and multi-color single-circuit. RGB/pixel props are outside v1 because the user's display does not use them. Explicitly report them as unsupported; never silently drop them.
- `props.yaml` is human-reviewed. Explicit physical overrides win over inferred preview interpretation, but may not invent channel identities.
- Timeline JSON is the single source of truth for choreography and is saved beside the generated sequence.
- Rules are data/configuration, not hardcoded display assumptions. Invalid Timelines fail with readable rule, prop/channel, and timestamp details.
- The writer serializes a validated Timeline only. It contains no choreography logic.

## Format and fixture discipline

- Test fixtures are the authority for LOR file schemas.
- Never guess a schema from memory or general XML knowledge. If fixtures do not answer a format question, stop and ask the project owner.
- Use sanitized fixture copies only. Never commit original display previews, original sequences, copyrighted audio, local paths, private metadata, or personal display details.
- Semantic round-trip comparisons compare meaning, not XML formatting.
- XML parsing uses `defusedxml`. YAML uses safe loading. Treat all input files and metadata as untrusted.

## Security and quality

- Python 3.12; use uv and commit the lockfile.
- Use Pydantic at stage boundaries, Typer for CLI, pytest, Ruff, and strict mypy.
- Pin dependencies and run a dependency audit in CI.
- Invoke FFmpeg with an argument list, never `shell=True`, with timeouts and bounded outputs.
- Validate extension and file content, enforce size/duration limits, and never overwrite input files.
- No secrets in code; `.env` is gitignored; use environment variables if credentials are ever needed.
- GitHub Actions use least-privilege permissions and third-party actions pinned to full commit SHAs.
- Never use `pull_request_target` to execute untrusted PR code.
- Synthetic audio only in tests; do not commit copyrighted audio.

## Phase completion report

At the end of each phase, report:
1. What changed.
2. Exact tests/commands run and their results.
3. CI status.
4. What remains unverified.
5. Human gate status and what the owner must do.
6. Issue and PR links.

Then stop and request approval. Do not start the next phase automatically.
