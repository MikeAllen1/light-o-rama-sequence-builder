# Implementation Plan

**Status:** Phases 0 through 6b are complete. Phase 7 planner code is merged, with the owner S6 playback gate still pending. Phase 8 vocal analysis remains in PR #44. Phase 11A browser workspace is owner-authorized and in progress on a separate branch.
**Current phase:** Phase 11A — Browser-first professional sequencing workspace (Issue #47; branch `ui/browser-sequencer-foundation`).
**Parallel engine status:** Phase 8 remains in PR #44, still based on `phase-7/planner-v1`; do not assume its real-vocal or owner playback gates are complete.
**Delivery boundary:** The browser is the development interface. Desktop packaging remains deferred until the final stage.

## Product objective and fixed requirements

Build a display-independent Python engine and CLI that accept audio plus a required Light-O-Rama .lorprev preview and produce a new native S6 .loredit sequence. Add a browser-based sequencing workspace that opens real S6 sequences and matching audio on a shared, musically aligned timeline. The browser workspace is the development interface; desktop packaging is deferred until the final stage. Timeline JSON remains the single source of truth for generated choreography.

- Preview is mandatory for analyze and generate. Missing, unreadable, malformed, unsupported-version, or zero-prop previews fail clearly.
- Props, controllers, and channels must originate from the preview. Never invent or silently reassign them.
- Classification combines prop type, shape, grouping, position, channel count, color, and name hints; never names alone.
- Product target includes legacy AC/DC single-color and LOR multi-color/single-circuit props. Phase 3 is intentionally narrower: it generates only verified `DeviceType=LOR` mappings for `Single Color`, `Multicolor_string_1_ch`, and `Channel_per_color`. AC/DC remains parseable but excluded until its native S6 channel mapping is independently verified; see the Phase 3 boundary in ARCHITECTURE.md.
- RGB/pixel is outside v1. Detect and report unsupported pixel props; never silently drop or fake support.
- The preview is the only display input (owner decision, 2026-11-11). There is no separate prop map: the tool reads the preview the way a person would, and corrections are made in the S6 Preview Editor.
- Rules are configuration; invalid Timelines fail with readable rule, prop/channel, and timestamp details.
- Never modify/overwrite inputs. Output is a new file.
- The browser workspace is in scope; desktop wrappers and packaging are deferred to the final stage. Controller upload and live hardware playback remain out of scope. The first browser workspace is read-only; editing and writing existing sequences are subsequent phases.
- Python 3.12, uv + committed lockfile, Pydantic, Typer, pytest, Ruff, strict mypy.
- XML via defusedxml; YAML safe_load; FFmpeg argument list, never shell=True; input size/type/duration limits.
- No secrets in code; .env gitignored; pin dependencies and run pip-audit.
- CI uses least privilege and third-party Actions pinned to full commit SHAs. Never use pull_request_target to execute untrusted PR code.
- Synthetic audio tests only; never commit copyrighted audio.

## Recorded stack deviations

These differ from the original stack proposal. They are intentional and accepted unless the owner reopens them:

- **Models:** frozen `dataclasses` are used for stage models instead of Pydantic. Pydantic remains the expected choice for user-edited inputs (rules profiles) where schema validation and error messages matter; adopt it in the phase that first parses those files.
- **CLI:** `argparse` is used instead of Typer. Acceptable for v1; revisit only if CLI complexity grows.
- **Audio (reversed 2026-11-11):** the stdlib-only baseline was replaced by librosa after real-song review showed its beat placement was near chance. librosa analyzes FFmpeg-decoded samples only; FFmpeg remains the only decoder. Demucs or similar is still expected for Phase 8 vocals and must be recorded here when added.

## Open decisions (owner input required before the phase that depends on them)

1. **Sequence creation without a template (resolved 2026-11-11).** Owner chose to build sequences from scratch: `generate` takes audio and preview only, and the tool creates a new native sequence itself. A template is not a required input. This becomes Phase 4b, scheduled after Phase 4 acceptance and before Phase 5 because it is the largest remaining format unknown.
2. **Preview Revision (resolved 2026-11-11).** Owner clarified that `PreviewClass/@Revision` is an edit counter incremented on each save, not a format version. The parser's revision allowlist (which rejected any preview not at revision 0, 1, 56, or 58) was removed; the value is now optional metadata. Compatibility is judged by structure. Do not reintroduce revision-based gating.
3. **Fixture diversity before Phase 5 (resolved for Phase 5 acceptance, 2026-11-11).** Phase 5 passed its five fictional-display regression suite and the owner confirmed the classifier conclusions against a real display locally. The real display and all derivatives remain private and are not committed. This records the Phase 5 acceptance evidence; it does not claim broad validation across every display or legacy AC/DC configuration.
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
**Status: Complete. Accepted by the owner on 2026-11-11** after the librosa rework (PR #17). The original baseline (PR #9) failed real-song review; its history follows. PR #9 was squash-merged into `master` as `2b962bd39d51b052c3f97d76876a29176dc627ae` after all required CI checks passed on final head `36a98f824dcd883d032b3a49240aa8957f20d91e`.

Delivered: bounded FFmpeg normalization; deterministic RMS/positive-energy-flux/autocorrelation analysis; tempo, beat and provisional downbeat candidates; onsets; energy curve; fixed 16-beat phrase candidates; energy-transition candidates; sustained near-silence candidates including leading silence; versioned JSON and formal v1.0 JSON Schema; SVG diagnostic plot; CLI confidence reporting; Linux and Windows tests; CodeQL.

Final-head CI: Tests workflow run `42956005759` passed both Linux (pytest, Ruff, strict mypy, pip-audit) and Windows compatibility jobs. Phase 3 Validation Package run `42956005713` passed. CodeQL run `42956005698` passed. The final hard-stop timestamp test uses a tolerance consistent with the 551-sample frame duration (~49.977 ms), rather than asserting a mathematically exact 3.000-second frame boundary.

**Historical baseline note:** The original stdlib implementation did not satisfy real-song review and was superseded by the librosa rework in PR #17. The unresolved review items from that baseline are historical, not current blockers. The reworked analyzer was accepted by the owner on 2026-11-11; its known swung/rubato limitation is recorded below and is addressed as a Phase 8 planning concern.

**Real-song review (2026-11-11):** the stdlib baseline was scored against owner-made timing grids on several songs and failed (beat placement near chance). The librosa rework (PR #17) was scored the same way. Per-song results, song identities, and measurements are kept private and are not recorded in this repository.

**Rework (PR #17):** librosa beat tracking with transient-supported beats and regression tempo; downbeats from beat-synchronous harmonic change with a weak-evidence fallback and a `--beats-per-bar` option (3 or 4; meter is not detected); structural section candidates from self-similarity plus loudness change at bar starts; `evaluate-analysis` command scoring analyses against grids in a user's own sequences; schema v2.0.

**Acceptance (owner, 2026-11-11):** accepted for songs in 4, which met the beat and bar targets below. Known limitation: swung or rubato recordings, where the band follows the singer's phrasing, score lower on beats and have unreliable bars. Later phases must use bar confidence and allow a reviewed bar offset or meter override rather than trusting downbeats blindly. If a hand-made bar grid scores near zero while beats score well, check it for a whole-beat offset.

**Swing investigation (before acceptance):** none of these improved swung recordings without hurting steady songs: stiffer or looser tempo tracking, drifting local tempo, percussive or bass-band onset envelopes, re-spacing weak stretches, snapping beats to nearby onsets, predominant-local-pulse beats, and a neural beat tracker (beat_this, which also added about 900 MB). In singer-led stretches, onsets alone cannot separate beats from swung notes. The planned fix is vocal-guided beat placement in Phase 8.

Review audio, sequences, and results stay local and are never committed.

**Acceptance:** The owner accepted the librosa rework on 2026-11-11 after the documented grid-scoring review. The original stdlib baseline did not pass and is retained only as historical context. Phase 4b was subsequently completed under its own S6 writer gate.

### Phase 4b — Scratch-built sequence writer
**Status: Complete. Owner S6 open-test passed on 2026-11-11.**

Build a native S6 v15 `.loredit` from a parsed `.lorprev` alone, with no template sequence: sequence metadata, embedded preview, one `SeqProp` and native channel record per supported preview channel, timing grid, duration, and audio reference. Replace the Phase 3 template requirement in `pulse` with this writer.

**Evidence used:** native S6 6.6.0.12 musical sequences examined locally; none of their content is committed. The structure is recorded in `docs/S6_FORMAT.md` under "New sequence structure". S6 cannot create a musical sequence without choosing audio, so "new empty sequence" means a new sequence with audio, saved with no edits.

**Delivered:** `new_sequence.py` builds the eleven-section skeleton, embeds the preview, creates sequence props for non-linked props in preview order with verified channel layouts, excludes and reports unverified prop types, adds the 0.05 s fixed grid and optional free timing grids, and derives a deterministic sequence id. `pulse` builds from the preview alone (`--duration-seconds`, `--music-filename`); `--template` is deprecated. Rebuilding examined sequences from their embedded previews matched every sequence prop, channel coordinate, empty section, and shared root setting. The Timeline field `template_xml_sha256` keeps its name for schema stability; without a template it fingerprints the newly built base sequence.

**Owner gate (2026-11-11):** a sequence built from a wholly fictional 8-prop display (controller units 10 and 11) with a generated 120 BPM click track opened in S6 6.6.12, imported its embedded preview, rendered all props, and played with pulses on every click across all seven sequence props. S6's load notices were only because the files were opened from inside the zip: the sequence was read-only, and the audio was not yet in place. The notice confirmed that S6 resolves `musicFilename` against the user's S6 audio folder (by default `Documents\Audio`), so `--music-filename` should be the audio file's path relative to that folder.

**Done when:** A scratch-built sequence for every committed fixture preview is semantically equal to its S6-created reference fixture (props, channel coordinates, addresses, timing, metadata); unsupported props are enumerated, never silently dropped; `pulse` works with only a preview, audio duration or explicit duration, and BPM; the template path is removed or explicitly deprecated; inputs are never modified; the owner opens a scratch-built sequence in S6, confirms it loads, the preview renders, and events appear. Mandatory human gate.

### Phase 5 — Classifier
**Status: Complete. Owner confirmed on 2026-11-11 that the conclusions on a real display match how they read it.**

Identify each prop from the preview alone: role (arch, mini tree, mega tree, star, singing face, icicles, outline, snowflake, or unknown), confidence with evidence, row position, direction, segment order, color capability, and whether v1 can sequence its channels. `analyze-preview` prints the conclusions and a review list and can write a JSON report. There is no prop map file (owner decision, 2026-11-11): the preview is the only input, and corrections are made in the S6 Preview Editor.

**Evidence:** S6 shape type and parameters (`Parm1` is the segment or strand count), geometry (center and size for parametric shapes, bounding box, arcs, closed outlines, long flat runs), channel count and `TraditionalType`, `StartLocation`, `PropGroup` membership and order, look-alike props side by side, small props drawn on top of each other as one figure (a face built from parts), and `MasterPropId` links.

**Name rule (owner decision, 2026-11-11):** when the S6 shape type is specific (Arch, Star, Tree, Icicles, snowflake) or there is real structural evidence, the name is only a tiebreaker. When the shape type is generic (plain lines) and nothing structural says otherwise, the name decides, flagged for review. A first real-display check showed most props are drawn as plain lines, so names are the only usable evidence for them.

**Fixtures:** five wholly fictional displays generated in `tests/display_builders.py` (classic yard, roofline house, misleading names, unsupported hardware, line-drawn yard), each with known roles. The owner's own display was analyzed locally at the owner's request; nothing from it is committed.

**Done when:** classifications match the known answers on all fictional displays; low-confidence and unknown props are flagged with reasons; renaming props never switches a prop to a different role; color capability and sequencing support agree with the sequence builder; the preview is never modified; the owner runs `analyze-preview` on a preview of their choice and agrees the conclusions are useful.

### Phase 6 — Rules engine
**Status: Complete. Merged 2026-11-11 (#34) on the owner's instruction.**

Build universal defaults and user profile layering.

**Delivered:** a versioned choreography Timeline (`choreography.py`, schema `choreography-1.0`: effects on preview channels, movements, sections, hard stops, vocal regions); the built-in profile `src/lor_sequence_builder/rules/default.yaml` (kept inside the package so installs ship it); profile loading and layering (`rules/profile.py`); eleven built-in rules and six requirement types (`rules/engine.py`); and a writer (`sequence_writer.py`) that runs the rules itself and writes only a report when there are errors. Commands: `list-rules`, `check-timeline`, `build-from-timeline`. Documented in `docs/RULES.md`. Example profiles: `examples/rules-sample-a.yaml`, `examples/rules-sample-b.yaml`.

**Decisions (owner, 2026-11-11):** a rule about a kind of prop applies only when the display has that prop and otherwise reports not applicable, never passed; the singing-face outline rule applies only when a face has a separate outline prop. Profiles are validated by explicit code instead of Pydantic, to avoid a dependency for one small format. PyYAML is a new runtime dependency; profiles use a safe loader that rejects duplicate keys and reads `on`/`off`/`yes`/`no` as words. The three rules that protect the file (well-formed effects, real channels, no overlaps) are locked.

**Not yet verified in S6:** fade (`startIntensity`/`endIntensity`), `TWINKLE` and `SHIMMER` effects written by `build-from-timeline`. These attributes were observed in native sequences, but no sequence written by this tool with them has been opened in S6 yet. The `pulse` harness keeps its own Phase 3 validation and does not use the rules engine.

### Phase 6b — "Any specific requirements?"
**Status: Complete. Merged 2026-11-11 (#36) on the owner's instruction.**

Owner request (2026-11-11): an optional step before building where a person can write in their requirements. Owner chose both input styles and remembered requirements.

**Delivered:** `requirements_intake.py` and the `requirements` command. Plain-English text is translated by a language model when `ANTHROPIC_API_KEY` is set (model from `LOR_REQUIREMENTS_MODEL`), after telling the person what is sent and asking to continue. Without a key, with `--guided`, or when sending is declined, guided questions are built from what the preview contains. Every translated or answered requirement is validated exactly like a hand-written profile and checked against the display's props; the person sees how each was understood, what could not be expressed, and what was left out, and nothing is saved until they confirm. Confirmed requirements are saved as `<preview>.requirements.yaml` next to the preview (git-ignored), and `check-timeline`, `build-from-timeline` and `list-rules --preview` layer it on automatically (`--ignore-saved-requirements` to skip; `build-from-timeline --ask-requirements` asks first). Later runs offer keep, add, or start fresh.

**Verified by tests:** guided questions only for props the display has; translation request contents and answer parsing with a fake transport (no network in tests); validation, confirmation, decline and fallback paths; remembering, extending and clearing; builds picking up saved requirements.

**Not verified:** a live call to the translation service. It needs the owner's API key and is optional.

### Phase 7 — Planner v1
**Status: Merged to master in PR #39; owner playback gate pending.**

Build section-aware choreography with basic effects.

**Delivered:** `planner.py` and `generate.py`, with the `generate` command (audio or an existing analysis, plus a preview). Sections come from the analyzer's section candidates (or every 8 bars when none), snapped to bar starts, with a low, mid or high energy level relative to the rest of the song and a guessed label (intro, verse, chorus, finale, outro). Hard stops split sections so motion never runs through a silence. Looks per prop kind and energy: arch rows chase every other beat, every beat, then fill each bar; mini tree rows rest, alternate, then pulse; other rows hold, chase, then fill; a mega tree (and multi-segment icicles or outlines) rotates through its segments, faster when loud; stars hold or twinkle; snowflakes rest, pulse on bars, or twinkle; outlines and decorations hold dim, hold brighter, or pulse. Chases follow the real row order in the preview and mirror direction between sections. A louder section opens with a one-beat accent. Within a section the look changes every 4-bar phrase, and each new chase or fill on a row runs the other way from the last. An intro brings props in a few kinds at a time, and the song's last bar fades everything out together. Back-to-back holds are joined into one effect. `generate` also writes `<song>.plan.svg`, a picture of the whole show for review away from S6. Requirements shape the plan directly (never-used props excluded, kept-on props held, quiet sections respected, colors and brightness limited, required chase directions). Mouths are never lit until vocal analysis exists. The plan is deterministic and must pass every rule before the writer accepts it. Next to the sequence: Timeline, plan summary, rule report, and (from audio) the analysis and plot. `generate` asks the requirements question first when run interactively without saved requirements.

**Verified by tests:** every fictional display produces a plan that passes all rules with no warnings; louder sections light more; arch chases follow preview order and mirror; nothing is lit during a hard stop; mouths stay dark; requirements change the plan; plans are deterministic; a song without beats still plans; looks change between phrases; the intro builds and the ending fades; a 57-prop, 4-minute fictional show plans and checks in well under a second; end-to-end from synthesized audio to a native sequence.

**Owner check (2026-11-11), fictional display:** the owner opened and played both sequences from the fictional test package in S6 and reported "both loredits worked fine effects seem to work fine as well". This confirms S6 reads the fade (`startIntensity`/`endIntensity`), `TWINKLE` and `SHIMMER` effects as written, and that a planned show plays.

**Owner check (2026-11-11), owner's display:** the owner played generated versions of their own songs: "They do work. I'm not sure they're "good" but they work and seem to be on beat" (one song checked). Feedback: too much is on; in the intro several beats get no reaction at all; a tambourine gets no lights. The owner most wants the planner to learn focus and handoffs. Changes in response: in each phrase only a few groups lead (two in quiet and mid sections, three in loud ones) while the rest rest against a dim base of outlines and star, and the lead passes left to right across the yard phrase by phrase; the mega tree keeps playing through mid and loud sections; the finale uses everything; every lead answers every beat even in quiet sections (the intro build-in that held props still was removed); the analysis now detects high-pitched hits (tambourine, sleigh bells, hi-hats) as `high_hits`, and where they come at least every other beat a sparkle group (snowflakes, else decorations) flashes on them.

**Owner gate (pending):** generate a real song on the owner's display, open and play it in S6, and confirm it looks intentional rather than random or beat-flashing.

**Done when:** Real song produces a Timeline and sequence passing rules; owner opens and plays it in LOR and confirms it looks intentional, not random or merely beat-flashing; effects feel integrated into the arrangement. Mandatory human gate.

### Phase 8 — Vocals
**Status: Built; owner playback gate pending.** Owner decisions (2026-11-11): accept a vocals-only file and offer built-in separation as an optional add-on; faces are built from separate props per part.

**Delivered:** `vocals.py` finds vocal regions (voice clearly present against the track's own loud level, breaths bridged, blips dropped) and syllables (onsets that follow a dip in the voice and reach a real note level, each held until the voice falls to half its peak) in a vocals-only track, and writes `<song>.vocals.json`. `vocal_separation.py` wraps the optional `audio-separator` add-on (`uv sync --extra vocals`) with the UVR MDX-Net vocal model (67 MB, cached in the user's cache folder) on the CPU. `generate` takes `--vocals` (audio, or a saved vocals JSON) or, when the display has face mouths and the add-on is installed, separates the vocals itself (`--no-vocals` skips). The planner sings each face built from separate props: parts are recognized by name (outline; mouth closed, half, open, O; eyes open, eyes closed; other parts), the outline and other parts hold through each vocal region, the eyes blink every 3 seconds, mouth shapes follow syllables by strength with the closed mouth between, exactly one mouth at a time, and faces rest outside vocal regions. The Timeline carries the vocal regions, so the mouth rules apply instead of reporting not applicable.

**Verified:** tests on generated singing (two phrases, nine syllables) find both regions and every syllable, opening no later than the note and at most 0.1 s early; faces pass the outline and vocals rules; one mouth at a time; blinks; faces rest between phrases; supplied vocals, saved vocals reuse, automatic separation (with a stand-in separator), and the no-vocals path through `generate`. Locally, the real separation model split a synthetic 12-second voice-plus-drums mix in 35 seconds (including model load); vocal regions matched exactly and syllables within one.

**Vocal-guided beats (the Phase 4 swing follow-up):** `vocal_beats.py` blends the mix's onset strength with the vocals', estimates a tempo that may drift with the singer (folded to the song's tempo octave and smoothed over 3 seconds), re-tracks beats on that blend, and, only inside sung passages where the mix's own local tempo drifts more than about 7% from the song's tempo and the re-tracked beats really run at another tempo, swaps in the re-tracked beats. `analyze-audio --vocals` and `generate --vocal-beats` use it (experimental, off by default; see the owner-song findings below); the report records the stretches under `beat_guidance` (an optional, additive field in the v2 schema) and marks each re-placed beat's method. On generated singer-led songs (steady drums, then 30 seconds of drifting tempo carried only by soft chords and a singer, with swung notes), beat F-measure in the singer-led middle rose from 0.65-0.76 to 0.96-1.00 across five songs, and from about 0.87 to 0.99 overall; on the same songs with steady drums and tempo throughout, nothing changed.

**Owner songs, checked locally (2026-11-11):** the owner supplied finished sequences and their songs for local testing only; none of it, and no score from it, is committed. Findings that changed the code, all general:
- Two rows of the same size on one display were merged into one jumbled row, by both the planner and the chase rule. Each row now has its own `row_id` from the classifier; parts of a singing face are never chased as a row.
- Faces whose mouth parts are mustaches (up is open, down is closed) are now recognized, and a closed (resting) mouth may stay on with the face outside vocals; the vocals rule only counts mouths that open.
- Hand-made shows mix hard hits with fades and sweep multi-segment arches segment by segment. The planner now decays pulses and chase steps in quiet and loud sections (mid sections hit hard), wipes multi-segment props across their segments, pulses mini trees on eighth notes and spins the mega tree on sixteenths when loud.
- Section energy is now ranked against the song's other sections (weighted by length) rather than scaled from quietest to loudest: mastered songs differ little in loudness between sections, and the old scale called almost every section loud. A mini tree or icicle line that is not part of a row now pulses instead of holding.
- Vocal-guided beats did not hold up on real songs. A first version trusted the voice wherever it lined up better and made a steady song much worse (singers syncopate). Gating it to stretches where the band's own tempo drifts kept steady songs intact in some cases, but breakdowns still trigger it, the drifting-tempo tracker wanders, and on the owner's genuinely swung song and on a song with a rubato intro it scored lower than the plain tracker. It is therefore experimental and off by default (`generate --vocal-beats`, `analyze-audio --vocals`). The swung-song gap remains open; following the voice is not the fix.

**Not verified:** real recorded vocals; separation speed on the owner's PC; re-scoring the owner's swung, singer-led songs with `evaluate-analysis` against their hand-made grids (owner runs this locally; scores are not committed).

Build vocal separation, vocal regions, syllable onsets, and singing-face choreography. Also use vocal phrasing to guide beat placement where the band follows the singer (rubato or loosely swung stretches), and re-score swung, singer-led songs with `evaluate-analysis` to confirm the gain without regressing steady songs.

**Done when:** A supported singing face lip-syncs to words/syllables, rests during instrumentals, and keeps outline on whenever mouth channels are active; owner opens/plays result in LOR and confirms visual behavior. Mandatory human gate.

### Phase 9 — Planner v2
Build motifs, call-and-response, signature moments, and richer dynamics.

**Done when:** Two different songs produce noticeably different shows; fixed inputs/config produce deterministic planning; owner confirms arrangements are distinct and coherent.

### Phase 10 — Polish
Build reports, docs, Python package distribution, example profiles, and installation workflow. Desktop wrapping and desktop packaging are not part of this phase; they are final delivery work after the browser sequencing and editing workflows are complete.

**Done when:** A new user can install and run by following README; reports cover generated/used/unused props, unsupported items, rules compliance, and physical-test needs; examples are included; CI is green.

### Phase 11A — Browser-first sequencing workspace

**Status: In progress. Owner-authorized on 2026-11-11.**  
**Issue:** #47 — Browser-first professional sequencing workspace  
**Branch:** `ui/browser-sequencer-foundation`

Build the sequencing workspace in the browser using the existing Python engine. This is not a desktop application phase.

**First delivery slice:**
- Open real native S6 v15 LOREDIT and matching audio using local file selection.
- Build tracks from actual sequence props, channels, embedded PropGroup membership, and native effect records.
- Display the full sequence duration with a shared ruler, actual decoded waveform, native timing grids, estimated musical event lanes, and lighting tracks.
- Run the existing librosa analyzer through a loopback-only local endpoint when audio is selected.
- Optionally display `vocals-1.0` reports as heuristic vocal regions and syllable candidates; no words or lyrics are inferred.
- Support synchronized zoom/scroll, audio playback, playhead seeking, track/group collapse, and effect inspection.
- Keep original files read-only; this first slice does not edit or rewrite sequences.
- Do not commit owner LOREDIT files, copyrighted audio, or sanitized derivatives.

**Acceptance:** the four owner-provided reference sequences and their corresponding audio open correctly; prop/channel/effect/timing-grid counts and sequence duration match the source; waveform comes from actual audio samples; all musical and lighting lanes remain aligned through zoom/scroll; large sequences remain responsive; tests and CI pass.

**Desktop boundary:** no Electron, Tauri, installer, or desktop wrapper work during Phase 11A. Desktop packaging is reserved for the final delivery stage.

### Final delivery — Desktop wrapper and packaging

This is the final product-delivery stage, not a prerequisite for sequencing development.

Build the desktop wrapper, installer, and platform-specific packaging only after the browser-based sequencing workspace, musical analysis workflow, and editing/export capabilities are complete and accepted. Reuse the browser workspace and existing Python engine; do not fork the sequencing logic into a separate desktop implementation.

**Done when:** the accepted browser sequencing workflow runs as a packaged desktop application, source and generated files remain protected by the same validation rules, installers are reproducible, and owner verification confirms the complete workflow on the target desktop environment.

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

### Current implementation handoff — 2026-11-11
This is the authoritative current-state summary; older entries below are chronological implementation history.

- **Phase 0–4b:** complete. Phase 4 rework was accepted in PR #17; the scratch-built sequence writer was completed and S6-checked in PR #23.
- **Phase 5:** complete and owner-accepted; PR #29 merged.
- **Phase 6:** complete; PR #34 merged. Native S6 verification of fade, TWINKLE, and SHIMMER output remains part of the Phase 7 owner playback gate.
- **Phase 6b:** complete; PR #36 merged.
- **Phase 7 — Planner v1:** PR #39 merged to master on 2026-11-11. The real-song S6 playback gate remains pending; the merge does not claim owner verification.
- **Phase 8 — Vocals:** PR #44 remains open on branch `phase-8/vocals`, with base `phase-7/planner-v1`. It has not been verified against real recorded vocals or owner S6 playback.
- **Current owner-authorized UI work — Phase 11A:** Issue #47; branch `ui/browser-sequencer-foundation`. Build a browser-first local sequencing workspace. The desktop wrapper and packaging are explicitly deferred until final delivery.
- **Next UI acceptance gate:** open all four owner reference sequences and matching audio; verify native track/effect/timing-grid counts, waveform derivation, synchronized timebase, and large-sequence responsiveness. Keep copyrighted and owner-derived material out of the repository.


### Repository cleanup — 2026-11-11
Owner decision: closed PR #12 unmerged (superseded by the librosa rework) and closed issues #8 and #13 as done. Retired the Phase 3 validation-package workflow, its build script, and its guide; the `pulse` harness itself remains. Stale branches are to be deleted by the owner.

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

The original Phase 4 baseline was merged in `2b962bd39d51b052c3f97d76876a29176dc627ae` and then superseded after it failed real-song review. PR #17 delivered the librosa rework, which the owner accepted on 2026-11-11 for steady songs. The known limitation is swung/rubato singer-led passages; Phase 8 is intended to address those using vocal phrasing. Confidence values remain heuristic, not probabilities.

### Phase 4 merge and handoff — 2026-11-10/11
- PR: https://github.com/MikeAllen1/light-o-rama-sequence-builder/pull/9
- Branch: `phase-4/audio-analysis`
- Final branch head: `36a98f824dcd883d032b3a49240aa8957f20d91e`
- Merge: squash commit `2b962bd39d51b052c3f97d76876a29176dc627ae`
- Final verification: Tests run `42956005759` passed on Linux and Windows; Phase 3 Validation Package run `42956005713` passed; CodeQL run `42956005698` passed.
- Final hardening: corrected cross-platform frame-time test tolerance; documented leading-silence hard-stop candidates; beat-grid confidence is reported separately from tempo confidence.
- Historical state at the close of PR #9: real-song review was pending and the stdlib baseline was not accepted. This was superseded by PR #17 and the owner acceptance recorded in the Phase 4 section above.
- Current Phase 4 status: complete and accepted for steady songs, with the swung/rubato limitation explicitly retained.
