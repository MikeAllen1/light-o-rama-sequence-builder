# Light-O-Rama Sequence Builder

A desktop-first toolkit for creating music-synchronized lighting sequences for Light-O-Rama S6.

The target output is the native **`.LOREDIT`** sequence format used by S5 and S6. The project is being built around a structured sequence model, a format adapter, and validation against files saved by the actual Light-O-Rama Sequencer.

## Project goals

- Build sequences around musical structure, phrasing, dynamics, and instrumentation—not indiscriminate beat flashes.
- Understand display previews, props, groups, element types, and color capabilities.
- Generate coordinated effects with intentional attacks, holds, fades, transitions, and phrase-level variation.
- Produce native S6 `.LOREDIT` files that open correctly in the Light-O-Rama Sequencer.
- Inspect and validate generated files before they are used in a show.
- Keep the project independent of the original legacy auto-sequencer.

## Current status

**Foundation and first audio-analysis milestone.** The repository includes a versioned intermediate sequence model, model validation, a diagnostic S6 XML inspector, and an initial audio analyzer for tempo, beat candidates, onsets, and relative energy.

The native `.LOREDIT` writer is not marked complete yet. Light-O-Rama documents the format as standard XML, but its exact sequence schema and required metadata must be implemented and tested against real S6-created files. A file is not considered S6-compatible until it opens in S6 and preserves the expected sequence content.

## Architecture

1. **Audio analysis** — tempo, beat and downbeat candidates, onset strength, energy, and phrase boundaries.
2. **Musical arrangement** — intro, verse, chorus, bridge, breakdown, build, and outro.
3. **Display model** — preview, props, groups, elements, colors, and capabilities.
4. **Sequence planner** — assign musical roles and create coherent lighting patterns.
5. **Intermediate sequence model** — versioned, time-based events independent of the output format.
6. **S6 format adapter** — read and write native `.LOREDIT` XML using verified schema rules.
7. **Validation and QA** — schema checks, timing checks, preview references, and round-trip tests in S6.

## Requirements

- Python 3.11 or later
- Windows is the primary target because Light-O-Rama S6 is a Windows application

## Development setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,audio]"
```

Run the command-line tools:

```powershell
lor-sequence-builder --help
lor-sequence-builder analyze-audio path\to\song.mp3 --output build\audio-analysis.json
lor-sequence-builder inspect path\to\sample.loredit
pytest
```

## Native S6 format research

Light-O-Rama documents that licensed sequence files use a standard XML format and that S5/S6 musical and animation sequences use the `.LOREDIT` extension. The Sequencer can also export legacy LMS/LAS files, but those are not the native S5/S6 save format.

- [Full Access XML Data Storage](https://info.lightorama.com/help/feature_comparison.htm)
- [Sequence file extensions](https://info.lightorama.com/help/concept_sequences.htm)
- [Upgrading legacy LMS/LAS sequences](https://info.lightorama.com/help/upgrading_sequences.htm)

See [docs/S6_FORMAT.md](docs/S6_FORMAT.md) for the implementation notes and sample files needed.

## Project identity

The application and generated files will use the project name **Light-O-Rama Sequence Builder**.
