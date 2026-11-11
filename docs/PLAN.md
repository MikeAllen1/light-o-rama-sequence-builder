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

1. **Sequence creation without a template.** The writer currently requires an existing native `.loredit` whose embedded preview exactly matches the `.lorprev`, then clears its effects. The planned `generate` command takes only audio, preview, and props.yaml, so a typical user has no matching template. Decide before Phase 5 is approved: (a) build a blank native v15 sequence from a preview (requires new fixtures and an S6 open-test human gate), or (b) make a matching sequence file an official `generate` input. Phases 6 and 7 build on this decision.
2. **Preview Revision 58.** `SUPPORTED_PREVIEW_REVISIONS` accepts `58`, but no committed fixture covers it, and the Phase 3 integration fixture is Revision 56 on both sides. Per the fixture policy, either commit a sanitized Revision 58 fixture with golden tests or remove `58` from the supported set.
3. **Fixture diversity before Phase 5.** All current real fixtures derive from the same 51-prop display. Classifier golden tests need 2 to 3 previews from materially different displays (different size, messy naming, legacy AC/DC) before Phase 5 can claim display independence.
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

**Status: Complete and merged.** The owner opened the generated Phase 3 package in Light-O-Rama S6 and confirmed the native sequence loads, the generic fixture preview renders without the private house image, and generated lighting events appear in the timeline. The owner accepted this as the Phase 3 completion check. Physical controller output was not independently verified; Phase 3's completed scope is native file generation and S6 preview rendering, not a claim of confirmed hardware playback.

**Done when:** The fixed-tempo pipeline generates a native v15 sequence and deterministic Timeline; S6 opens the generated file; preview and generated events render; unsupported/excluded props are enumerated.

### Phase 4 — Audio analysis
**Status: Baseline merged; acceptance review remains open.** PR #9 was squash-merged into `master` as `2b962bd39d51b052c3f97d76876a29176dc627ae` after all required CI checks passed on final head `36a98f824dcd883d032b3a49240aa8957f20d91e`.

Delivered: bounded FFmpeg normalization; deterministic RMS/positive-energy-flux/autocorrelation analysis; tempo, beat and provisional downbeat candidates; onsets; energy curve; fixed 16-beat phrase candidates; energy-transition candidates; sustained near-silence candidates including leading silence; versioned JSON and formal v1.0 JSON Schema; SVG diagnostic plot; CLI confidence reporting; Linux and Windows tests; CodeQL.

Final-head CI: Tests workflow run `42956005759` passed both Linux (pytest, Ruff, strict mypy, pip-audit) and Windows compatibility jobs. Phase 3 Validation Package run `42956005713` passed. CodeQL run `42956005698` passed. The final hard-stop timestamp test uses a tolerance consistent with the 551-sample frame duration (~49.977 ms), rather than asserting a mathematically exact 3.000-second frame boundary.

**Remaining acceptance:** owner review of diagnostic plots against contrasting real songs (fast/percussive, slower, and a song with tempo or arrangement changes), recording tempo/phase alignment, false/missed candidates, and whether confidence communicates uncertainty usefully. Confidence values remain heuristic and uncalibrated; do not treat them as probabilities or use them as the sole basis for choreography. No real-song review is claimed complete. Phase 5 remains blocked until this human review is complete and the owner explicitly approves moving forward.

**Done when:** Analysis JSON and a debug plot are generated; plot is reviewed against real songs; synthetic tests cover known tempo/events/energy/sections/stops; uncertainty and limitations are explicit; confidence behavior is reviewed; CI is green; owner approves Phase 5.

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
- Format evidence: owner-tested Light-O-Rama S6 `6.6.0.12`, `saveFileVersion="15"`; source sequence was sanitized into a neutral 51-prop test display with no house background or original house arrangement.
- Implementation: secure `defusedxml` parsing with DTDs/entities/external references forbidden; v15-only support boundary; opaque XML-tree preservation; `inspect` and `roundtrip` CLI; atomic create-if-absent writer; sequence-prop/preview referential-integrity validation on read and write.
- Test fixture: compressed, reduced derivative of the approved source. It retains 48 sequence props, 51 preview prop identities, 81 channels, 8 timing grids, and representative INTENSITY/TWINKLE/SHIMMER effects. Preview shape geometry is omitted from the compact automated fixture; the full neutral-grid fixture remains the human-tested baseline and is not committed.
- Local tests: `PYTHONPATH=src python -m pytest -q` — 17 passed.
- Local CLI: `inspect` reports S6 v15, 20,925 centiseconds, 48 sequence props, and 8 timing grids; `roundtrip` output is semantically equal to the source fixture.
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
- Owner-provided standalone preview: `Imported from roundtrip.loredit on 11_10_2026 (3).lorprev`, a fictional S6 Revision 1 export (118,026 bytes). The repo also contains the owner-provided `fixture_candidate.loredit` source with an embedded PreviewClass Revision 56; this embedded preview contains the native PropGroup that the earlier review overlooked.
- Golden fixture: `tests/fixtures/s6_revision_1_export.lorprev.gz` is a base64-encoded gzip transport copy of the sanitized S6 XML. The test decodes/decompresses it before parsing. Sanitization changes only preview/scene/prop IDs and preview/scene names; structural source values and geometry are retained.
- Observed standalone Revision 1 data: 51 PropClass entries; one Scene; one empty PropViews; 1,900 geometry points; 46 Square and 5 Hexagon props; six shape names; eight Channel_per_color props. Its controller/channel assignments are in each prop's ChannelGrid. The embedded Revision 56 PreviewClass in `fixture_candidate.loredit` has 51 PropClass entries and one PropGroup named `Fixture Group 01`, with five member references resolving to Fixture Props 011, 010, 009, 008, and 007. Group arrangement is `Preview`; each member retains orientation/top/left values. Controller assignments expose LOR network + Unit ID + circuit, while DMX exposes universe + channel. All source fields and locators are retained.
- Parser: secure defusedxml parsing; Revision 0, 1, and 56 support; raw attributes, element text, child-tail text, and XML descendants retained; per-attribute file/element locator provenance; unknown elements at any depth preserved and surfaced with source provenance; unfamiliar DeviceType and TraditionalType values surfaced as UnsupportedConstruct records with provenance; ChannelGrid rows are typed by DeviceType (LOR network/Unit ID/circuit; DMX universe/channel) while all remaining raw fields are retained; `Undetermined` remains an explicit unassigned device type; legacy `AC` and `DC` values remain recognized for Revision 0 fixture compatibility; geometry points are typed with x/y provenance and only read from direct prop shape children; explicit missing/malformed/unsafe/unsupported-revision/zero-prop errors; 20 MiB input and 256-level nesting limits. PropGroup and member references are parsed into typed group/member models; IDs are checked against the prop set and dangling references are surfaced as unsupported constructs.
- Tests: 44 tests on the current branch, including Revision 0 fixture and runtime-generated synthetic Revision 1 coverage, golden parse test for the S6-exported Revision 1 fixture, typed LOR/DMX channel address assertions against the native S6 golden fixture and synthetic DMX fixture, incomplete assignment reporting, legacy/undetermined device handling, CLI controller-address and group summary output, native Revision 56 group/member golden assertions, geometry point values, unsupported-construct reporting, provenance assertions, nested unknown controller/group-shaped element reporting, mixed-content preservation, excessive-nesting rejection, geometry-context isolation, incomplete-point rejection, and bounded file reads.
- Final PR head: `43ddf25a41d40e5529acdd80d0af027f77dc3723`. Latest successful Tests workflow: https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42939566052 — 47 pytest tests, Ruff, strict mypy, and pip-audit passed. CodeQL passed: https://github.com/MikeAllen1/light-o-rama-sequence-builder/actions/runs/42939565986. Squash merge commit: `519f081e1eedbc2cf4bf520f5a4bfc289811b123`.
- Human verification: complete. On 2026-11-10, the owner opened the sanitized Revision 1 `.lorprev` fixture supplied for S6 import and confirmed that it loads successfully. This satisfies the independent-import acceptance gate; no further preview import is requested.

- Remaining acceptance work: no new group export is required. The supplied embedded PreviewClass in `fixture_candidate.loredit` provides native S6 group evidence and is now committed as a sanitized extracted golden fixture. The parser covers Revision 56, PropGroup, member ID references, arrangement, orientation, top, and left. The original standalone Revision 1 fixture remains covered separately. The exact S6 build is recorded in the source sequence as 6.6.0.12; parser compatibility is keyed to each preview's internal Revision marker.
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
- Test fixture note: the compact LOREDIT fixture has 51 preview props but only 48 SeqProps. The Phase 3 test derives a matched preview subset from the 48 existing SeqProp identities; it does not invent channel mappings. The production command requires exact preview/template prop-ID equality and fails if any prop inside the supported type boundary lacks an existing SeqProp/channel mapping.
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
