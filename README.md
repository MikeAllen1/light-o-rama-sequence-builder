# Light-O-Rama Sequence Builder

A display-independent command-line tool for building native Light-O-Rama S6 sequences from music and a required `.lorprev` display preview.

**Project status:** Phases 0–3 are complete and merged. The Phase 4 audio-analysis baseline is merged (PR #9); its real-song review is the open acceptance gate. Prop classification, rules, and intelligent choreography remain future work. See [docs/PLAN.md](docs/PLAN.md) for the authoritative status.

## Product workflow

The planned workflow is:

1. `analyze` — inspect the audio and required `.lorprev`, then produce a human-reviewable `props.yaml`.
2. Review and correct the prop map.
3. `generate` — create a new native S6 `.loredit`, a Timeline JSON file, and a report.

The implementation is deliberately staged. The native S6 read/write path and fixed-tempo sequence-generation path are established. Phase 4 adds audio feature analysis; intelligent choreography comes later.

See [docs/PLAN.md](docs/PLAN.md) for the phase order, acceptance criteria, and handoff log. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the intended system boundaries and data contracts. For the simple Phase 3 S6 playback check, follow [docs/PHASE3_VALIDATION.md](docs/PHASE3_VALIDATION.md); it provides a one-download ZIP generated automatically by GitHub Actions.

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

The preview is the authoritative display map. For LOR props, each `ChannelGrid` row exposes network, Unit ID, and the circuit value present in that row; for DMX props, universe and channel are exposed. These are address fields only: remaining fields are retained verbatim and are not yet semantically interpreted. The original row and source locator are retained. The parser enforces a 20 MiB input limit, 256-level XML nesting limit, and 100,000-element limit, and reports missing or duplicate prop IDs rather than treating them as reliable identities. `PropGroup` and `member` records are parsed into typed group/member models, including prop ID references, arrangement, orientation, top, and left values. The supplied Revision 56 fixture contains 51 props and one group with five members.

## Phase 4 audio analysis (baseline merged; acceptance review open)

Install FFmpeg and ensure `ffmpeg` is available on PATH. The first analyzer accepts audio formats FFmpeg can decode, normalizes to mono 11.025 kHz signed 16-bit PCM, and writes a versioned JSON report plus an SVG diagnostic plot:

```powershell
uv run lor-sequence-builder analyze-audio .\song.mp3 --output-json .\song.analysis.json --plot .\song.analysis.svg --min-bpm 60 --max-bpm 200
```

The current deterministic signal-processing baseline estimates one global tempo from positive energy-flux autocorrelation, derives beat/downbeat candidates, detects energy-flux onsets, reports RMS energy, proposes energy-transition and fixed 16-beat phrase candidates, and flags sustained near-silence as hard-stop candidates. It deliberately does **not** claim semantic verse/chorus recognition, changing-tempo tracking, spectral onset classification, or vocal/syllable detection. Confidence, event provenance, tool versions, and limitations are included in the JSON. The formal v1.0 contract is [audio-analysis-v1.schema.json](docs/schemas/audio-analysis-v1.schema.json). Output files must be new paths and are never overwritten.

This is an initial measurable baseline, not professional choreography. Inspect the SVG against the song and treat low-confidence or musically implausible estimates as unresolved. Follow the [real-song review procedure](docs/AUDIO_ANALYSIS_REVIEW.md) before relying on these estimates for later planning.



## Phase 3 walking skeleton

The temporary engineering command `pulse` proves the preview → Timeline → native S6 writer path using a fixed BPM. It does not analyze audio or create intelligent choreography. It requires a native S6 v15 `.loredit` template whose embedded prop IDs and per-prop `DeviceType`, `TraditionalType`, and `ChannelGrid` declarations match the supplied standalone preview exactly.

Example:

```powershell
uv run lor-sequence-builder pulse --preview .\display.lorprev --template .\template.loredit --bpm 120 --output .\pulse-test.loredit --timeline-output .\pulse-test.timeline.json
```

The verified Phase 3 boundary is `DeviceType=LOR` with `TraditionalType=Single Color`, `Multicolor_string_1_ch`, or `Channel_per_color`. The standalone preview and embedded template must have identical prop subtrees (all attributes and nested data, including geometry and master-prop references) and identical `PropGroup` membership/layout. Numeric geometry and group coordinates allow only a 1e-6 tolerance. Preview edit revisions are ignored, since they only count saves.

Physical mapping is deliberately strict. Each LOR `ChannelGrid` entry must have a complete network/Unit ID/circuit address, and the number of entries must equal the native `SeqProp/channel` count. Entry order is mapped to native channel coordinates using observed S6 v15 patterns: `Single Color` and `Multicolor_string_1_ch` use row 0 and sequential columns; `Channel_per_color` uses row 0, column 0, and sequential color coordinates. These addresses are included in each Timeline channel reference. A prop with no native `SeqProp`, incomplete address, count mismatch, or unverified native coordinates is explicitly listed as excluded with a reason; no mapping is invented. Legacy `DeviceType=AC` and `DC` values remain parseable for preview compatibility but are explicitly excluded from Phase 3 because their native mapping is not verified. Unsupported prop types are also listed in the Timeline.

Existing effects in the template copy are intentionally removed before the generated intensity pulses are inserted; the source template is never modified. The template's duration controls the generated sequence duration. This is a plumbing harness, not a professional choreography generator. The owner must still open and play the generated file in S6 and verify the intended physical lights respond correctly; automated mapping checks do not replace that gate.

The command writes a deterministic, versioned Timeline JSON and a new `.loredit`; it refuses to overwrite inputs or existing outputs. It bounds generation to 50,000 beats and 250,000 events. The generated file still requires manual opening and playback verification in the target S6 release.

## Development checks

The CI workflow pins the development tools and runs:

```powershell
uv run --no-sync --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 --with types-defusedxml==0.7.0.20260504 python -m pytest
uv run --no-sync --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 --with types-defusedxml==0.7.0.20260504 ruff check .
uv run --no-sync --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 --with types-defusedxml==0.7.0.20260504 mypy --strict src tests
uv run --no-sync --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 --with types-defusedxml==0.7.0.20260504 --with setuptools==84.1.0 pip-audit --skip-editable
```

## Repository structure

```text
src/lor_sequence_builder/  Python package and CLI
tests/                     Unit tests and sanitized fixtures
docs/                      Architecture, format evidence, and phased plan
.github/workflows/         CI and CodeQL workflows
SECURITY.md                Security policy
CLAUDE.md                  Instructions for AI coding sessions
LICENSE                    MIT license
```

## Scope and safety

- The `.lorprev` preview will be mandatory for both analysis and generation.
- Props, channels, and controller identities must come from the preview or an explicitly reviewed prop map; never invent or silently reassign them.
- V1 does not support pixel/RGB props. Unsupported props must be reported, not faked or silently omitted.
- Source audio, previews, and sequence files are read-only. Generated output must be a new file.
- Never commit original show files, private previews, copyrighted audio, local machine paths, or secrets. Use sanitized fixtures only after review.
- No GUI, controller upload, live playback, or editing existing sequences in v1.

This is an independent project and is not affiliated with or endorsed by Light-O-Rama.
