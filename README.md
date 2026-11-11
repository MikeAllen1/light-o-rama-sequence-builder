# Light-O-Rama Sequence Builder

A display-independent command-line tool for building native Light-O-Rama S6 sequences from music and a required `.lorprev` display preview.

**Project status:** Phase 1's native S6 LOREDIT reader/writer is complete. Phase 2 adds standalone `.lorprev` parsing for observed preview revisions 0 and 1. Audio analysis, prop classification, and choreography have not started.

## Product workflow

The planned workflow is:

1. `analyze` — inspect the audio and required `.lorprev`, then produce a human-reviewable `props.yaml`.
2. Review and correct the prop map.
3. `generate` — create a new native S6 `.loredit`, a Timeline JSON file, and a report.

The implementation is deliberately staged. The first engineering milestone was proving that the tool can read and write a native S6 sequence that opens in Light-O-Rama S6. Audio analysis and intelligent choreography come later.

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

The LOREDIT reader currently accepts only `saveFileVersion="15"`, the version represented by the reviewed fixture. The standalone LORPREV parser currently supports internal `Revision` values `0` and `1`; this is separate from the LOREDIT save-file version. XML is parsed with `defusedxml`, with DTDs, entities, and external references forbidden. The writer preserves the parsed XML tree opaquely and atomically creates a new output without overwriting the input or an existing destination.\n\nThe preview is the authoritative display map. For LOR props, each `ChannelGrid` row is interpreted using the documented network, Unit ID, and circuit fields; for DMX props, the documented universe and channel fields are exposed. The complete original row and its source locator are retained. `LOR`, `DMX`, and `Undetermined` are recognized device types. Group membership and arrangement still require a native S6-exported group fixture before semantic support can be claimed.

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
```

## Scope and safety

- The `.lorprev` preview will be mandatory for both analysis and generation.
- Props, channels, and controller identities must come from the preview or an explicitly reviewed prop map; never invent or silently reassign them.
- The user's display does not use pixel props. Pixel/RGB choreography is outside v1 and unsupported props must be reported, not faked or silently omitted.
- Source audio, previews, and sequence files are read-only. Generated output must be a new file.
- Never commit original show files, private previews, copyrighted audio, local machine paths, or secrets. Use sanitized fixtures only after review.
- No GUI, controller upload, live playback, or editing existing sequences in v1.

This is an independent project and is not affiliated with or endorsed by Light-O-Rama.
