#!/usr/bin/env sh
# Start the LOR Sequencer in your browser (macOS and Linux).
# The first start installs what it needs; later starts are quick.
cd "$(dirname "$0")" || exit 1
if ! command -v uv >/dev/null 2>&1; then
  echo 'The LOR Sequencer needs "uv". Install it once with:'
  echo '  curl -LsSf https://astral.sh/uv/install.sh | sh'
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo 'The LOR Sequencer needs FFmpeg to read songs. Install it (macOS: brew install ffmpeg;'
  echo 'Debian/Ubuntu: sudo apt install ffmpeg), then run this again.'
  exit 1
fi
uv sync --locked --quiet || { echo 'Setup did not finish; run: uv run lor-sequence-builder doctor'; exit 1; }
exec uv run lor-sequence-ui
