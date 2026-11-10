# Implementation Plan

**Status:** Phase 1 — native LOREDIT format  
**Current phase:** 1  
**Next phase:** 2 — preview parser

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

## GitHub workflow

See [GITHUB_WORKFLOW.md](GITHUB_WORKFLOW.md) for branch, PR, review, merge, and repository-protection standards.

## Current progress log

### Phase 0 — Scaffold
- Status: Complete and merged.
- Issue: https://github.com/MikeAllen1/light-o-rama-sequence-builder/issues/4
- PR: https://github.com/MikeAllen1/light-o-rama-sequence-builder/pull/4
- Merge commit: `4dba0bdb92f0e836210dffb82d6a1c293ace012a`
- Verification: Python 3.12 CI passed pytest, Ruff, strict mypy, dependency audit, and CodeQL. See the merged PR and its linked runs.

### Phase 1 — Native S6 LOREDIT format
- Status: Implementation complete; PR #1 ready for owner review. Latest GitHub Tests and CodeQL runs are green.
- PR: https://github.com/MikeAllen1/light-o-rama-sequence-builder/pull/1
- Issue: https://github.com/MikeAllen1/light-o-rama-sequence-builder/issues/1
- Branch: `phase-1/loredit-format`
- Format evidence: owner-tested Light-O-Rama S6 `6.6.0.12`, `saveFileVersion="15"`; source sequence was sanitized into a neutral 51-prop test display with no house background or original house arrangement.
- Implementation: secure `defusedxml` parsing with DTDs/entities/external references forbidden; v15-only support boundary; opaque XML-tree preservation; `inspect` and `roundtrip` CLI; atomic create-if-absent writer; sequence-prop/preview referential-integrity validation on read and write.
- Test fixture: compressed, reduced derivative of the approved source. It retains 48 sequence props, 51 preview prop identities, 81 channels, 8 timing grids, and representative INTENSITY/TWINKLE/SHIMMER effects. Preview shape geometry is omitted from the compact automated fixture; the full neutral-grid fixture remains the human-tested baseline and is not committed.
- Local tests: `PYTHONPATH=src python -m pytest -q` — 17 passed.
- Local CLI: `inspect` reports S6 v15, 20,925 centiseconds, 48 sequence props, and 8 timing grids; `roundtrip` output is semantically equal to the source fixture.
- Human gate: complete. Owner opened the writer-generated round-trip output in S6 and explicitly confirmed it was fine.
- Local quality-tool limitation: Ruff and mypy executables are unavailable in this runtime. `uv lock --check --offline` passes. `uv sync --locked --offline` cannot install registry packages without network access. GitHub Tests run https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42917498988 passed locked sync, 17 pytest tests, Ruff, strict mypy (with pinned `types-defusedxml` stubs), and pip-audit. CodeQL run https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42917499008 passed.
- Scope boundary: no preview parser, audio analysis, Timeline, or choreography work has been started.
- Remaining: resolve any CI findings, complete PR review, obtain owner approval to merge, then stop. Do not begin Phase 2 before merge and explicit approval.

## Handoff protocol

At the start of each fresh phase session: read this plan and active issue; confirm previous PR is merged and approval recorded; check branch and working tree; work only on the active phase; update this log before PR; stop after phase completion and request approval.


## Phase 2 — Standalone LORPREV parser

- Status: Parser implementation in progress; no PR or merge yet.
- Issue: https://github.com/MikeAllen1/light-o-rama-sequence-builder/issues/5
- Branch: `phase-2/lorprev-parser`
- Source evidence: owner-supplied `Default.lorprev` (351 bytes). Root is `PreviewClass`, `Revision="0"`, with one `Scene`, empty `PropViews`, and zero `PropClass` elements.
- Fixtures: `default_empty.lorprev` preserves the safe empty S6 export as a negative test. `synthetic_display.lorprev` uses fictional identifiers, names, channel-grid values, and shape geometry, based on the observed standalone root and embedded PropClass structures.
- Parser: strict Revision=0 boundary; secure defusedxml parsing; raw attributes and XML descendants retained; per-attribute file/element locator provenance; unknown top-level nodes preserved; explicit missing/malformed/unsafe/unsupported/zero-prop errors.
- Validation limitation: the synthetic prop-bearing fixture has not yet been imported into S6. Do not claim S6 compatibility or full channel/controller semantics until independently validated. No real house/display data is committed.
- Scope remains Phase 2 only. Audio analysis, classification, props.yaml, Timeline, rules, and choreography have not been started.
