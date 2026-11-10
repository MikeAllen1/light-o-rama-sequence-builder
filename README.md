# Light-O-Rama Sequence Builder

A display-independent command-line tool for building native Light-O-Rama S6 sequences.

**Current status:** Phase 1 implements a fixture-driven reader and loss-preserving writer for the observed S6 LOREDIT save-file version 15 format. It does not yet analyze audio, parse `.lorprev` files, or generate choreography.

## Setup (PowerShell)

```powershell
uv sync --locked
uv run lor-sequence-builder --help
```

## Phase 1 commands

Inspect a sequence:

```powershell
uv run lor-sequence-builder inspect .\path\to\show.loredit
```

Write a new round-trip copy (the destination must not already exist):

```powershell
uv run lor-sequence-builder roundtrip .\path\to\show.loredit .\output\roundtrip.loredit
```

The reader currently accepts only `saveFileVersion="15"`, the version represented by the reviewed fixture. XML is parsed with `defusedxml`, with DTDs, entities, and external references forbidden. The writer preserves the parsed XML tree opaquely and atomically creates a new output without overwriting the input or an existing destination.

## Development checks

```powershell
uv run --no-sync --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 python -m pytest
uv run --no-sync --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 ruff check .
uv run --no-sync --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 mypy --strict src tests
uv run --no-sync --with pytest==9.2.0 --with ruff==0.17.4 --with mypy==1.18.2 --with pip-audit==2.10.1 --with setuptools==84.1.0 pip-audit --skip-editable
```

See [docs/PLAN.md](docs/PLAN.md) for the staged roadmap and [docs/S6_FORMAT.md](docs/S6_FORMAT.md) for the exact format evidence and limitations. The compressed test fixture is a reduced derivative of the owner-approved neutral-grid sequence; it contains no original audio, machine-specific media path, or house background.
