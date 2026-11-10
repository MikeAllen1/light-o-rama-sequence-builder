# Light-O-Rama Sequence Builder

A display-independent command-line tool for building native Light-O-Rama S6 sequences from music and a required `.lorprev` display preview.

**Project status:** Phase 0 — scaffold only. The CLI currently displays help; sequence generation is not implemented.

## Product workflow

The planned workflow is:

1. `analyze` — inspect the audio and required `.lorprev`, then produce a human-reviewable `props.yaml`.
2. Review and correct the prop map.
3. `generate` — create a new native S6 `.loredit`, a Timeline JSON file, and a report.

The implementation is deliberately staged. The first engineering milestone after the scaffold is proving that the tool can read and write a native S6 sequence that opens in Light-O-Rama S6. Audio analysis and intelligent choreography come later.

See [docs/PLAN.md](docs/PLAN.md) for the phase order, acceptance criteria, and handoff log. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the intended system boundaries and data contracts. [CLAUDE.md](CLAUDE.md) contains persistent instructions for coding agents.

## Requirements

- Python 3.12
- `uv`

Install uv using the official instructions: https://docs.astral.sh/uv/getting-started/installation/

## Setup (PowerShell)

```powershell
git clone https://github.com/MikeAllen1/light-o-rama-sequence-builder.git
cd light-o-rama-sequence-builder
uv sync --locked
```

Show CLI help:

```powershell
uv run lor-sequence-builder --help
```

The Phase 0 CLI is intentionally minimal. It does not yet inspect files or generate sequences.

## Development checks

The CI workflow pins the development tools and runs:

```powershell
uv run --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 pytest
uv run --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 ruff check .
uv run --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 mypy --strict src tests
uv run --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 --with setuptools==84.1.0 pip-audit --skip-editable
```

## Repository structure

```text
src/lor_sequence_builder/  Minimal Python package and CLI
tests/                     Scaffold tests
docs/                      Architecture and phased delivery plan
.github/workflows/         CI and CodeQL workflows
CLAUDE.md                  Persistent coding-agent instructions
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
