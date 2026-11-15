# For developers

```
git clone https://github.com/MikeAllen1/light-o-rama-sequence-builder.git
cd light-o-rama-sequence-builder
uv sync --locked
uv run lor-sequence-ui                 # the workspace, in your browser
uv run lor-sequence-builder --help     # the command line
```

Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), and FFmpeg on PATH. `uv run lor-sequence-builder doctor` checks the setup.

Optional extras: `--extra vocals` (vocal separation for singing faces), `--extra lyrics` (offline transcription), `--extra desktop` (desktop app build).

## Checks

```
uv run --no-sync --with pytest==9.2.0 --with playwright==1.56.0 --with axe-playwright-python==0.1.8 python -m pytest
uv run --no-sync --with ruff==0.17.4 ruff check .
uv run --no-sync --with mypy==1.18.2 --with types-defusedxml==0.7.0.20260504 --with types-PyYAML==6.0.12.20260906 --with pytest==9.2.0 mypy --strict src tests
```

## Where things are

| Read | For |
| --- | --- |
| [ARCHITECTURE.md](https://github.com/MikeAllen1/light-o-rama-sequence-builder/blob/master/docs/ARCHITECTURE.md) | Stages, boundaries, data contracts |
| [S6_FORMAT.md](https://github.com/MikeAllen1/light-o-rama-sequence-builder/blob/master/docs/S6_FORMAT.md), [S4_FORMAT.md](https://github.com/MikeAllen1/light-o-rama-sequence-builder/blob/master/docs/S4_FORMAT.md) | File-format evidence |
| [RULES.md](https://github.com/MikeAllen1/light-o-rama-sequence-builder/blob/master/docs/RULES.md) | Rules, profiles and the Timeline format |
| [SEQUENCER_UI.md](https://github.com/MikeAllen1/light-o-rama-sequence-builder/blob/master/docs/SEQUENCER_UI.md) | The workspace |
| [packaging/README.md](https://github.com/MikeAllen1/light-o-rama-sequence-builder/blob/master/packaging/README.md) | Desktop builds and releases |
| [CONTRIBUTING.md](https://github.com/MikeAllen1/light-o-rama-sequence-builder/blob/master/CONTRIBUTING.md) | Ground rules |

Ground rules in short: never invent props, channels or file formats (they come from the preview and from real S6 evidence); never modify input files; never commit real show files, previews or audio — tests use synthetic fixtures only.
