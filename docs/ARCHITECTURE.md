# Architecture

**Status:** Phase 2 — preview parser for standalone and embedded PreviewClass data in progress; later-stage contracts are planned below  
**Project:** Light-O-Rama Sequence Builder  
**V1 interface:** Command line  
**Target output:** Native Light-O-Rama S6 `.loredit` sequence  
**Required display input:** Light-O-Rama `.lorprev` preview

## 1. Purpose and scope

LOR Auto-Sequencer accepts an audio file and the display's required `.lorprev` file, then creates a new native LOR sequence choreographed to the music. It is intended to work with different LOR displays without embedding any particular user's prop names, channel numbers, controller assignments, layout, or naming conventions in code.

The workflow has two explicit commands:

1. `analyze` reads and validates the audio and preview, extracts the display model, classifies its props, and writes a human-editable `props.yaml`.
2. The user reviews and may correct `props.yaml`. `generate` reads the same required inputs and reviewed map, analyzes the music, plans choreography, validates the resulting Timeline, and writes a new `.loredit` file plus the Timeline JSON and a report.

The original audio, preview, prop map, and any reference sequence are read-only inputs. Output paths must be new paths; the tool must refuse to overwrite an input or an existing output unless a future explicit and separately approved policy says otherwise. V1 does not edit existing sequences.

## 2. Confirmed project decisions

- The display preview input is **`.lorprev`** and is mandatory for both `analyze` and `generate`.
- The generated sequence output is **`.loredit`**, intended to open in the configured target LOR S6 version.
- The committed standalone preview golden fixture is a sanitized fictional S6 export with internal `Revision="1"`. A second sanitized golden fixture is extracted from the `PreviewClass` embedded in the supplied `fixture_candidate.loredit` (S6 6.6.0.12); it has internal `Revision="56"`, 51 props, and one `PropGroup` containing five prop references. These preview revisions are distinct from the LOREDIT save-file version. The original private owner preview is not committed.
- The supplied Merry Christmas `.loredit` is an example sequence from the user's actual setup and is a sequence-format reference associated with that setup.
- The user's display does **not** use pixel props. RGB/pixel support is therefore a declared V1 limitation, not something to fake or infer. If a preview contains a channel/prop type the current writer cannot safely represent, the tool must report it and must not silently drop it or claim full support.
- V1 is CLI-only. GUI, controller upload, live playback, and editing existing sequences are out of scope.

## 3. Design principles

1. **Preview is authoritative for the display.** Every emitted prop, controller, channel, and channel assignment must trace to the parsed preview or an explicit user prop-map override that corrects physical interpretation. No generated or guessed channels.
2. **No preview, no sequence.** Missing, unreadable, malformed, unsupported-version, oversized, or zero-prop previews are fatal errors with actionable messages.
3. **Names are evidence, not identity.** Classification combines prop type, shape, grouping, position, channel count, color capability, and name hints. Names alone never determine a role.
4. **Unknowns remain visible.** Unknown roles, unsupported channel types, uncertain orientation, and low-confidence classifications are surfaced in `props.yaml` and the final report.
5. **Music drives the arrangement.** Choreography is planned around song structure, phrasing, dynamics, instrumentation, vocals, transitions, and intentional contrast—not just beat flashes.
6. **One intermediate truth.** The Timeline JSON is the sole choreography representation consumed by validation and serialization.
7. **Rules are configuration.** Universal rules ship in `rules/default.yaml`; user profiles layer on top without modifying application code.
8. **The writer does not choreograph.** `lor_writer` serializes a validated Timeline into the exact supported LOR format.
9. **Inputs are immutable and untrusted.** Parsing is hardened, resource limits are explicit, and output is always written separately.
10. **Format claims require fixtures.** Real `.lorprev` and `.loredit` fixtures plus opening the result in the target LOR application—not remembered or guessed schemas—establish compatibility.

## 4. High-level data flow

```text
analyze
  audio + required .lorprev
       |
     ingest
       |
  preview_parser ----> RawDisplay / RawProp models
       |
  prop_classifier ---> Classified props + confidence
       |
  props.yaml <-------- human review / physical overrides

generate
  audio + required .lorprev + reviewed props.yaml
       |
     ingest
       |--------------------------|
  preview_parser             audio_analysis
       |                          |
  prop_classifier <--- reviewed overrides
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

Every stage has typed Pydantic inputs and outputs. A stage may use the public models of another stage, but it must not reach into that stage's implementation internals. Stage orchestration belongs in the application/CLI layer.

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
- Identify the root/schema family and preview format revision before interpreting fields.
- Parse into raw, loss-minimizing typed models: display metadata, props, prop IDs, groups, geometry/position, shape/grid, channel count and assignments, device/controller references, color/channel capability, and any other relevant metadata present in the preview.
- Preserve source identifiers and provenance for every channel and prop.
- Fail clearly on unsupported preview revisions rather than best-effort parsing that could corrupt assignments.
- Treat names and descriptive metadata as untrusted text.

**Outputs:** `RawDisplayModel` and `RawPropModel[]`.

**Known preview references:** Revision 0 is covered by a small synthetic fixture; Revision 1 by the supplied standalone `.lorprev`; Revision 56 by the `PreviewClass` extracted from the supplied S6 6.6.0.12 `.loredit`. The Revision 56 fixture contains 51 props and a real `PropGroup` with five `member` references. These internal preview revisions are distinct from the LOREDIT `saveFileVersion` and S6 application build.

**Controller/channel interpretation:** Each LOR prop `ChannelGrid` row exposes network, Unit ID, and the circuit value present in that row; each DMX row exposes universe and channel. These are address fields, not a complete interpretation of every field or channel-range behavior. Remaining row fields are retained verbatim and are not yet semantically interpreted. The parser retains the complete original value and source locator. `Undetermined` is a recognized unassigned device type. Later phases must not infer channel counts, ranges, color semantics, or controller capabilities from unparsed fields.

**Group interpretation:** A direct `PropGroup` contains direct `member` elements. The parser exposes group ID, name, arrangement, ordered member prop IDs, orientation, top, and left values. It validates that each referenced member ID resolves to a prop in the same preview; missing or dangling references are preserved and reported as unsupported constructs. Raw group/member elements and per-attribute provenance remain available.

### 5.3 `prop_classifier`

**Input:** Raw preview models and optional existing user prop map.

**Responsibilities:**
- Infer roles such as arch, mini tree, mega tree, singing face, snowflake, outline, matrix, and star.
- Use a weighted/evidence-based combination of prop type, shape, geometry, grouping, position, channel count, color capability, and name hints. No name-only classification.
- Infer orientation/direction and segment order only where preview evidence supports it.
- Determine color capability, including single-color AC/DC channels and multi-color channels on one circuit.
- Assign an explainable confidence score and retain evidence/reasons for each inference.
- Mark low-confidence, ambiguous, and unsupported props for review. Unknown is a valid classification outcome.
- Never manufacture a channel, controller, prop, or assignment.

**Output:** Classified prop models and editable `props.yaml`.

The YAML must preserve stable preview identifiers and distinguish inferred values from user overrides. It must include at least role, orientation/direction, segment order, color capability, confidence, classification evidence, review status, and override fields. Physical corrections (for example, wrong colors or reversed segment order) override inferred preview interpretation. Overrides may correct interpretation, but cannot silently create new physical channels or change channel identity.

### 5.4 `audio_analysis`

**Input:** Normalized audio.

**Responsibilities:**
- Estimate tempo, beats, downbeats, onsets/transients, phrase/section boundaries, energy, and hard stops.
- Estimate intro, verse, chorus, bridge, and outro sections with confidence/evidence; do not represent uncertain section labels as facts.
- Support vocal stem separation and vocal syllable-onset detection for singing-face choreography.
- Keep beat, downbeat, onset, vocal, and section events as distinct concepts. Mouth animation follows detected vocal syllables, not the beat.
- Report unavailable or low-confidence analysis rather than inventing events.

**Implementation notes:** Librosa is the initial analysis foundation. Demucs may be used for vocal separation. Madmom is an alternative only if its Python/runtime compatibility and maintenance are validated. Vocal separation and syllable detection are computationally expensive and must have explicit dependency, runtime, and failure behavior. If vocal analysis is unavailable, singing-face mouth animation must be disabled or flagged for user review; it must not fall back to beat-driven mouth movement.

**Output:** Typed musical feature models with timestamps, confidence, and provenance.

### 5.5 `planner`

**Inputs:** Classified display/props, musical features, reviewed prop map, active rules/tunables.

**Responsibilities:**
- Identify musical sections and phrases and assign choreography roles by section.
- Plan purposeful contrast, repetition with variation, transitions, accents, holds, fades, coordinated groups, and selective prop activation.
- Respect each prop's role, orientation, direction, segment order, color capability, and physical overrides.
- Use singing faces only in detected vocal regions and align mouth events to syllable onsets when available.
- Stop motion at hard musical stops and resolve multi-segment movements.
- Avoid activating every prop simultaneously; create dynamic contrast across sections.
- Generate decisions as data, not LOR XML.

**Output:** A typed `Timeline` model. This is the only source of truth for all choreography.

### 5.6 `rules_engine`

**Inputs:** Timeline, display/prop model, active rules profile.

**Responsibilities:**
- Load YAML profiles with `yaml.safe_load`.
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
- Serialize only validated Timeline events to the native `.loredit` schema demonstrated by committed, sanitized fixtures.
- Preserve required target-version metadata and references needed by LOR.
- Never invent or reassign channel/controller/prop identifiers.
- Never contain musical analysis or choreography policy.
- Refuse unsupported target versions or unsupported effects/channel constructs.
- Write to a new output path and verify the resulting file is well-formed and structurally valid.

The exact `.loredit` schema is not to be inferred from memory. The supplied real sequence is a starting reference; additional sanitized fixtures and round-trip tests must establish the structures needed for each supported feature.

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

Use Pydantic models for public stage boundaries. Initial model families:

- `InputManifest`: paths, file metadata, hashes, detected formats, configured target version, and resource limits.
- `RawDisplayModel`, `RawPropModel`, `RawChannelModel`, `RawControllerModel`: faithful preview-derived structures and source identifiers.
- `ClassifiedPropModel`: inferred role, orientation, segment order, color capability, confidence, evidence, review status, and overrides.
- `AudioAnalysisModel`: tempo, beats, downbeats, onsets, sections, energy curve, hard stops, vocal regions, and syllable events.
- `RuleProfile`: versioned rule IDs, constraints, and tunables.
- `Timeline`: versioned timebase, source references, musical sections, and channel/prop events.
- `GenerationReport`: used/unused entities, unsupported features, validation results, and verification status.

### Timeline requirements

- JSON serialization is deterministic and versioned.
- All event timestamps use one documented timebase and precision.
- Every event references a known preview-derived prop/channel identity.
- Timeline contains no raw LOR XML; the writer owns that translation.
- Timeline JSON is saved next to the generated sequence.
- Invalid or unresolvable references are rejected before serialization.

### `props.yaml` requirements

- Human-editable, documented, versioned YAML.
- Stable preview IDs are the identity keys; names are labels, not keys.
- Clearly separate inferred values, confidence/evidence, review flags, and user overrides.
- Explicitly represent unknown/unsupported types.
- Validate all references against the current preview before generation.
- Reject stale or mismatched maps when preview identity/fingerprint does not match, unless the user explicitly re-runs analysis or approves a documented migration.

## 7. Rules profile configuration

Files:
- `rules/default.yaml`: universal rules and default tunables.
- `examples/rules-sample-a.yaml` and `examples/rules-sample-b.yaml`: illustrative user profiles, clearly labeled examples and not tied to the user's actual display.

CLI selection:
- Default profile is always loaded.
- `--rules my-display.yaml` layers a user profile over defaults.
- Merge behavior is explicit: rule IDs override by ID; tunables use documented key-level overrides; invalid/unknown keys fail validation.
- The effective merged profile is recorded in the report for reproducibility.

## 8. CLI contract

Proposed command shape:

```text
lor-auto-sequencer analyze \
  --audio song.mp3 \
  --preview display.lorprev \
  --props-out props.yaml

lor-auto-sequencer generate \
  --audio song.mp3 \
  --preview display.lorprev \
  --props props.yaml \
  --output generated.loredit \
  --timeline-output generated.timeline.json \
  --report generated.report.json \
  --lor-version 6.6.0.12 \
  --rules my-display.yaml
```

Names and option defaults are proposals pending approval. Both commands require a preview. `generate` also requires a valid reviewed prop map. The target LOR version is configurable; detection of preview revision and selection of target application version are separate concerns.

## 9. Compatibility and fixture policy

The test fixtures are the format authority. Never guess schemas from memory or extrapolate compatibility from one file.

- Keep sanitized `.lorprev` and `.loredit` fixtures under `tests/fixtures/`.
- Never commit the user's original display preview, original sequences, audio, local media paths, personal metadata, or private preview/background assets.
- Create multiple preview fixtures covering materially different file sizes, naming styles, groups/shapes, and supported channel types.
- For each fixture, maintain expected prop classification and channel provenance.
- Include sequence fixtures for each supported output construct and target-version family.
- Add golden-file tests for parsing/classification and semantic round-trip tests.
- A round-trip test must compare meaning (props, channel references, timing, effect types/settings, and relevant metadata), not XML whitespace or attribute ordering.
- Automated structural validation is necessary but not sufficient. Each supported writer/version combination also requires opening the generated file in the target LOR application. Record that manual verification in the release/test report.

The currently supplied preview and sequence establish an initial real-world reference pair. Additional sanitized fixtures are needed before claiming broad display compatibility.

## 10. V1 channel support and declared limitation

V1 will prioritize the channel types actually present in the user's display and confirmed by fixtures:

- Single-color AC/DC channels.
- Multi-color props whose colors share a single circuit, with correct handling so they are not treated as independent single-color channels.

**RGB/pixel props are not used by the user's display and are outside the initial V1 implementation target.** The architecture should leave a typed extension point for them, but V1 must not emit pixel choreography or pretend to support pixel data. If a preview includes RGB/pixel props, they must be explicitly listed as unsupported in analysis and the generation report. Generation must fail if the requested sequence would require unsupported pixel channels or if excluding them would violate the user's no-silent-drop requirement. Adding pixel support later requires dedicated preview/sequence fixtures and target-LOR verification.

Any other unsupported channel or effect type follows the same explicit-report-and-fail policy where safe output cannot be guaranteed.

## 11. Security and reliability

- No secrets in source; environment variables for any future credentials; `.env` remains gitignored.
- Parse XML with `defusedxml`; no external entities.
- Enforce file-size, XML nesting-depth, XML element-count, audio-duration, decompression, and processing limits. The Phase 2 preview parser currently applies a 20 MiB file limit, 256-level nesting limit, and 100,000-element limit.
- Validate extension and content/magic bytes; extension alone is not trusted.
- Load YAML only with `safe_load`, then validate against strict Pydantic schemas.
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
- Unsupported preview revision: report detected revision and supported revisions.
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
- Which `.lorprev` revisions and S6 application versions will be officially supported?
- Which exact `.loredit` elements/attributes are required for each supported channel/effect type?
- How are timing grids, event boundaries, effect settings, and sequence references represented across supported versions?
- Which preview properties encode physical segment order/orientation reliably, and which require user overrides?
- Which channel types/effects are present in the user's display but not yet represented by the supplied fixture pair?
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
5. Prop classifier and `analyze` / `props.yaml`.
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
