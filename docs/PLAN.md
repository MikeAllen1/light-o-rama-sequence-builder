# Implementation Plan

**Status:** Phase 3 merged; its physical S6 playback gate is pending. Phase 4 audio-analysis branch started by explicit owner direction.  
**Current phase:** 4  
**Next phase:** 5 — prop classification (blocked until Phase 4 is complete, merged, and owner approves)

## Product objective and fixed requirements

Build a display-independent CLI that accepts audio plus a required Light-O-Rama .lorprev preview and produces a new native S6 .loredit sequence. The user workflow remains analyze → review/edit props.yaml → generate. Timeline JSON is the single source of truth and is saved beside the output.

- Preview is mandatory for analyze and generate. Missing, unreadable, malformed, unsupported-version, or zero-prop previews fail clearly.
- Props, controllers, and channels must originate from the preview or reviewed user prop map. Never invent or silently reassign them.
- Classification combines prop type, shape, grouping, position, channel count, color, and name hints; never names alone.
- Product target includes legacy AC/DC single-color and LOR multi-color/single-circuit props. Phase 3 is intentionally narrower: it generates only verified `DeviceType=LOR` mappings for `Single Color`, `Multicolor_string_1_ch`, and `Channel_per_color`. AC/DC remains parseable but excluded until its native S6 channel mapping is independently verified; see the Phase 3 boundary in ARCHITECTURE.md.
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
- A phase is complete only when acceptance criteria pass, CI is green, the PR is merged, required human verification is recorded, and the owner approves moving forward. The owner explicitly authorized Phase 4 branch work to proceed while Phase 3's physical playback gate remains pending; Phase 4 must not be merged until that gate is reported complete and the owner explicitly authorizes the merge.
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
Build .lorprev / embedded PreviewClass → raw PropModel plus display/channel/controller/group data.

**Done when:** Golden tests pass on every fixture preview; revision detection and unsupported-version errors work; missing/unreadable/malformed/zero-prop previews fail; every entity has source provenance; unsupported types are explicitly reported.

### Phase 3 — Walking skeleton
Build fixed-tempo "pulse every supported prop on the beat" → Timeline → writer.

**Done when:** The independent S6 Revision 58 standalone preview + native v15 sequence fixture runs through the fixed-tempo pipeline; full prop geometry and group parity is checked; every generated event carries a verified ChannelGrid address and native channel coordinate; unsupported/excluded props are enumerated; Timeline and native output are deterministic/validated; owner opens and plays the output in LOR and confirms synchronization and correct physical lights. Mandatory human gate. This proves plumbing before intelligent behavior.

### Phase 4 — Audio analysis

- Status: Initial audio-analysis engine is implemented and being hardened on the dedicated branch. Draft PR #9 remains open and unmerged. Current CI is green on the latest code head; real-song diagnostic plot review and the Phase 3 physical S6 playback gate remain pending.
- Issue: https://github.com/MikeAllen1/light-o-rama-sequence-builder/issues/8
- Branch: `phase-4/audio-analysis` (isolated from `master`; development proceeds in parallel with the owner's Phase 3 playback test).
- Scope: audio validation/normalization, tempo and beat estimation, provisional downbeats, onsets/transients, phrase/section estimates, energy/dynamics, hard stops, versioned analysis JSON, and a debug plot. All event classes remain distinct and uncertain estimates carry confidence.
- Non-goals: prop classification/props.yaml, rules engine, choreography/effect planning, vocal separation/syllable detection, and changes to native S6 serialization.
- Phase 3 dependency: the owner will test the Phase 3 generated sequence in S6. By explicit owner instruction, Phase 4 development proceeds in parallel, but this branch must remain unmerged until the owner reports the Phase 3 physical playback result and explicitly authorizes the Phase 4 merge.
- Dependency decision: no new Python packages. FFmpeg is an explicit external runtime dependency for decoding/normalization; CI installs it through the Ubuntu package manager. Signal extraction after normalization uses the Python standard library. Inputs are limited to 200 MiB, two seconds minimum, and 30 minutes maximum. Output schema v1.0 separates tempo, beats, downbeats, onsets, RMS energy, phrase candidates, energy-transition candidates, and hard-stop candidates. CLI tempo bounds are configurable from 30 to 300 BPM (default 60–200); selected bounds are recorded in the JSON. Confidence and known limitations are embedded in the JSON.
- PR: https://github.com/MikeAllen1/light-o-rama-sequence-builder/pull/9 (draft; intentionally unmerged).
- Implementation: `src/lor_sequence_builder/audio_analysis.py`; CLI: `analyze-audio`; formal JSON Schema: `docs/schemas/audio-analysis-v1.schema.json`; tests: `tests/test_audio_analysis.py`; real-song review procedure: `docs/AUDIO_ANALYSIS_REVIEW.md`; FFmpeg installation is part of the Tests workflow.
- Coverage hardening on the current branch: MP3 encode/decode ingestion and tempo recovery; 90 BPM tempo alias behavior under the default 60–200 BPM search range; minimum duration, 200 MiB input-size, and 30-minute duration rejection. Existing synthetic coverage includes known 120/90 BPM click tracks, silence and constant-tone no-tempo cases, transient-heavy noise, energy transitions, hard stops, output safety, provenance, CLI configuration, SVG overlays, and schema-contract checks.
- Latest code head: `ea4dc468f501a71b67f367bb54b41d2a7fb1177e`. Tests workflow: https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42947625768 — 90 pytest tests passed, Ruff passed, strict mypy passed, and pip-audit passed. CodeQL: https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42947631461 — passed.
- Human verification: pending owner S6 playback test for Phase 3; Phase 4 analysis plot/audio alignment review will also be required before Phase 4 is considered complete.
