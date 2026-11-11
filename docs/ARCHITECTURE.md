# Architecture

**Status:** Architecture and confirmed design decisions only. Current implementation phase, review state, and next approved work are maintained in [PLAN.md](PLAN.md); do not infer project phase status from this document.  
**Project:** Light-O-Rama Sequence Builder  
**V1 interface:** Command line  
**Target output:** Native Light-O-Rama S6 `.loredit` sequence  
**Required display input:** Light-O-Rama `.lorprev` preview

## 1. Purpose and scope

LOR Auto-Sequencer accepts an audio file and the display's required `.lorprev` file, then creates a new native LOR sequence choreographed to the music. It is intended to work with different LOR displays without embedding any particular user's prop names, channel numbers, controller assignments, layout, or naming conventions in code.

The workflow has two explicit commands:

1. `analyze-preview` reads the required preview, classifies its props, and reports each conclusion with its evidence and a review list.
2. The user reviews the report and corrects anything wrong in the S6 Preview Editor itself (owner decision, 2026-11-11: the preview is the only display input; there is no separate prop map). `generate` reads the audio and preview, classifies the props the same way, analyzes the music, plans choreography, validates the resulting Timeline, and writes a new `.loredit` file plus the Timeline JSON and a report.

The original audio, preview, and any reference sequence are read-only inputs. Output paths must be new paths; the tool must refuse to overwrite an input or an existing output unless a future explicit and separately approved policy says otherwise. V1 does not edit existing sequences.

## 2. Confirmed project decisions

- The display preview input is **`.lorprev`** and is mandatory for both `analyze` and `generate`.
- The generated sequence output is **`.loredit`**, intended to open in the configured target LOR S6 version.
- The current committed preview fixture is `tests/fixtures/synthetic_display.lorprev`, a small hand-authored fictional XML example. Larger sequence and preview test inputs are generated at test time with fictional identifiers, names, addresses, and geometry.
- The repository's current fixture policy is synthetic-only. Historical owner-derived and sanitized show material was removed from the current tree in PR #15; do not restore it. Format claims must be supported by documented observations, synthetic regression coverage, and owner-run S6 verification without retaining private source files.
- RGB/pixel support is a declared V1 limitation, not something to fake or infer. If a preview contains a channel/prop type the current writer cannot safely represent, the tool must report it and must not silently drop it or claim full support.
- V1 is CLI-only. GUI, controller upload, live playback, and editing existing sequences are out of scope.

## 3. Design principles

1. **Preview is authoritative for the display.** Every emitted prop, controller, channel, and channel assignment must trace to the parsed preview, which is the only display input. Physical corrections are made in the preview itself. No generated or guessed channels.
2. **No preview, no sequence.** Missing, unreadable, malformed, unsupported-version, oversized, or zero-prop previews are fatal errors with actionable messages.
3. **Names are evidence, not identity.** Classification combines prop type, shape, grouping, position, channel count, color capability, and name hints. Names alone never determine a role.
4. **Unknowns remain visible.** Unknown roles, unsupported channel types, uncertain orientation, and low-confidence classifications are surfaced in the classification report and the final generation report.
5. **Music drives the arrangement.** Choreography is planned around song structure, phrasing, dynamics, instrumentation, vocals, transitions, and intentional contrast—not just beat flashes.
6. **One intermediate truth.** The Timeline JSON is the sole choreography representation consumed by validation and serialization.
7. **Rules are configuration.** Universal rules ship in `rules/default.yaml`; user profiles layer on top without modifying application code.
8. **The writer does not choreograph.** `lor_writer` serializes a validated Timeline into the exact supported LOR format.
9. **Inputs are immutable and untrusted.** Parsing is hardened, resource limits are explicit, and output is always written separately.
10. **Format claims require evidence.** S6-generated samples must be inspected locally and the resulting structural observations documented; synthetic regression tests protect implemented behavior, and the owner must open generated files in the target LOR application. Do not commit owner/customer source files or sanitized derivatives.

## 4. High-level data flow

```text
analyze-preview
  required .lorprev
       |
  preview_parser ----> RawDisplay / RawProp models
       |
  prop_classifier ---> classified props + confidence + evidence
       |
  report  ----------> human review; corrections made in the S6 Preview Editor

generate
  audio + required .lorprev
       |
     ingest
       |--------------------------|
  preview_parser             audio_analysis
       |                          |
  prop_classifier                 |
       |                          |
       |                    musical features
       |                          |
       +---------- planner -------+
                      |
                   Timeline
                      |
                 rules_engine <--- default + user rules
                      |
                validated Timeline
                   /         \
          Timeline JSON    lor_writer
                                |
                         new .loredit file
                                |
                       report + verification
```

Current internal stage models use frozen dataclasses with explicit validation. User-edited rule profiles are validated by explicit code that rejects unknown keys, wrong types and out-of-range values. A stage may use the public models of another stage, but it must not reach into that stage's implementation internals. Stage orchestration belongs in the application/CLI layer.

## 5. Stage responsibilities and contracts

### 5.1 `ingest`

**Inputs:** Audio path, required preview path, target LOR version, configured resource limits.

**Responsibilities:**
- Require both input files and validate regular-file status, extensions, size limits, and file signatures/content before expensive parsing.
- Enforce audio duration limits and reject unsupported or malformed media.
- Normalize audio to a documented analysis format using FFmpeg invoked with an argument list and never `shell=True`.
- Verify FFmpeg's output and report its version and normalization parameters.
- Never mutate either source file.

**Outputs:** Validated input metadata and a normalized temporary audio asset. Temporary data is local and cleaned up safely.

### 5.2 `preview_parser`

**Input:** Validated `.lorprev` path.

**Responsibilities:**
- Parse XML with `defusedxml`; reject DTD/entity expansion and malformed XML.
- Identify the root/schema family (`PreviewClass`) before interpreting fields. `PreviewClass/@Revision` is an edit counter that S6 increments each time a preview is saved. It is not a format version: it is recorded as metadata only and must never be used to accept, reject, or interpret a preview.
- Parse into raw, loss-minimizing typed models: display metadata, props, prop IDs, groups, geometry/position, shape/grid, channel count and assignments, device/controller references, color/channel capability, and any other relevant metadata present in the preview.
- Preserve source identifiers and provenance for every channel and prop.
- Fail clearly on structurally unsupported or ambiguous constructs rather than best-effort parsing that could corrupt assignments.
- Treat names and descriptive metadata as untrusted text.

**Outputs:** `RawDisplayModel` and `RawPropModel[]`.

**Known preview references:** the hand-authored fictional fixture at `tests/fixtures/synthetic_display.lorprev` and additional runtime-generated synthetic previews. Tests exercise structural parsing, including groups and members, without requiring owner/customer display exports in the repository. The LOREDIT `saveFileVersion` is a real format version and remains gated; `PreviewClass/@Revision` is an edit counter recorded as optional metadata, not a format gate.

**Controller/channel interpretation:** Each LOR prop `ChannelGrid` row exposes network, Unit ID, and the circuit value present in that row; each DMX row exposes universe and channel. These are address fields, not a complete interpretation of every field or channel-range behavior. Remaining row fields are retained verbatim and are not yet semantically interpreted. The parser retains the complete original value and source locator. `Undetermined` is a recognized unassigned device type. Later phases must not infer channel counts, ranges, color semantics, or controller capabilities from unparsed fields.

**Group interpretation:** A direct `PropGroup` contains direct `member` elements. The parser exposes group ID, name, arrangement, ordered member prop IDs, orientation, top, and left values. It validates that each referenced member ID resolves to a prop in the same preview; missing or dangling references are preserved and reported as unsupported constructs. Raw group/member elements and per-attribute provenance remain available.

### 5.3 `prop_classifier`

**Input:** the parsed preview only.

**Responsibilities:**
- Infer roles: arch, mini tree, mega tree, star, singing face, icicles, outline, snowflake, or unknown. Unknown is a valid outcome.
- Combine evidence the way a person reads a preview: S6 shape type and parameters (`Parm1` is the segment or strand count; parametric shapes store center and size in `OffsetX`/`OffsetY`/`ScaleX`/`ScaleY`), geometry (arcs, closed outlines, long flat runs), channel count and `TraditionalType`, `PropGroup` membership and order, matching repeated props ordered left to right, and `MasterPropId` links.
- Names: when the shape type is specific or structural evidence exists, the name is a tiebreaker (0.25). When the shape type is generic (plain lines) and nothing structural contradicts it, the name decides (0.55), flagged for review.
- Small props drawn on top of each other form a figure; a figure with a clear face part (mouth, mustache) is a singing face, and linked parts drawn on it join it. Rows require look-alike props at a similar size and height, and only count when their members end up the same role.
- Direction comes from `StartLocation` and is reported only for props that chase; otherwise it is unknown or not applicable. Segment order is the `ChannelGrid` order.
- Color capability follows `TraditionalType`: single color, combined colors on one circuit (no color can be shown alone), or one color per channel. Sequencing support uses the same check as the sequence builder.
- Every conclusion carries its evidence and review notes; close calls, weak evidence, and unsupported hardware are flagged for review.
- Never modify the preview or manufacture a channel, controller, prop, or assignment.

**Output:** `PropClassification` records and a JSON report.

### 5.4 `audio_analysis`

**Input:** Normalized audio.

**Responsibilities:**
- Estimate tempo, beats, downbeats, onsets/transients, phrase/section boundaries, energy, and hard stops.
- Estimate intro, verse, chorus, bridge, and outro sections with confidence/evidence; do not represent uncertain section labels as facts.
- Support vocal stem separation and vocal syllable-onset detection for singing-face choreography.
- Keep beat, downbeat, onset, vocal, and section events as distinct concepts. Mouth animation follows detected vocal syllables, not the beat.
- Report unavailable or low-confidence analysis rather than inventing events.

**Implementation notes:** Librosa is the analysis foundation (adopted in the Phase 4 rework); it receives only FFmpeg-decoded sample arrays and never opens files. Demucs may be used for vocal separation. Madmom is an alternative only if its Python/runtime compatibility and maintenance are validated. Vocal separation and syllable detection are computationally expensive and must have explicit dependency, runtime, and failure behavior. If vocal analysis is unavailable, singing-face mouth animation must be disabled or flagged for user review; it must not fall back to beat-driven mouth movement.

**Output:** Typed musical feature models with timestamps, confidence, and provenance.

### 5.5 `planner`

**Inputs:** Classified display/props, musical features, active rules/tunables.

**Responsibilities:**
- Identify musical sections and phrases and assign choreography roles by section.
- Plan purposeful contrast, repetition with variation, transitions, accents, holds, fades, coordinated groups, and selective prop activation.
- Respect each prop's role, direction, segment order, row position, and color capability as read from the preview.
- Use singing faces only in detected vocal regions and align mouth events to syllable onsets when available.
- Stop motion at hard musical stops and resolve multi-segment movements.
- Avoid activating every prop simultaneously; create dynamic contrast across sections.
- Generate decisions as data, not LOR XML.

**Output:** A typed `Timeline` model. This is the only source of truth for all choreography.

### 5.6 `rules_engine`

**Inputs:** Timeline, display/prop model, active rules profile.

**Responsibilities:**
- Load YAML profiles with a safe loader that rejects duplicate keys.
- Validate every Timeline command against known preview-derived channels and prop mappings.
- Enforce universal and user-specific constraints.
- Return structured violations with rule ID/name, severity, prop/channel, timestamp or time range, and explanation.
- Fail generation on error-level violations. Warnings must be included in the report.
- Never silently repair a violation in a way that changes choreography.

Initial universal validators:
- No overlapping or contradictory commands on the same channel.
- Directional effects respect prop orientation; falling effects run top-to-bottom and chases follow the actual segment order.
- Multi-segment fills, wipes, and chases complete and resolve; they do not stop partway unless the music stops.
- Single-circuit multi-color props are not used for single-color moments.
- Singing-face outline is on whenever any mouth channel is on; mouth animation occurs only during detected vocals and follows syllables, not beat events.
- At a music hard-stop, motion stops with it.
- Prop activation varies by section; not every prop is active at once.

User profiles may add display-specific constraints and adjust tunables such as effect density, intensity ranges, and which props sing which vocal parts. User profiles layer over the default profile using documented merge semantics. Conflicting or invalid rules must be reported, not silently resolved.

### 5.7 `lor_writer`

**Inputs:** Validated Timeline, exact preview-derived display mapping, configured target LOR version.

**Responsibilities:**
- Serialize only validated Timeline events to the native `.loredit` schema supported by locally inspected S6 format evidence and documented structural observations. Synthetic fixtures provide regression coverage; they do not establish the native format by themselves.
- Preserve required target-version metadata and references needed by LOR.
- Never invent or reassign channel/controller/prop identifiers.
- Never contain musical analysis or choreography policy.
- Refuse unsupported target versions or unsupported effects/channel constructs.
- Write to a new output path and verify the resulting file is well-formed and structurally valid.

The exact `.loredit` schema is not to be inferred from memory. The implementation's existing format observations and synthetic regression tests are not a substitute for new S6-generated evidence when adding unsupported structures. Request the minimum necessary owner-run export, inspect it locally, and do not commit owner sequence material; retain only synthetic regression cases and documented, non-sensitive format requirements.

### 5.9 Phase 3 walking-skeleton orchestrator

**Inputs:** Required standalone `.lorprev`, matching native S6 v15 `.loredit` template, integer fixed BPM, pulse duration.

**Responsibilities:**
- Require exact prop-ID set equality, semantic equality of every complete `PropClass` subtree (all attributes, master-prop references, shapes, and geometry), and semantic equality of all `PropGroup` records (member references and arrangement). Numeric geometry/layout coordinates may differ only by 1e-6 to tolerate export formatting. Never remap IDs based on names or order.
- The independent integration fixture derives its standalone preview from the template's embedded PreviewClass. Edit revision values may differ between a standalone preview and a sequence's embedded copy and are ignored; physical display content must match.
- Support only `DeviceType=LOR` with `TraditionalType=Single Color`, `Multicolor_string_1_ch`, or `Channel_per_color`, complete LOR ChannelGrid addresses, and matching native channel records.
- Exclude unsupported device/prop types and any prop without a provable native mapping explicitly in Timeline JSON. A missing SeqProp, incomplete address, ChannelGrid/native-channel count mismatch, or unverified coordinate pattern is a per-prop exclusion with a reason; no event is generated for it.
- AC/DC values remain recognized by the preview parser for legacy compatibility but are explicitly excluded from Phase 3 because their native mapping has not been verified.
- Map each ChannelGrid entry to the native channel at the same index only when the entry count matches the channel count and the native coordinates match a verified S6 v15 pattern: row 0 + sequential col for Single Color/Multicolor_string_1_ch; row 0 + col 0 + sequential color for Channel_per_color. Carry network, Unit ID, circuit, preview index, and native row/col/color into every Timeline channel reference.
- Generate deterministic integer-centisecond beat positions from an explicitly supplied integer BPM (30–300); no audio analysis or tempo inference occurs in this phase. Bound allocation to 50,000 beats and 250,000 events before event materialization.
- Replace prior effects in the in-memory template copy with short `INTENSITY` pulses at each beat for every supported native channel.
- Validate Timeline prop/channel references and event bounds before serialization; re-read the generated LOREDIT before publishing outputs.
- Write a versioned Timeline JSON with SHA-256 fingerprints of the validated parsed XML trees, BPM, beat positions, supported/excluded props, and event references.

This is a temporary engineering harness, not the final user workflow. It requires a compatible S6 sequence template because the current writer preserves a verified native v15 document rather than constructing a blank sequence. Phase 4b replaces this: the writer will build a new native sequence from the preview alone, and a template will not be a user input (owner decision, 2026-11-11). The standalone preview is not merged into the template: it is compared in full and must already describe the same prop geometry and group layout. Existing effects in the template copy are intentionally cleared and replaced by the generated pulses. The owner must open and play the output in S6 and confirm that the expected physical lights respond; automated checks do not satisfy this human gate.

### 5.8 `report`

**Inputs:** Input metadata, classifications, audio analysis, Timeline, rule results, writer/verification results.

**Output:** Human-readable report and machine-readable report data containing:
- Inputs and detected format/application versions.
- Props classified, confidence, and items needing review.
- Props/channels used and unused, with reasons where known.
- Unsupported or unhandled prop/channel types.
- Musical analysis limitations and low-confidence detections.
- Rules passed, warnings, and violations.
- Output file and Timeline JSON paths.
- What has been verified by automated tests versus what still requires opening/testing in the target LOR application and on the physical display.

## 6. Domain models and artifact contracts

Use frozen dataclasses with explicit validation for current internal stage models. Rule profiles, the first user-edited configuration, are validated by explicit code rather than Pydantic. Initial model families:

- `InputManifest`: paths, file metadata, hashes, detected formats, configured target version, and resource limits.
- `RawDisplayModel`, `RawPropModel`, `RawChannelModel`, `RawControllerModel`: faithful preview-derived structures and source identifiers.
- `PropClassification`: inferred role, confidence, evidence, review status and notes, row position, direction, segment order, color capability, sequencing support, and master link.
- `AudioAnalysisModel`: tempo, beats, downbeats, onsets, sections, energy curve, hard stops, vocal regions, and syllable events.
- `RuleProfile`: versioned rule IDs, constraints, and tunables.
- `Timeline`: versioned timebase, source references, musical sections, and channel/prop events. Phase 3 serializes an immutable dataclass Timeline with schema version, source fingerprints, fixed BPM, centisecond beat positions, supported/excluded props, and native channel references.
- `GenerationReport`: used/unused entities, unsupported features, validation results, and verification status.

### Timeline requirements

- JSON serialization is deterministic and versioned.
- All event timestamps use one documented timebase and precision.
- Every event references a known preview-derived prop/channel identity.
- Timeline contains no raw LOR XML; the writer owns that translation.
- Timeline JSON is saved next to the generated sequence.
- Invalid or unresolvable references are rejected before serialization.

### Classification report requirements

- Versioned JSON; stable preview prop IDs are the identity keys and names are labels.
- Every conclusion carries its evidence (role, weight, reason) and any review notes.
- Unknown and unsupported props are listed explicitly, never omitted.
- The report is an output for review, not an input. Corrections are made in the preview.
- Reject stale or mismatched maps when preview identity/fingerprint does not match, unless the user explicitly re-runs analysis or approves a documented migration.

## 7. Rules profile configuration

Files:
- `src/lor_sequence_builder/rules/default.yaml`: universal rules and default tunables, shipped inside the package.
- `examples/rules-sample-a.yaml` and `examples/rules-sample-b.yaml`: illustrative user profiles, clearly labeled examples and not tied to any specific real display.

CLI selection:
- Default profile is always loaded.
- `--rules my-display.yaml` layers a user profile over defaults; repeat it to stack profiles, later wins.
- Profiles are validated by explicit code (not Pydantic): see docs/RULES.md for every key.
- Merge behavior is explicit: rule IDs override by ID; tunables use documented key-level overrides; invalid/unknown keys fail validation.
- The effective merged profile is recorded in the report for reproducibility.

## 8. CLI contract

Proposed command shape:

```text
lor-sequence-builder analyze-preview display.lorprev --report display.analysis.json

lor-auto-sequencer generate \
  --audio song.mp3 \
  --preview display.lorprev \
  --output generated.loredit \
  --timeline-output generated.timeline.json \
  --report generated.report.json \
  --lor-version 6.6.0.12 \
  --rules my-display.yaml
```

Names and option defaults are proposals pending approval. Both commands require a preview, which is the only display input. The target LOR version is configurable; detection of preview revision and selection of target application version are separate concerns.

## 9. Compatibility and fixture policy

S6-generated samples inspected locally and their documented structural observations are the format evidence. Synthetic fixtures provide repeatable regression coverage; they are not native-format authority and must not be presented as sanitized owner data.

- Keep only fictional, hand-authored or runtime-generated synthetic `.lorprev` and `.loredit` fixtures under `tests/fixtures/`.
- Never commit original or sanitized owner/customer previews, sequences, audio, local media paths, personal metadata, or private preview/background assets.
- Create synthetic preview fixtures covering materially different structures, groups/shapes, and supported channel types without copying owner/customer identifiers or content.
- For each fixture, maintain expected parser behavior, prop classification, and channel provenance.
- Include synthetic sequence fixtures for each supported output construct and target-version family.
- Add regression tests for parsing/classification and semantic round trips. Tests must compare meaning (props, channel references, timing, effect types/settings, and relevant metadata), not XML whitespace or attribute ordering.
- Automated structural validation is necessary but not sufficient. Each supported writer/version combination also requires opening the generated file in the target LOR application. Record that manual verification in the release/test report.

The initial format investigation used local S6 exports that are not retained in the repository. Additional format claims require targeted S6-generated evidence reviewed locally; retain only synthetic regression cases and non-sensitive structural observations.

## 10. V1 channel support and declared limitation

V1 currently implements and tests the following non-pixel channel types. Synthetic fixtures exercise these behaviors but do not establish how common they are across LOR displays:

- Single-color AC/DC channels.
- Multi-color props whose colors share a single circuit, with correct handling so they are not treated as independent single-color channels.

**RGB/pixel props are outside the initial V1 implementation target.** The architecture should leave a typed extension point for them, but V1 must not emit pixel choreography or pretend to support pixel data. If a preview includes RGB/pixel props, they must be explicitly listed as unsupported in analysis and the generation report. Generation must fail if the requested sequence would require unsupported pixel channels or if excluding them would violate the no-silent-drop requirement. Adding pixel support later requires dedicated preview/sequence fixtures and target-LOR verification.

Any other unsupported channel or effect type follows the same explicit-report-and-fail policy where safe output cannot be guaranteed.

## 11. Security and reliability

- No secrets in source; environment variables for any future credentials; `.env` remains gitignored.
- Parse XML with `defusedxml`; no external entities.
- Enforce file-size, XML nesting-depth, XML element-count, audio-duration, decompression, and processing limits. The Phase 2 preview parser currently applies a 20 MiB file limit, 256-level nesting limit, and 100,000-element limit.
- Validate extension and content/magic bytes; extension alone is not trusted.
- Load YAML only with a safe loader (no object construction, duplicate keys rejected), then validate every key strictly.
- Invoke FFmpeg with argument arrays, no shell, controlled environment, timeouts, and bounded output paths.
- Treat names, metadata, and paths inside input files as untrusted; never use them directly as output paths or shell arguments.
- Never commit audio files; tests use short synthetic tones.
- Pin Python dependencies in `uv.lock`; run `pip-audit` or a compatible lock-aware audit in CI.
- CI uses least-privilege permissions and third-party GitHub Actions pinned to full commit SHAs.
- Never use `pull_request_target` to execute untrusted PR code.
- Never overwrite source inputs; use atomic writes for generated outputs.
- Keep original files and fixture sources outside generated directories.

## 12. Observability and failure behavior

Errors should identify the stage, input, and corrective action without dumping sensitive file contents. Examples:
- Preview missing/unreadable/empty: stop before classification or generation.
- Unsupported preview structure: report the construct, its locator, and why it cannot be interpreted safely.
- Preview has zero props: stop with a clear error.
- Prop classification uncertain: produce a review flag and evidence; do not silently assume.
- Unsupported channel type: list prop/channel identity and reason.
- Invalid/stale props map: stop and ask for re-analysis or explicit correction.
- Rules violation: name rule, prop/channel, timestamp, and conflicting events.
- Unsupported LOR target version or writer feature: stop before writing.
- Output exists or aliases an input: refuse to overwrite.
- Audio feature unavailable: report degraded analysis; never fabricate vocal syllables or section certainty.

## 13. Explicitly out of scope for V1

- GUI.
- Uploading sequences to controllers.
- Live playback/control.
- Editing existing sequence files.
- RGB/pixel choreography implementation (declared limitation; unsupported inputs are reported).
- Cloud processing or account integration.

## 14. Open technical questions to resolve during fixture-led phases

These are implementation questions, not permission to guess:
- Which S6 application versions and LOREDIT `saveFileVersion` values will be officially supported?
- Which exact `.loredit` elements/attributes are required for each supported channel/effect type?
- How are timing grids, event boundaries, effect settings, and sequence references represented across supported versions?
- Which preview properties encode physical segment order and orientation reliably beyond `StartLocation`?
- Which common channel types/effects are not yet represented by any committed fixture?
- What resource limits are appropriate for expected song lengths and preview sizes?

Resolve these through additional fixtures, targeted questions, and tests before implementation depends on the answer.


## 15. Delivery order and engineering controls

The implementation sequence is governed by `docs/PLAN.md`. The highest-risk unknown is native LOR sequence compatibility, so the project proves read/write/semantic round-trip and owner-open verification before preview parsing or intelligent audio/choreography work.

The delivery order is:
0. Scaffold and CI.
1. Native LOR sequence format reader/writer, with owner opening the rewritten file in LOR.
2. `.lorprev` preview parser.
3. Walking skeleton: fixed-tempo pulse Timeline through the writer, with owner playback verification in LOR.
4. Audio analysis.
5. Prop classifier and `analyze-preview`.
6. Rules engine.
7. Section-aware planner v1, with owner playback verification.
8. Vocal separation and syllable-level singing-face choreography, with owner playback verification.
9. Planner v2 (motifs, call-and-response, signature moments, dynamics).
10. Polish, reporting, documentation, and packaging.

Every phase is one GitHub Issue, one branch, and one PR. The issue is the acceptance contract. The PR must contain only work for that phase. A phase is complete only after its tests and CI pass, required human verification is recorded, the PR is merged, and the owner approves the next phase. Keep the progress log in `docs/PLAN.md` current so a fresh session can resume without relying on chat history.

**Human verification is not delegated to automated tests.** For designated gates, the owner must open and/or play the output in the target LOR application. The assistant must never claim to have performed that local verification.


## 16. Phase 0 scaffold boundary

The Phase 0 repository is intentionally a minimal Python 3.12 package with a CLI entry point that only displays help. No LOR parsing, sequence serialization, preview interpretation, audio processing, prop classification, or choreography belongs in the scaffold. Those capabilities are introduced only in their ordered phases in `PLAN.md`.

The scaffold uses `uv` and a committed `uv.lock`. CI uses Python 3.12, pytest, Ruff, strict mypy, and dependency auditing. Third-party GitHub Actions are pinned to full commit SHAs, and workflow permissions are explicitly read-only except for the CodeQL analysis job's required security-events permission.

The intended source layout is:

```text
src/lor_sequence_builder/
  __init__.py
  cli.py
tests/
  test_cli.py
docs/
  ARCHITECTURE.md
  PLAN.md
.github/
  workflows/
    tests.yml
    codeql.yml
```

No phase-specific implementation is considered complete merely because a scaffold command or CI check succeeds. The LOR format remains the first implementation risk and is addressed only after Phase 0 is merged and approved.


## Phase 4 implementation boundary

The analyzer is implemented in `audio_analysis.py` and exposed as `analyze-audio`. FFmpeg is the only decoder: it normalizes the first audio stream to mono 22.05 kHz signed 16-bit PCM, and librosa analyzes the resulting sample array. Inputs are limited to 200 MiB and 30 minutes; clips shorter than two seconds are rejected.

- **Tempo and beats:** librosa global tempo seeds the dynamic-programming beat tracker; beats without a nearby transient (lead-in or trailing silence) are dropped; tempo is a least-squares fit across all beats to cancel frame quantization. Tempo confidence is the share of local tempo estimates agreeing with the result (or its half/double); beat confidence compares onset strength on beats against midpoints.
- **Beat-synchronous features:** `_beat_sync` keeps column *i* equal to beat *i* (librosa adds a leading column when the first beat is not frame 0) and closes the last beat after one period.
- **Downbeats:** four beats per bar; the bar position with the highest median harmonic (chroma) change wins. With fewer than four bars or a margin below 0.1, the first beat is used and confidence reports the weak evidence.
- **Sections:** checkerboard novelty on a beat-level self-similarity matrix (chroma plus MFCC) plus loudness change, evaluated only at downbeats, local peaks at least four bars apart. Broad energy transitions are added when no structural candidate is nearby. No labels are inferred.
- **Evaluation:** `evaluation.py` and `evaluate-analysis` score a report against named free timing grids in a sequence opened read only through the LOREDIT reader (70 ms for beats and bars, 2 s for sections).

The machine-readable contract is `docs/schemas/audio-analysis-v2.schema.json`; v1 remains for the historical baseline. Changes to report structure must increment the schema version and update the contract and the contract test together.
