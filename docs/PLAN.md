# Implementation Plan

**Status:** Proposed — no implementation phase authorized yet  
**Approval rule:** Complete one phase, show its evidence, and stop. Do not begin the next phase until the project owner approves the completed phase.

## Delivery objective

Deliver a CLI tool that accepts an audio file and a required `.lorprev` display preview, produces a reviewed `props.yaml`, and then generates a new native S6 `.loredit` sequence choreographed to the music. The tool must be display-independent, must never invent or silently reassign physical channels, and must report anything it cannot safely support.

The Timeline JSON is the single source of truth between choreography planning, rules validation, and native LOR serialization.

## Confirmed scope and constraints

- Required preview input: `.lorprev`.
- Generated sequence: native `.loredit`.
- Target application family: LOR S6; exact target version is configurable.
- Initial real-world preview reference: `LOR_2026_Final.lorprev` (PreviewClass root, revision 58, 51 PropClass entries).
- Initial sequence-format reference: supplied Merry Christmas `.loredit` from the user's actual setup.
- V1 channel focus: single-color AC/DC and multi-color single-circuit props.
- RGB/pixel support: not used by the user's display; excluded from initial V1 implementation. Must be detected and explicitly reported as unsupported, never silently dropped.
- V1 excludes GUI, controller upload, live playback, and editing existing sequences.
- No code is written until the owner approves the architecture and plan.
- After that approval, each phase requires its own explicit approval before the next phase begins.

## Phase gates

### Phase 0 — Architecture and plan approval

**Work product:** `docs/ARCHITECTURE.md` and `docs/PLAN.md`.

**Includes:**
- Stage boundaries and data flow.
- CLI contract proposal.
- Preview/sequence format and fixture policy.
- V1 supported channel types and pixel limitation.
- Security and reliability controls.
- Phased implementation and test gates.

**Exit criteria:**
- Owner reviews and approves both documents.
- Open format questions and assumptions are accepted or revised.
- No implementation code is written in this phase.

**Approval required:** Yes. This is the current phase. Stop after publishing the documents.

### Phase 1 — Fixture inventory and format evidence

**Goal:** Establish exactly what the supplied `.lorprev` and `.loredit` files encode before writing a parser or writer.

**Work:**
- Inventory the supplied preview and sequence without modifying either.
- Identify sensitive/local metadata and create sanitized copies for repository fixtures.
- Document observed preview revision, root structure, prop/channel/controller relationships, shapes, grids, color capabilities, and stable IDs.
- Document observed sequence version, root structure, timing representation, effect representation, display references, and metadata required by S6.
- Identify mismatches or missing evidence; ask the owner for additional examples rather than guessing.
- Define semantic comparison rules for round-trip tests.
- Establish a fixture matrix and version-support policy.

**Tests/evidence:**
- Fixture provenance and sanitization checks.
- XML security tests (malformed XML, DTD/entity payloads, size limits).
- Inventory assertions for known fixture facts.
- Written list of confirmed versus unknown schema details.

**Exit criteria:**
- Sanitized fixtures are committed.
- The format notes are grounded in those fixtures.
- All writer-critical unknowns are either answered by fixtures or explicitly resolved with the owner.
- No parser/writer implementation begins before approval of this phase.

**Approval required:** Yes.

### Phase 2 — Typed domain models and secure ingest

**Goal:** Build stable Pydantic contracts and safe input handling.

**Work:**
- Set up Python 3.12, uv, lockfile, Typer, Pydantic, pytest, Ruff, and strict mypy.
- Define versioned input manifest, raw display/prop/channel/controller models, classified prop model, audio analysis model, rules model, Timeline, and report model.
- Implement extension/content checks, size and duration limits, input identity/hashing, and safe temporary-file handling.
- Implement FFmpeg normalization with argument arrays, timeouts, and no shell.
- Ensure preview is mandatory and zero-prop/unsupported-version inputs fail clearly.

**Tests/evidence:**
- Unit tests for valid/invalid input, missing preview, unreadable preview, zero props, unsupported revision, wrong extension/signature, oversize files, duration limit, and FFmpeg failure.
- No source input modified.
- Ruff, strict mypy, pytest, dependency audit pass.

**Exit criteria:** All phase tests pass in CI and the owner approves the phase summary.

**Approval required:** Yes.

### Phase 3 — Preview parser

**Goal:** Convert supported `.lorprev` fixtures into loss-minimizing raw display models.

**Work:**
- Implement defusedxml-based parser for only fixture-verified revisions.
- Preserve prop, controller, channel, grouping, shape, geometry, grid, and color metadata with source IDs/provenance.
- Explicitly identify unsupported fields/channel types.
- Add version dispatch and fail-closed behavior for unsupported revisions.

**Tests/evidence:**
- Unit tests for each parser behavior.
- Golden parse tests across multiple preview fixtures with different sizes and naming styles.
- Assertions that every parsed channel/prop maps back to source preview identity.
- Negative XML/security tests.
- Ruff, strict mypy, pytest pass.

**Exit criteria:** All fixtures parse accurately; no invented assignments; unsupported data is reported. Owner approves.

**Approval required:** Yes.

### Phase 4 — Prop classifier and editable props map

**Goal:** Produce useful, reviewable prop classifications without relying on names alone.

**Work:**
- Implement evidence-based role inference using prop type, shape, grouping, position, channel count, color capability, and name hints.
- Infer orientation, direction, and segment order only when evidence supports it.
- Generate versioned human-editable `props.yaml` with confidence, evidence, review flags, and explicit overrides.
- Validate overrides and bind them to stable preview IDs/fingerprint.
- Ensure overrides win over inferred values but cannot create/reassign channels.

**Tests/evidence:**
- Golden classification files for multiple fixture previews, varied naming, layout, shape, and channel types.
- Tests proving names alone cannot drive classification.
- Tests for low confidence, unknown props, stale maps, wrong colors, reversed segment order, and override precedence.
- Tests proving channel/controller/prop identity never changes.
- Ruff, strict mypy, pytest pass.

**Exit criteria:** Classification results are explainable and owner-reviewable. Owner approves.

**Approval required:** Yes.

### Phase 5 — Audio analysis

**Goal:** Produce a timestamped, confidence-aware musical feature model.

**Work:**
- Implement tempo, beat, downbeat, onset, section, energy, phrase, and hard-stop analysis.
- Evaluate librosa and optional madmom only against actual test signals and supported runtime.
- Evaluate Demucs vocal separation and syllable-onset detection.
- Keep vocal/syllable events separate from beat events.
- Document fallback behavior when optional vocal analysis is unavailable.

**Tests/evidence:**
- Synthetic audio fixtures with known tempo, transients, section/energy changes, and hard stops.
- Tests for timestamps, confidence, empty/invalid audio, resource limits, and analysis failure.
- Vocal tests using appropriately licensed/generated test material; no copyrighted user audio committed.
- Ruff, strict mypy, pytest pass.

**Exit criteria:** Analysis outputs are deterministic enough for tests, uncertainty is visible, and no vocal events are fabricated. Owner approves.

**Approval required:** Yes.

### Phase 6 — Timeline planner

**Goal:** Plan complete, intentional choreography as a versioned Timeline, without writing LOR XML.

**Work:**
- Define deterministic Timeline schema and JSON serialization.
- Plan by song sections and phrases, with purposeful contrast, coordinated props, transitions, holds, fades, accents, and selective activation.
- Respect role, orientation, segment order, color capability, and user overrides.
- Align singing-face mouth events to vocal syllables, not beats; require outline whenever mouth channels are active.
- Ensure motion resolves and hard stops stop motion.
- Keep choreography decisions out of the writer.

**Tests/evidence:**
- Unit tests for each planner decision family.
- Golden Timeline tests for multiple prop-map fixtures and synthetic audio scenarios.
- Determinism tests and Timeline schema-version tests.
- Negative tests for unknown prop/channel references and incomplete movement behavior.
- Ruff, strict mypy, pytest pass.

**Exit criteria:** Timeline is coherent, reproducible, and references only valid display entities. Owner approves.

**Approval required:** Yes.

### Phase 7 — Rules engine and profiles

**Goal:** Enforce universal and user-defined constraints before writing.

**Work:**
- Implement `rules/default.yaml`.
- Implement two example user profiles in `examples/`.
- Define strict schema, rule IDs, severity, tunables, and deterministic layering/merge semantics.
- Implement all universal validators in the architecture document.
- Produce readable violations naming rule, prop/channel, and timestamp.

**Tests/evidence:**
- Positive tests for valid timelines.
- Negative tests for every universal rule, malformed profiles, conflicting rules, and unknown rule keys.
- Tests for user profile layering and overrides.
- Tests that any error-level violation prevents serialization.
- Ruff, strict mypy, pytest pass.

**Exit criteria:** Invalid Timeline cannot reach the writer; reports are actionable. Owner approves.

**Approval required:** Yes.

### Phase 8 — Native S6 writer and round-trip verification

**Goal:** Serialize a validated Timeline into a native `.loredit` file that opens in the configured target LOR version.

**Work:**
- Implement writer only for fixture-confirmed target versions and channel/effect types.
- Preserve required display/sequence references and metadata as established by fixtures.
- Never invent IDs, controller assignments, channels, or unsupported effects.
- Write a new file atomically and refuse overwrite/input aliasing.
- Add semantic reader/writer comparison and target-version validation.
- Explicitly report RGB/pixel and any other unsupported data.

**Tests/evidence:**
- Round-trip tests: read fixture sequence, write it, and compare semantic content.
- Golden output tests across multiple fixture displays and supported channel types.
- Negative tests for invalid Timeline, unknown channel, unsupported effect/channel type, unsupported target version, and output overwrite.
- Open generated files in the target LOR S6 application and record exact version/result. Automated XML validity alone is not acceptance.
- Ruff, strict mypy, pytest pass.

**Exit criteria:** Native output passes semantic tests and opens in target LOR version. Owner approves.

**Approval required:** Yes.

### Phase 9 — CLI integration, reports, and release readiness

**Goal:** Deliver the complete two-step user workflow.

**Work:**
- Integrate `analyze` and `generate` using Typer.
- Require preview on both commands and reviewed props map on generate.
- Save Timeline JSON next to output and emit human/machine-readable report.
- Add actionable errors, help text, examples, and Windows-oriented setup documentation.
- Verify clean install using uv on supported Python 3.12 environment.
- Finalize security workflows and dependency pinning.

**Tests/evidence:**
- End-to-end tests from synthetic audio + sanitized preview through props map, Timeline, rules, and output.
- Missing/invalid preview must fail before output creation.
- No input file modified; no output overwrites input or existing file.
- CI runs Ruff, strict mypy, pytest, and dependency audit.
- Final manual S6 open test and report review.

**Exit criteria:** All acceptance criteria pass; unsupported features and physical-display testing requirements are clearly disclosed. Owner approves release.

**Approval required:** Yes.

## Definition of done for every phase

No phase is complete based on code being written alone. Each phase must provide:

1. Unit tests for the stage.
2. Golden-file tests across multiple fixture previews where the phase concerns preview-derived behavior, with expected classification where applicable.
3. Semantic round-trip coverage for sequence-format/writer phases.
4. Negative tests proving invalid Timelines are rejected by the rules engine.
5. Ruff, strict mypy, and pytest passing in CI (plus dependency audit where applicable).
6. A short summary: what changed, what tests verify, and what remains unverified.
7. Explicit project-owner approval before starting the next phase.

For phases where a particular test category is not yet applicable (for example, the rules engine does not exist during ingest), record it as pending rather than claiming it passed.

## Repository organization (proposed)

```text
src/lor_auto_sequencer/
  cli.py
  models/
  stages/
    ingest/
    preview_parser/
    prop_classifier/
    audio_analysis/
    planner/
    rules_engine/
    lor_writer/
    report/
  config/
tests/
  fixtures/
    previews/
    sequences/
    golden/
  unit/
  integration/
rules/
  default.yaml
examples/
  props.yaml
  rules-sample-a.yaml
  rules-sample-b.yaml
docs/
  ARCHITECTURE.md
  PLAN.md
```

The current repository may be reorganized incrementally after approval; this proposed layout is not permission to perform a broad refactor in advance.

## CI and dependency policy

- Python 3.12 and uv-managed pinned lockfile.
- Ruff lint/format checks.
- Strict mypy.
- Pytest.
- Dependency vulnerability audit.
- GitHub Actions with least-privilege permissions and all third-party actions pinned to full commit SHAs.
- Never use `pull_request_target` to execute untrusted PR code.
- Synthetic audio fixtures only; do not commit copyrighted audio.
- `.lorprev` and `.loredit` fixtures must be sanitized and approved for repository inclusion.

## Current phase status

**Phase 0 — awaiting approval.**

The architecture and plan are proposals. No implementation phase has started under this plan. The next action is owner review of `docs/ARCHITECTURE.md` and `docs/PLAN.md`. Do not begin Phase 1 or write implementation code until the owner explicitly approves Phase 0.
