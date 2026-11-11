# Light-O-Rama Sequence Builder

A display-independent Light-O-Rama S6 sequence builder with a Python CLI and a browser-based local sequencing workspace. The browser workspace is being developed now; desktop packaging is deliberately deferred until the end.

**Project status:** Phases 0 through 8 are merged; the owner playback gates for Phase 7 (planner) and Phase 8 (singing faces) remain open. Phase 11A adds the browser-first sequencing workspace; it is not a desktop app. Desktop packaging remains a final-stage deliverable. See [docs/PLAN.md](docs/PLAN.md) for the authoritative status.

## Product workflow

The planned workflow is:

1. `analyze-preview`: read the required `.lorprev` and report what each prop is (arch, mega tree, singing face, ...), with evidence and a review list.
2. Review the report. Correct anything wrong in the S6 Preview Editor itself (shape type, grouping, start location, name) and run it again; the preview is the only input.
3. `generate` — create a new native S6 `.loredit`, a Timeline JSON file, and a report.

The implementation is deliberately staged. The native S6 read/write path and fixed-tempo sequence-generation path are established. Phase 4 adds audio feature analysis; intelligent choreography comes later.

See [docs/PLAN.md](docs/PLAN.md) for the phase order, acceptance criteria, and handoff log. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the intended system boundaries and data contracts.

## Requirements

- Python 3.12
- `uv`

Install uv using the official instructions: https://docs.astral.sh/uv/getting-started/installation/

## Setup (PowerShell)

```powershell
git clone https://github.com/MikeAllen1/light-o-rama-sequence-builder.git
cd light-o-rama-sequence-builder
uv sync --locked
uv run lor-sequence-builder --help
```

## Current commands

Inspect a sequence:

```powershell
uv run lor-sequence-builder inspect .\path\to\show.loredit
```

Inspect a standalone S6 display preview:

```powershell
uv run lor-sequence-builder inspect-preview .\path\to\display.lorprev
```

Write a new round-trip copy (the destination must not already exist):

```powershell
uv run lor-sequence-builder roundtrip .\path\to\show.loredit .\output\roundtrip.loredit
```

The LOREDIT reader currently accepts only `saveFileVersion="15"`, the version represented by the reviewed fixture. A preview's internal `Revision` value is an edit counter that S6 increments each time the preview is saved; the parser records it but never uses it to accept or reject a preview. XML is parsed with `defusedxml`, with DTDs, entities, and external references forbidden. The writer preserves the parsed XML tree opaquely and atomically creates a new output without overwriting the input or an existing destination.

The preview is the authoritative display map. For LOR props, each `ChannelGrid` row exposes network, Unit ID, and the circuit value present in that row; for DMX props, universe and channel are exposed. These are address fields only: remaining fields are retained verbatim and are not yet semantically interpreted. The original row and source locator are retained. The parser enforces a 20 MiB input limit, 256-level XML nesting limit, and 100,000-element limit, and reports missing or duplicate prop IDs rather than treating them as reliable identities. `PropGroup` and `member` records are parsed into typed group/member models, including prop ID references, arrangement, orientation, top, and left values. The repository's current fixture set is synthetic; larger preview examples are generated at test time.

## Identify props in a preview

```powershell
uv run lor-sequence-builder analyze-preview .\display.lorprev --report .\display.analysis.json
```

Reads the preview only (never modifies it) and lists each prop as confident, needs review, or unknown, with its role, row position, direction, color capability, and whether v1 can sequence its channels. Evidence comes from the S6 shape type and parameters, geometry, channel count and type, groups and their order, links to master props, and the string start location. When the S6 shape type is specific (Arch, Star, Tree...), it wins over the name; when a prop is drawn as plain lines, its name decides and the prop is flagged for review. To correct a conclusion, fix the prop in the S6 Preview Editor and run the command again.

## Browser sequencing workspace

Start the local browser-based sequencing interface:

```powershell
uv run lor-sequence-ui
```

The server binds only to `127.0.0.1`. Open a native S6 v15 `.loredit` file and its matching audio. The workspace builds tracks from the sequence's actual props, channels, embedded prop groups, timing grids, and effects; the waveform is decoded from the selected audio. When served by this command, the selected audio is sent only to the local Python analysis endpoint and held in a temporary directory while the existing librosa analyzer runs. The source audio and sequence are not modified or retained by the server.

The first delivery is a read-only reference workspace: it supports synchronized navigation, playback, musical marker visualization, track expansion/collapse, and effect inspection. Editing and writing existing sequences are subsequent work. Optional saved audio-analysis JSON and `vocals-1.0` JSON can be loaded. Vocal regions and syllable candidates are heuristic; the current vocal format does not recognize words or provide lyrics.

This is a browser application, not a desktop wrapper. Do not install Electron, Tauri, or another desktop framework during the sequencing-workspace phases.

## Build a show

```powershell
uv run lor-sequence-builder generate --preview .\display.lorprev --audio .\Song.mp3 --output .\Song.loredit
```

Before building, it asks whether you have any specific requirements (skipped when you have saved ones; `--ask-requirements` always asks, `--no-ask` never does). It then analyzes the song, splits it into sections by energy, plans each kind of prop (rows of arches and mini trees chase or fill in their real order, a mega tree rotates, outlines and decorations hold or pulse), checks the plan against every rule and requirement, and writes:

- `Song.loredit`: the sequence. Put the song in your S6 audio folder; `--music-filename` sets the stored name (default: the audio file's name).
- `Song.plan.svg`: a picture of the whole show, one lane per prop, that opens in any browser or on a phone.
- `Song.timeline.json`, `Song.plan.json`, `Song.rules.json`: every decision, the section plan with props used and left out, and the rule report.
- `Song.analysis.json` and `Song.analysis.svg`: the music analysis. Pass `--analysis` instead of `--audio` to reuse one.

### Singing faces

Faces drawn as separate props (outline, mouth shapes, eyes) sing along: the mouth opens on each syllable (wider on stronger ones, an "O" mouth on some held notes when you have one, the closed mouth between words), the eyes blink every few seconds, the outline stays on whenever a mouth is on, and the face rests during instrumentals. Parts are recognized by their names in the preview: `outline`; `mouth` or `lips` with `closed`, `half`, `open`, or `o`; `eyes open`, `eyes closed`.

That needs the vocals on their own. Either:

- pass a vocals-only file you already have: `--vocals .\Song-vocals.wav`, or
- install the optional separation add-on once, and `generate` splits the vocals out of the song itself (only when your display has face mouths):

  ```powershell
  uv sync --locked --extra vocals
  ```

  It is a large install (PyTorch), downloads a 67 MB model the first time, and then runs offline. Splitting takes a few minutes per song (about 6 on a 2-core machine); the result is saved as `Song.vocals.wav` and `Song.vocals.json`, and either can be passed to `--vocals` next time. `--no-vocals` skips it.

Without vocals, face mouths stay still and the rest of the face lights with the show.

## Rules and display requirements

Every choreography Timeline is checked against built-in rules (no overlapping effects, movements that finish, falls that go down, a face outline whenever a mouth is on, and more) plus any requirements you add in your own rule profile. A Timeline with rule errors is never written to a sequence.

Before building, tell it what you want in your own words (or answer a few questions about your display). Confirmed requirements are saved next to the preview and used by every later build:

```powershell
uv run lor-sequence-builder requirements .\display.lorprev
uv run lor-sequence-builder list-rules --rules .\my-display.yaml
uv run lor-sequence-builder check-timeline .\display.lorprev .\plan.json --rules .\my-display.yaml
uv run lor-sequence-builder build-from-timeline --preview .\display.lorprev --timeline .\plan.json --music-filename "Song.mp3" --output .\song.loredit --report .\song.rules.json
```

See [docs/RULES.md](docs/RULES.md) for every rule, the profile format, and the Timeline format.

## Phase 4 audio analysis

Install FFmpeg and ensure `ffmpeg` is available on PATH. FFmpeg decodes any supported audio format to mono 22.05 kHz signed 16-bit PCM; librosa then analyzes the decoded samples (it never opens files itself). The command writes a versioned JSON report plus an SVG diagnostic plot:

```powershell
uv run lor-sequence-builder analyze-audio .\song.mp3 --output-json .\song.analysis.json --plot .\song.analysis.svg
```

The report contains tempo (with a stability confidence), beats from a dynamic-programming beat tracker, downbeats chosen from harmonic change, onsets, an energy curve, four-bar phrase candidates, unlabelled section candidates (self-similarity plus loudness change at bar starts, and broad energy transitions), and hard-stop candidates. Every inferred event records its method and a heuristic confidence. The formal contract is [audio-analysis-v2.schema.json](docs/schemas/audio-analysis-v2.schema.json). Output files must be new paths and are never overwritten.

Add `--beats-per-bar 3` for songs counted in 3; the default is 4.

Experimental, off by default: `--vocals .\song-vocals.wav` lets a vocals-only track re-place beats in stretches where the band's own tempo drifts (the band following the singer). It helped on generated rubato songs but not on the real songs it was checked against, where the plain beat tracker did as well or better, so `generate` only uses it with `--vocal-beats`. The report lists any re-placed stretches under `beat_guidance`.

Score the analysis against timing grids you placed by hand in an existing sequence for the same song:

```powershell
uv run lor-sequence-builder evaluate-analysis --analysis .\song.analysis.json --sequence .\song.loredit --beats-grid "Beats" --bars-grid "Bars" --sections-grid "Sections"
```

See the [audio analysis review procedure](docs/AUDIO_ANALYSIS_REVIEW.md) for acceptance targets and how to read the results.

## Pulse sequences (engineering harness)

The `pulse` command proves the preview → Timeline → native S6 writer path using a fixed BPM. It does not analyze audio or create intelligent choreography. It builds a brand-new native S6 v15 sequence from the preview alone; no template sequence is needed:

```powershell
uv run lor-sequence-builder pulse --preview .\display.lorprev --bpm 120 --duration-seconds 180 --music-filename "Show\song.mp3" --output .\pulse-test.loredit --timeline-output .\pulse-test.timeline.json
```

`--music-filename` is stored in the sequence the way S6 records it (S6 always attaches an audio file to a musical sequence). Props linked to a master prop are driven by their master and get no sequence prop of their own; props without a verified channel layout (pixel/RGB, DMX, legacy AC/DC, unassigned) are excluded and listed in the output. See the new-sequence structure in [docs/S6_FORMAT.md](docs/S6_FORMAT.md).

The older template mode (`--template`, a native S6 v15 sequence whose embedded preview matches the standalone preview exactly) still works but is deprecated. The rules below apply to it.

The verified Phase 3 boundary is `DeviceType=LOR` with `TraditionalType=Single Color`, `Multicolor_string_1_ch`, or `Channel_per_color`. The standalone preview and embedded template must have identical prop subtrees (all attributes and nested data, including geometry and master-prop references) and identical `PropGroup` membership/layout. Numeric geometry and group coordinates allow only a 1e-6 tolerance. Preview edit revisions are ignored, since they only count saves.

Physical mapping is deliberately strict. Each LOR `ChannelGrid` entry must have a complete network/Unit ID/circuit address, and the number of entries must equal the native `SeqProp/channel` count. Entry order is mapped to native channel coordinates using observed S6 v15 patterns: `Single Color` and `Multicolor_string_1_ch` use row 0 and sequential columns; `Channel_per_color` uses row 0, column 0, and sequential color coordinates. These addresses are included in each Timeline channel reference. A prop with no native `SeqProp`, incomplete address, count mismatch, or unverified native coordinates is explicitly listed as excluded with a reason; no mapping is invented. Legacy `DeviceType=AC` and `DC` values remain parseable for preview compatibility but are explicitly excluded from Phase 3 because their native mapping is not verified. Unsupported prop types are also listed in the Timeline.

Existing effects in the template copy are intentionally removed before the generated intensity pulses are inserted; the source template is never modified. The template's duration controls the generated sequence duration. This is a plumbing harness, not a professional choreography generator. The owner must still open and play the generated file in S6 and verify the intended physical lights respond correctly; automated mapping checks do not replace that gate.

The command writes a deterministic, versioned Timeline JSON and a new `.loredit`; it refuses to overwrite inputs or existing outputs. It bounds generation to 50,000 beats and 250,000 events. The generated file still requires manual opening and playback verification in the target S6 release.

## Development checks

The CI workflow pins the development tools and runs:

```powershell
uv run --no-sync --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 --with types-defusedxml==0.7.0.20260504 --with types-PyYAML==6.0.12.20260906 python -m pytest
uv run --no-sync --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 --with types-defusedxml==0.7.0.20260504 --with types-PyYAML==6.0.12.20260906 ruff check .
uv run --no-sync --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 --with types-defusedxml==0.7.0.20260504 --with types-PyYAML==6.0.12.20260906 mypy --strict src tests
uv run --no-sync --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 --with types-defusedxml==0.7.0.20260504 --with types-PyYAML==6.0.12.20260906 --with setuptools==84.1.0 pip-audit --skip-editable
```

## Repository structure

```text
src/lor_sequence_builder/  Python package, CLI, and browser workspace assets
tests/                     Unit tests and synthetic fixtures
docs/                      Architecture, format evidence, and phased plan
.github/workflows/         CI and CodeQL workflows
SECURITY.md                Security policy
CONTRIBUTING.md            Contribution rules and phase workflow
LICENSE                    MIT license
```

## Scope and safety

- The `.lorprev` preview will be mandatory for both analysis and generation.
- Props, channels, and controller identities must come from the preview; never invent or silently reassign them.
- V1 does not support pixel/RGB props. Unsupported props must be reported, not faked or silently omitted.
- Source audio, previews, and sequence files are read-only. Generated output must be a new file.
- Never commit original or sanitized show files, private previews, copyrighted audio, local machine paths, or secrets. Tests use fictional, hand-authored or runtime-generated synthetic fixtures only.
- No desktop wrapper or packaging yet; desktop delivery is deferred until the final stage. The browser workspace is local-only. Controller upload and live hardware playback remain out of scope. The first browser workspace is read-only; editing existing sequences is a later phase.

This is an independent project and is not affiliated with or endorsed by Light-O-Rama.
