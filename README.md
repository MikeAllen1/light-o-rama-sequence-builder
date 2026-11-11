# Light-O-Rama Sequence Builder

A display-independent command-line tool for building native Light-O-Rama S6 sequences from music and a required `.lorprev` display preview.

**Project status:** Phases 0–3 are complete and merged. The Phase 4 audio-analysis baseline is merged; real-song acceptance and security follow-ups are in progress on PR #12. Phase 4.5 (Issue #13) will remove the template requirement by building a blank native S6 v15 sequence directly from the preview. Prop classification, rules, and intelligent choreography remain future work.

## Product workflow

The planned workflow is:

1. `analyze` — inspect the audio and required `.lorprev`, then produce a human-reviewable `props.yaml`.
2. Review and correct the prop map.
3. `generate` — create a new native S6 `.loredit` directly from the preview and reviewed prop map, plus Timeline JSON and a report. A matching `.loredit` template is not required; an existing sequence may be used only as an optional reference/import source.

The implementation is deliberately staged. Native S6 reading/round-trip writing and the fixed-tempo Phase 3 harness are established. The Phase 3 `pulse` command still uses a matching template as a temporary engineering constraint; Phase 4.5 removes that constraint from the product generation path. Phase 4 adds audio feature analysis; intelligent choreography comes later.

See [docs/PLAN.md](docs/PLAN.md) for the phase order, acceptance criteria, and handoff log. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the intended system boundaries and data contracts. For the simple Phase 3 S6 playback check, follow [docs/PHASE3_VALIDATION.md](docs/PHASE3_VALIDATION.md); it provides a one-download ZIP generated automatically by GitHub Actions.

## Requirements

- Python 3.12 or newer (CI compatibility matrix: 3.12, 3.13, and 3.14)
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

The LOREDIT reader currently accepts only `saveFileVersion="15"`, the version reviewed against owner-supplied examples. Those owner files and all derived copies are kept outside the repository. The preview parser supports internal `Revision` values `0`, `1`, `56`, and `58`; these are distinct from the LOREDIT save-file version. XML is parsed with `defusedxml`, with DTDs, entities, and external references forbidden. The writer preserves the parsed XML tree semantically and creates a new output without overwriting the input or an existing destination. XML serialization is not byte-identical: comments, original BOM/line endings, and quote style are not guaranteed to survive.

The preview is the authoritative display map. For LOR props, each `ChannelGrid` row exposes network, Unit ID, and the circuit value present in that row; for DMX props, universe and channel are exposed. These are address fields only: remaining fields are retained verbatim and are not yet semantically interpreted. The original row and source locator are retained. The parser enforces a 20 MiB input limit, 256-level XML nesting limit, and 100,000-element limit, and reports missing or duplicate prop IDs rather than treating them as reliable identities. `PropGroup` and `member` records are parsed into typed group/member models, including prop ID references, arrangement, orientation, top, and left values. The runtime-generated synthetic Revision 56 integration preview contains 51 fictional props and one group with five members.

## Phase 4 audio analysis (in progress)

Install FFmpeg and ensure `ffmpeg` is available on PATH. The analyzer accepts supported audio formats (MP3, MP4/M4A, WAV, FLAC, AAC, OGG, WMA, and AIFF), normalizes to mono 11.025 kHz signed 16-bit PCM, and writes a versioned JSON report plus an SVG diagnostic plot:

```powershell
uv run lor-sequence-builder analyze-audio .\song.mp3 --output-json .\song.analysis.json --plot .\song.analysis.svg --min-bpm 60 --max-bpm 200
```

The current deterministic signal-processing baseline estimates one global tempo from positive energy-flux autocorrelation, derives beat/downbeat candidates, detects energy-flux onsets, reports RMS energy, proposes energy-transition and fixed 16-beat phrase candidates, and flags sustained near-silence as hard-stop candidates. It deliberately does **not** claim semantic verse/chorus recognition, changing-tempo tracking, spectral onset classification, or vocal/syllable detection. Confidence, event provenance, tool versions, and limitations are included in the JSON. The formal v1.3 contract is [audio-analysis-v1.schema.json](docs/schemas/audio-analysis-v1.schema.json). Output files must be new paths and are never overwritten.

This is an initial measurable baseline, not professional choreography. Beat grids can remain ambiguous when half-time/double-time and offbeat accents compete; do not treat the selected BPM as ground truth. Inspect the SVG against the song and treat low-confidence or musically implausible estimates as unresolved. Follow the [real-song review procedure](docs/AUDIO_ANALYSIS_REVIEW.md) before relying on these estimates for later planning.



## Phase 3 walking skeleton

The temporary engineering command `pulse` proves the preview → Timeline → native S6 writer path using a fixed BPM (including decimal values such as `127.43`). It does not analyze audio or create intelligent choreography. It requires a native S6 v15 `.loredit` template whose embedded prop IDs and per-prop `DeviceType`, `TraditionalType`, and `ChannelGrid` declarations match the supplied standalone preview exactly.

Example:

```powershell
uv run lor-sequence-builder pulse --preview .\display.lorprev --template .\template.loredit --bpm 127.43 --output .\pulse-test.loredit --timeline-output .\pulse-test.timeline.json
```

The verified Phase 3 boundary is `DeviceType=LOR` with `TraditionalType=Single Color`, `Multicolor_string_1_ch`, or `Channel_per_color`. The standalone preview and embedded template must have identical prop subtrees (all attributes and nested data, including geometry and master-prop references) and identical `PropGroup` membership/layout. Numeric geometry and group coordinates allow only a 1e-6 tolerance. Revision markers may differ; the independent S6 fixture pairs standalone Revision 58 with embedded Revision 56.

Physical mapping is deliberately strict. Each LOR `ChannelGrid` entry must have a complete network/Unit ID/circuit address, and the number of entries must equal the native `SeqProp/channel` count. Entry order is mapped to native channel coordinates using observed S6 v15 patterns: `Single Color` and `Multicolor_string_1_ch` use row 0 and sequential columns; `Channel_per_color` uses row 0, column 0, and sequential color coordinates. These addresses are included in each Timeline channel reference. A prop with no native `SeqProp`, incomplete address, count mismatch, or unverified native coordinates is explicitly listed as excluded with a reason; no mapping is invented. Legacy `DeviceType=AC` and `DC` values remain parseable for preview compatibility but are explicitly excluded from Phase 3 because their native mapping is not verified. Unsupported prop types are also listed in the Timeline.

Existing effects in the template copy are intentionally removed before the generated intensity pulses are inserted; the source template is never modified. The template's duration controls the generated sequence duration. This is a plumbing harness, not a professional choreography generator. The owner must still open and play the generated file in S6 and verify the intended physical lights respond correctly; automated mapping checks do not replace that gate.

The command writes a deterministic, versioned Timeline JSON and a new `.loredit`; it refuses to overwrite inputs or existing outputs. It bounds generation to 50,000 beats and 250,000 events. The generated file still requires manual opening and playback verification in the target S6 release.

## Development checks

Pinned developer tools are defined in the `dev` dependency group in `pyproject.toml` and committed in `uv.lock`. CI tests Python 3.12, 3.13, and 3.14 on Windows and Linux. Once the updated lock is committed, use `uv sync --locked --group dev`, then run:

```powershell
uv run --no-sync coverage run --branch --source=lor_sequence_builder -m pytest
uv run --no-sync coverage report --show-missing
uv run --no-sync ruff check .
uv run --no-sync mypy --strict src tests
```

CI audits the locked production dependency export separately with `pip-audit`; developer tooling is not mixed into that production dependency audit. The `pip-audit` command scans the exported runtime requirements only; its own developer-tool dependencies are excluded from that audit.


## Repository structure

```text
src/lor_sequence_builder/  Python package and CLI
tests/                     Unit tests and runtime-generated synthetic fixtures
docs/                      Architecture, format evidence, and phased plan
.github/workflows/         CI and CodeQL workflows
SECURITY.md                Security policy
```

## Scope and safety

- The `.lorprev` preview will be mandatory for both analysis and generation.
- Props, channels, and controller identities must come from the preview or an explicitly reviewed prop map; never invent or silently reassign them.
- V1 does not support pixel/RGB choreography. Unsupported props must be reported, not faked or silently omitted.
- Source audio, previews, and sequence files are read-only. Generated output must be a new file.
- Never commit user-owned show files, private previews, copyrighted audio, local machine paths, or secrets. Tests generate synthetic sequences and previews at runtime.
- No GUI, controller upload, live playback, or editing existing sequences in v1.

This is an independent project and is not affiliated with or endorsed by Light-O-Rama.
