# Implementation Plan

**Status:** Phases 0–3 complete and merged. The Phase 4 audio-analysis baseline is merged; its real-song review and confidence-calibration acceptance work remains open.  
**Current phase:** 4 acceptance review  
**Next phase:** 5 — prop classification (blocked until Phase 4 acceptance is complete and the owner approves).

## Product objective and fixed requirements

Build a display-independent CLI that accepts audio plus a required Light-O-Rama .lorprev preview and produces a new native S6 .loredit sequence. The user workflow remains analyze → review/edit props.yaml → generate. Timeline JSON is the single source of truth and is saved beside the output.

- Preview is mandatory for analyze and generate. Missing, unreadable, malformed, unsupported-version, or zero-prop previews fail clearly.
- Props, controllers, and channels must originate from the preview or reviewed user prop map. Never invent or silently reassign them.
- Classification combines prop type, shape, grouping, position, channel count, color, and name hints; never names alone.
- Product target includes legacy AC/DC single-color and LOR multi-color/single-circuit props. Phase 3 is intentionally narrower: it generates only verified `DeviceType=LOR` mappings for `Single Color`, `Multicolor_string_1_ch`, and `Channel_per_color`. AC/DC remains parseable but excluded until its native S6 channel mapping is independently verified; see the Phase 3 boundary in ARCHITECTURE.md.
- RGB/pixel is outside v1. Detect and report unsupported pixel props; never silently drop or fake support.
- Physical overrides in props.yaml win over inferred preview interpretation but cannot create channel identities.
- Rules are configuration; invalid Timelines fail with readable rule, prop/channel, and timestamp details.
- Never modify/overwrite inputs. Output is a new file.
- V1 excludes GUI, controller upload, live playback, and editing existing sequences.
- Python 3.12, uv + committed lockfile, Pydantic, Typer, pytest, Ruff, strict mypy.
- XML via defusedxml; YAML safe_load; FFmpeg argument list, never shell=True; input size/type/duration limits.
- No secrets in code; .env gitignored; pin dependencies and run pip-audit.
- CI uses least privilege and third-party Actions pinned to full commit SHAs. Never use pull_request_target to execute untrusted PR code.
- Synthetic audio tests only; never commit copyrighted audio.

## Recorded stack deviations

These differ from the original stack proposal. They are intentional and accepted unless the owner reopens them:

- **Models:** frozen `dataclasses` are used for stage models instead of Pydantic. Pydantic remains the expected choice for user-edited inputs (`props.yaml`, rules profiles) where schema validation and error messages matter; adopt it in the phase that first parses those files.
- **CLI:** `argparse` is used instead of Typer. Acceptable for v1; revisit only if CLI complexity grows.
- **Audio:** the Phase 4 baseline uses the Python standard library after FFmpeg normalization, with no librosa dependency. This keeps installation and the dependency surface small, but it cannot provide semantic section labels, tempo-change tracking, or vocal analysis. Phase 8 (and possibly section work in Phase 7) will require heavier dependencies such as librosa and Demucs; adding them must be recorded here.

## Open decisions (owner input required before the phase that depends on them)

1. **Sequence creation without a template (resolved 2026-11-11).** Owner chose to build sequences from scratch: `generate` takes audio, preview, and props.yaml only, and the tool creates a new native sequence itself. A template is not a required input. This becomes Phase 4b, scheduled after Phase 4 acceptance and before Phase 5 because it is the largest remaining format unknown.
2. **Preview Revision (resolved 2026-11-11).** Owner clarified that `PreviewClass/@Revision` is an edit counter incremented on each save, not a format version. The parser's revision allowlist (which rejected any preview not at revision 0, 1, 56, or 58) was removed; the value is now optional metadata. Compatibility is judged by structure. Do not reintroduce revision-based gating.
3. **Fixture diversity before Phase 5.** Current committed fixtures are synthetic and intentionally limited. Classifier golden tests need 2 to 3 previews from materially different displays (different size, messy naming, legacy AC/DC) before Phase 5 can claim display independence. Any additional owner-provided examples must remain local; do not commit original or sanitized owner show material.
4. **License.** An MIT `LICENSE` was added in the docs-cleanup PR as a proposed default. The owner should confirm or replace it before merge.

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
Build/audit repository structure, CONTRIBUTING.md, ARCHITECTURE.md, PLAN.md, CI (Ruff, strict mypy, pytest), uv + lockfile, and an empty/minimal CLI.

**Done when:** CLI installs and shows help; CI is green on the minimal project; Python 3.12 and uv workflow is established; Ruff, strict mypy, pytest run in CI; Actions are SHA-pinned and least-privilege; dependency audit is included; Phase 0 PR is merged.

**Existing-state caveat:** The repo already has a Python package, CLI, tests, and CI. Audit against these exact criteria; do not assume completion. Verify Python 3.12, uv/uv.lock, strict mypy, empty/minimal CLI acceptance, SHA-pinned Actions, and test workflow. Make only Phase 0 changes.

### Phase 1 — LOR format (highest-risk unknown)
Build fixture-driven sequence reader/writer for native .loredit.

**Done when:** Read/write fixtures; semantic round-trip tests pass; unsupported versions/constructs fail clearly; no input is modified; output is new; owner opens rewritten file in target S6 and confirms it loads. This is a mandatory human gate. Do not start preview parsing, audio analysis, or choreography during this phase. S6-generated reference files and documented structural observations are the format evidence; synthetic fixtures provide regression coverage, not native-format authority. Ask when evidence is missing; never guess.

### Phase 2 — Preview parser
Build .lorprev / embedded PreviewClass → raw PropModel plus display/channel/controller/group data.

**Done when:** Golden tests pass on every fixture preview; preview edit revision is recorded as metadata but never gates parsing; missing/unreadable/malformed/zero-prop previews fail; every entity has source provenance; unsupported types are explicitly reported.

### Phase 3 — Walking skeleton
Build fixed-tempo "pulse every supported prop on the beat" → Timeline → writer.

**Status: Complete and merged.** The owner opened the generated Phase 3 package in Light-O-Rama S6 and confirmed the native sequence loads, the synthetic fixture preview renders, and generated lighting events appear in the timeline. The owner accepted this as the Phase 3 completion check. Physical controller output was not independently verified; Phase 3's completed scope is native file generation and S6 preview rendering, not a claim of confirmed hardware playback.

**Done when:** The fixed-tempo pipeline generates a native v15 sequence and deterministic Timeline; S6 opens the generated file; preview and generated events render; unsupported/excluded props are enumerated.

### Phase 4 — Audio analysis
**Status: Baseline merged; acceptance review remains open.** PR #9 was squash-merged into `master` as `2b962bd39d51b052c3f97d76876a29176dc627ae` after all required CI checks passed on final head `36a98f824dcd883d032b3a49240aa8957f20d91e`.

Delivered: bounded FFmpeg normalization; deterministic RMS/positive-energy-flux/autocorrelation analysis; tempo, beat and provisional downbeat candidates; onsets; energy curve; fixed 16-beat phrase candidates; energy-transition candidates; sustained near-silence candidates including leading silence; versioned JSON and formal v1.0 JSON Schema; SVG diagnostic plot; CLI confidence reporting; Linux and Windows tests; CodeQL.

Final-head CI: Tests workflow run `42956005759` passed both Linux (pytest, Ruff, strict mypy, pip-audit) and Windows compatibility jobs. Phase 3 Validation Package run `42956005713` passed. CodeQL run `42956005698` passed. The final hard-stop timestamp test uses a tolerance consistent with the 551-sample frame duration (~49.977 ms), rather than asserting a mathematically exact 3.000-second frame boundary.

**Remaining acceptance:** owner review of diagnostic plots against contrasting real songs (fast/percussive, slower, and a song with tempo or arrangement changes), recording tempo/phase alignment, false/missed candidates, and whether confidence communicates uncertainty usefully. Confidence values remain heuristic and uncalibrated; do not treat them as probabilities or use them as the sole basis for choreography. No real-song review is claimed complete. Phase 5 remains blocked until this human review is complete and the owner explicitly approves moving forward.

**Done when:** Analysis JSON and a debug plot are generated; plot is reviewed against real songs; synthetic tests cover known tempo/events/energy/sections/stops; uncertainty and limitations are explicit; confidence behavior is reviewed; CI is green; owner approves Phase 5.

### Phase 4b — Scratch-built sequence writer
Build a native S6 v15 `.loredit` from a parsed `.lorprev` alone, with no template sequence: sequence metadata, embedded preview, one `SeqProp` and native channel record per supported preview channel, timing grid, duration, and audio reference. Replace the Phase 3 template requirement in `pulse` with this writer.

**Evidence first:** Before writing code, collect native fixtures that show how S6 represents a brand-new sequence created from a preview: at minimum, a new empty sequence created in S6 from a fixture preview, and the same sequence after adding audio. Compare them against the existing v15 fixtures and document every field the writer must produce in `docs/S6_FORMAT.md`. Ask the owner for any field the fixtures do not explain; never fill gaps from memory.

**Done when:** A scratch-built sequence for every committed fixture preview is semantically equal to its S6-created reference fixture (props, channel coordinates, addresses, timing, metadata); unsupported props are enumerated, never silently dropped; `pulse` works with only a preview, audio duration or explicit duration, and BPM; the template path is removed or explicitly deprecated; inputs are never modified; the owner opens a scratch-built sequence in S6, confirms it loads, the preview renders, and events appear. Mandatory human gate.

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
- Status: Complete and merged in PR #1. The owner opened the writer-generated round-trip output in S6 and confirmed it loads.
- PR: https://github.com/MikeAllen1/light-o-rama-sequence-builder/pull/1
- Issue: https://github.com/MikeAllen1/light-o-rama-sequence-builder/issues/1
- Branch: `phase-1/loredit-format`
- Format evidence: Light-O-Rama S6 `6.6.0.12`, `saveFileVersion="15"`, was used for the initial format investigation. Owner-derived fixture content was subsequently removed from the current repository tree; keep original show material and all derivatives local.
- Implementation: secure `defusedxml` parsing with DTDs/entities/external references forbidden; v15-only support boundary; opaque XML-tree preservation; `inspect` and `roundtrip` CLI; atomic create-if-absent writer; sequence-prop/preview referential-integrity validation on read and write.
- Test data: the current test suite uses synthetic or runtime-generated XML with fictional identifiers and values. No owner sequence fixture is required as a test input in the current tree.
- Local tests: `PYTHONPATH=src python -m pytest -q` — 17 passed.
- Local CLI: `inspect` and `roundtrip` smoke tests passed against the then-current local test input; owner-derived input data is not retained in the repository.
- Human gate: complete. Owner opened the writer-generated round-trip output in S6 and explicitly confirmed it was fine.
- Local quality-tool limitation: Ruff and mypy executables are unavailable in this runtime. `uv lock --check --offline` passes. `uv sync --locked --offline` cannot install registry packages without network access. GitHub Tests run https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42917498988 passed locked sync, 17 pytest tests, Ruff, strict mypy (with pinned `types-defusedxml` stubs), and pip-audit. CodeQL run https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42917499008 passed.
- Scope boundary: no preview parser, audio analysis, Timeline, or choreography work has been started.
- Completion: PR #1 was merged before Phase 2 began; the S6 writer validation gate is complete.

## Handoff protocol

At the start of each fresh phase session: read this plan and active issue; confirm previous PR is merged and approval recorded; check branch and working tree; work only on the active phase; update this log before PR; stop after phase completion and request approval.


## Phase 2 — Preview parser

- Status: Complete and merged. PR #6 was squash-merged into master on 2026-11-10. The supplied native S6 PreviewClass group evidence is covered; the earlier assertion that group evidence was missing was incorrect.
- Issue: https://github.com/MikeAllen1/light-o-rama-sequence-builder/issues/5
- PR: https://github.com/MikeAllen1/light-o-rama-sequence-builder/pull/6
- Branch: `phase-2/lorprev-parser`
- Historical format validation used S6-exported preview data, including prop geometry, LOR/DMX address fields, and native PropGroup/member structures. The owner-derived source files and sanitized derivatives were removed from the current repository tree in PR #15. Do not restore them or include owner/customer sequence material in future commits.
- Current fixture policy: the static preview is the hand-authored fictional `tests/fixtures/synthetic_display.lorprev`; larger preview/sequence inputs are generated at test time by `tests/fixture_builders.py`. Synthetic tests cover parser behavior without retaining owner data.
- Parser: secure defusedxml parsing; Revision 0, 1, and 56 support; raw attributes, element text, child-tail text, and XML descendants retained; per-attribute file/element locator provenance; unknown elements at any depth preserved and surfaced with source provenance; unfamiliar DeviceType and TraditionalType values surfaced as UnsupportedConstruct records with provenance; ChannelGrid rows are typed by DeviceType (LOR network/Unit ID/circuit; DMX universe/channel) while all remaining raw fields are retained; `Undetermined` remains an explicit unassigned device type; legacy `AC` and `DC` values remain recognized for Revision 0 fixture compatibility; geometry points are typed with x/y provenance and only read from direct prop shape children; explicit missing/malformed/unsafe/unsupported-revision/zero-prop errors; 20 MiB input and 256-level nesting limits. PropGroup and member references are parsed into typed group/member models; IDs are checked against the prop set and dangling references are surfaced as unsupported constructs.
- Historical Phase 2 verification covered revision metadata, LOR/DMX address parsing, legacy/undetermined device handling, groups and member references, geometry, provenance, unsupported constructs, malformed XML, and parser resource limits. Current regression tests use synthetic or runtime-generated data; the original owner-derived golden files are no longer present in the current tree.
- Final PR head: `43ddf25a41d40e5529acdd80d0af027f77dc3723`. Latest successful Tests workflow: https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42939566052 — 47 pytest tests, Ruff, strict mypy, and pip-audit passed. CodeQL passed: https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42939565986. Squash merge commit: `519f081e1eedbc2cf4bf520f5a4bfc289811b123`.
- Human verification: complete. The owner confirmed a test preview imports successfully in S6 on 2026-11-10. This records the historical acceptance check; it does not authorize retaining the source display export in the repository.

- Remaining acceptance work: group/member parsing and preview revision metadata remain covered by synthetic regression tests. `PreviewClass/@Revision` is an edit counter, not a format version, and must not be used as a compatibility gate. No owner-derived preview or sequence file is required or permitted in the current test fixture set.
- Scope was Phase 2 only. Phase 3 began only after the owner explicitly approved it.


### Phase 2 hardening follow-up — 2026-11-10
- Added incremental secure XML scanning with a 100,000-element ceiling in addition to the existing 20 MiB input and 256-level nesting limits. The bounded scan completes before the typed raw model is constructed; the same in-memory bytes are then reparsed with defusedxml.
- Added explicit unsupported-construct reporting for missing/blank and duplicate PropClass IDs. Source props remain preserved; invalid identities are not treated as reliable keys.
- Clarified that ChannelGrid parsing currently exposes address fields only (LOR network/Unit ID/circuit and DMX universe/channel). Other fields remain raw and must not be assumed semantically interpreted by later phases.
- Updated CLI summary wording so its unsupported-construct count includes group and channel-assignment issues, not only prop/device declarations.
- Added three regression tests. Latest successful Tests workflow on head `43ddf25a41d40e5529acdd80d0af027f77dc3723`: 47 passed, Ruff passed, strict mypy passed, and pip-audit passed. CodeQL passed on that head.


## Phase 3 — Fixed-tempo Timeline walking skeleton

- Status: **Complete and merged** (see the Phase 3 entry under Phase order for the accepted gate). The bullets below are the historical implementation log from while PR #7 was open; where they conflict with the current Phase 3 boundary (for example, `Channel_per_color` is now supported), the Phase order section and ARCHITECTURE.md are authoritative.
- Issue: https://github.com/MikeAllen1/light-o-rama-sequence-builder/issues/7
- PR: https://github.com/MikeAllen1/light-o-rama-sequence-builder/pull/7
- Branch: `phase-3/walking-skeleton`
- Scope: Required standalone preview + exact-ID and per-prop channel-declaration-matching native S6 v15 template → fixed-BPM beat positions → deterministic versioned Timeline → native LOREDIT with intensity pulses.
- CLI: `lor-sequence-builder pulse --preview display.lorprev --template template.loredit --bpm 120 --output pulse.loredit --timeline-output pulse.timeline.json`.
- Support boundary: only `DeviceType=LOR` with `TraditionalType=Single Color` or `Multicolor_string_1_ch`, complete LOR ChannelGrid addresses, and existing native channel records in the template. Unsupported types are enumerated in Timeline JSON. A prop inside the supported type boundary that lacks a preview address or native channel mapping fails closed with its prop ID.
- Native channel identity: existing template `channel` row/col/color coordinates are preserved as the channel reference; no channel coordinate is invented from ChannelGrid. The template's embedded preview geometry and group arrangement are retained; Phase 3 does not merge those from the standalone preview, so the two inputs must describe the same physical layout.
- Timeline: schema version 1.0; integer centiseconds; fixed integer BPM; deterministic rounded beat positions; SHA-256 fingerprints of the validated parsed XML trees; supported/excluded prop lists; per-channel pulse events.
- Writer behavior: clear old effects in the in-memory template copy, add only generated intensity pulses, write a new LOREDIT and Timeline JSON, re-read the generated LOREDIT, and refuse output/input aliasing and overwrites. The template's duration defines sequence duration. Beat allocation is capped at 50,000 beats and Timeline events at 250,000.
- Test fixture note: Phase 3 tests derive a matched preview subset from existing native `SeqProp` identities; they do not invent channel mappings. The production command requires exact preview/template prop-ID equality and fails if any prop inside the supported type boundary lacks an existing `SeqProp`/channel mapping.
- Tests added: fixture-backed end-to-end pipeline, deterministic Timeline output, exact preview/template identity and channel-declaration matching, BPM and pulse-duration validation, no-overwrite/input-alias checks, native output re-read, fail-closed missing/incomplete native channel mapping, complete per-beat/per-channel event coverage, oversized-duration protection, and explicit unsupported-prop reporting.
- Human gate (historical, now complete): owner opened the generated package in S6 and confirmed it loads and its events render. Physical controller output was not independently verified.
- Latest code-bearing commit: `b0872b46292276d97b0eb42ba1eb4d8ebb4ec8b5`. Tests workflow: https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42941298309 — 65 pytest tests passed, Ruff passed, strict mypy passed, and pip-audit passed. CodeQL: https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42941303887 — passed. The subsequent handoff-log-only update was also validated: Tests https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42941442561 and CodeQL https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42941442362 both passed.
- Remaining Phase 3 work: none. Superseded by the completed gate above.


## Phase 4 implementation boundary

The Phase 4 baseline is merged in `2b962bd39d51b052c3f97d76876a29176dc627ae`. The analyzer emits a versioned JSON report and SVG diagnostic plot using bounded FFmpeg normalization. It estimates a single global tempo and heuristic event candidates; it does not claim semantic section recognition, tempo-change tracking, spectral onset classification, or choreography. Real-song diagnostic review and confidence calibration remain acceptance tasks.

### Phase 4 merge and handoff — 2026-11-10/11
- PR: https://github.com/MikeAllen1/light-o-rama-sequence-builder/pull/9
- Branch: `phase-4/audio-analysis`
- Final branch head: `36a98f824dcd883d032b3a49240aa8957f20d91e`
- Merge: squash commit `2b962bd39d51b052c3f97d76876a29176dc627ae`
- Final verification: Tests run `42956005759` passed on Linux and Windows; Phase 3 Validation Package run `42956005713` passed; CodeQL run `42956005698` passed.
- Final hardening: corrected cross-platform frame-time test tolerance; documented leading-silence hard-stop candidates; beat-grid confidence is reported separately from tempo confidence.
- Human gate: pending real-song review. No user audio or real-song diagnostic outputs have been reviewed in this phase.
- Next step: complete real-song review and evaluate whether confidence and candidate markers are useful before requesting approval for Phase 5. Do not start classifier work until owner approval.
