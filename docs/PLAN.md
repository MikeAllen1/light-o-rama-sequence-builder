# Implementation Plan

**Status:** Phase 0 — scaffold audit / completion  
**Current phase:** 0  
**Next phase:** 1 — LOR format

## Product objective and fixed requirements

Build a display-independent CLI that accepts audio plus a required Light-O-Rama .lorprev preview and produces a new native S6 .loredit sequence. The user workflow remains analyze → review/edit props.yaml → generate. Timeline JSON is the single source of truth and is saved beside the output.

- Preview is mandatory for analyze and generate. Missing, unreadable, malformed, unsupported-version, or zero-prop previews fail clearly.
- Props, controllers, and channels must originate from the preview or reviewed user prop map. Never invent or silently reassign them.
- Classification combines prop type, shape, grouping, position, channel count, color, and name hints; never names alone.
- Initial channel support: single-color AC/DC and multi-color single-circuit.
- RGB/pixel is outside v1 because the user's display does not use pixels. Detect and report unsupported pixel props; never silently drop or fake support.
- Physical overrides in props.yaml win over inferred preview interpretation but cannot create channel identities.
- Rules are configuration; invalid Timelines fail with readable rule, prop/channel, and timestamp details.
- Never modify/overwrite inputs. Output is a new file.
- V1 excludes GUI, controller upload, live playback, and editing existing sequences.
- Python 3.12, uv + committed lockfile, Pydantic, Typer, pytest, Ruff, strict mypy.
- XML via defusedxml; YAML safe_load; FFmpeg argument list, never shell=True; input size/type/duration limits.
- No secrets in code; .env gitignored; pin dependencies and run pip-audit.
- CI uses least privilege and third-party Actions pinned to full commit SHAs. Never use pull_request_target to execute untrusted PR code.
- Synthetic audio tests only; never commit copyrighted audio.

## Mandatory engineering workflow

- One phase = one GitHub Issue = one branch = one PR.
- The issue is the contract: scope, non-goals, acceptance criteria, tests, and human gates.
- Work only on the active phase. No future-phase work, unrelated refactoring, or scope creep.
- A phase is complete only when acceptance criteria pass, CI is green, the PR is merged, required human verification is recorded, and the owner approves moving forward.
- Do not start the next phase before explicit owner approval.
- Keep this file as the persistent progress/handoff log: issue/PR links, branch, commits, exact tests/results, human-gate status, and remaining unknowns.
- Prefer a fresh session per phase. The next session must be able to resume from this file and the GitHub issue without relying on chat history.
- Never claim the owner opened or played a file in LOR. Automated tests cannot satisfy human gates.

## Phase order

### Phase 0 — Scaffold
Build/audit repository structure, CLAUDE.md, ARCHITECTURE.md, PLAN.md, CI (Ruff, strict mypy, pytest), uv + lockfile, and an empty/minimal CLI.

**Done when:** CLI installs and shows help; CI is green on the minimal project; Python 3.12 and uv workflow is established; Ruff, strict mypy, pytest run in CI; Actions are SHA-pinned and least-privilege; dependency audit is included; Phase 0 PR is merged.

**Existing-state caveat:** The repo already has a Python package, CLI, tests, and CI. Audit against these exact criteria; do not assume completion. Verify Python 3.12, uv/uv.lock, strict mypy, empty/minimal CLI acceptance, SHA-pinned Actions, and test workflow. Make only Phase 0 changes.

### Phase 1 — LOR format (highest-risk unknown)
Build fixture-driven sequence reader/writer for native .loredit.

**Done when:** Read/write fixtures; semantic round-trip tests pass; unsupported versions/constructs fail clearly; no input is modified; output is new; owner opens rewritten file in target S6 and confirms it loads. This is a mandatory human gate. Do not start preview parsing, audio analysis, or choreography during this phase. Fixtures are the format authority; ask when evidence is missing, never guess.

### Phase 2 — Preview parser
Build .lorprev → raw PropModel plus display/channel/controller data.

**Done when:** Golden tests pass on every fixture preview; revision detection and unsupported-version errors work; missing/unreadable/malformed/zero-prop previews fail; every entity has source provenance; unsupported types are explicitly reported.

### Phase 3 — Walking skeleton
Build fixed-tempo "pulse every supported prop on the beat" → Timeline → writer.

**Done when:** Complete pipeline runs with fixture preview and fixed tempo; Timeline references only preview-derived entities; expected pulse events appear; owner opens and plays it in LOR and confirms synchronization and correct display mapping. Mandatory human gate. This proves plumbing before intelligent behavior.

### Phase 4 — Audio analysis
Build beats, downbeats, onsets, sections, energy, and hard stops.

**Done when:** Analysis JSON and a debug plot are generated; plot can be eyeballed against the song; synthetic tests cover known tempo/events/energy/sections/stops; uncertainty and limitations are explicit.

### Phase 5 — Classifier
Build prop roles, orientation/direction, segment order, color capability, analyze command, and editable props.yaml.

**Done when:** Expected classifications match golden results on all fixtures; low-confidence and unknown classifications are flagged; names alone cannot determine classification; overrides win without changing channel identity; stale prop maps are rejected or explicitly migrated.

### Phase 6 — Rules engine
Build universal defaults and user profile layering.

**Done when:** rules/default.yaml and two example profiles exist; schemas and merge behavior are validated; deliberately bad Timelines are rejected with readable rule/prop/channel/timestamp errors; invalid Timelines cannot reach writer.

### Phase 7 — Planner v1
Build section-aware choreography with basic effects.

**Done when:** Real song produces a Timeline and sequence passing rules; owner opens and plays it in LOR and confirms it looks intentional, not random or merely beat-flashing; effects feel integrated into the arrangement. Mandatory human gate.

### Phase 8 — Vocals
Build vocal separation, vocal regions, syllable onsets, and singing-face choreography.

**Done when:** A supported singing face lip-syncs to words/syllables, rests during instrumentals, and keeps outline on whenever mouth channels are active; owner opens/plays result in LOR and confirms visual behavior. Mandatory human gate.

### Phase 9 — Planner v2
Build motifs, call-and-response, signature moments, and richer dynamics.

**Done when:** Two different songs produce noticeably different shows; fixed inputs/config produce deterministic planning; owner confirms arrangements are distinct and coherent.

### Phase 10 — Polish
Build reports, docs, packaging, example profiles, and installation workflow.

**Done when:** A new user can install and run by following README; reports cover generated/used/unused props, unsupported items, rules compliance, and physical-test needs; examples are included; CI is green.

## Definition of done for every phase

1. One GitHub Issue with scope and acceptance criteria.
2. One dedicated branch and one PR containing only that phase.
3. Unit tests for the stage/scaffold.
4. Golden tests across multiple fixtures wherever parsing/classification applies.
5. Semantic round-trip tests for format/writer work.
6. Negative tests for failure cases and, once available, invalid Timelines.
7. Ruff, strict mypy, pytest green in CI; dependency audit where applicable.
8. Completion summary: changes, exact tests/results, and unverified items.
9. Required human gate completed by owner.
10. PR merged and explicit owner approval before next phase.

Not-yet-applicable tests are marked pending, never falsely reported as passing.

## Current progress log

### Phase 0 — Scaffold
- Status: Not yet audited against revised acceptance criteria.
- Issue/branch/PR: Not created under the new workflow.
- Existing assets: Python package, CLI, pytest tests, Ruff workflow, CodeQL, Dependabot, security docs, README.
- Verify: Python 3.12, uv/uv.lock, strict mypy in CI, minimal CLI, SHA-pinned third-party Actions, least-privilege permissions, dependency audit.
- Tests: No Phase 0 verification run under this revised plan.
- Human gate: None.
- Next action: Audit current repo; create Phase 0 issue, branch, and PR before scaffold changes.

### Phase 1 — LOR format
- Status: Not started.
- References: one real user .lorprev and one real user .loredit example; originals must not be committed, sanitized fixtures require review.
- Human gate: owner opens rewritten sequence in target LOR S6.

## Handoff protocol

At the start of each fresh phase session: read this plan and active issue; confirm previous PR is merged and approval recorded; check branch and working tree; work only on the active phase; update this log before PR; stop after phase completion and request approval.
