# Audio Analysis Review

This is the manual review procedure for Phase 4. Automated tests use synthetic audio; they do not prove that timing estimates line up with real music.

## Run an analysis

Requirements: Python 3.12, the project environment installed with `uv sync --locked`, and FFmpeg available on `PATH`.

Use a copy of a song you are permitted to analyze. The analyzer does not modify the source audio. Both output paths must be new files.

```powershell
uv run lor-sequence-builder analyze-audio .\song.mp3 --output-json .\song.analysis.json --plot .\song.analysis.svg
```

If you know the approximate tempo, narrow the search range to reduce tempo aliases. For example:

```powershell
uv run lor-sequence-builder analyze-audio .\song.mp3 --output-json .\song.analysis.json --plot .\song.analysis.svg --min-bpm 100 --max-bpm 150
```

The command creates a machine-readable JSON report and an SVG diagnostic plot. Open the SVG in a browser or image viewer and compare its timeline with the source song in an audio player. Both artifacts are staged before publication; the command refuses to overwrite existing outputs and cleans up the JSON if the plot cannot be published.

## Read the plot

- **Blue line:** one-second RMS energy curve. It shows broad loudness/dynamics, not musical importance.
- **Green lines:** estimated beat grid from one global tempo.
- **Purple lines:** provisional downbeats. They assume the first detected beat is beat one and every fourth beat is a downbeat; this is not meter detection.
- **Amber marks:** positive frame-energy-flux peaks. They are transient candidates, not a complete list of drum hits or musical notes.
- **Teal dashed lines:** energy-transition candidates. They are not verse, chorus, bridge, or drop labels.
- **Red lines:** sustained near-silence candidates. Quiet breakdowns and intentional pauses may be included.

Confidence values are heuristic and uncalibrated. Tempo confidence describes the autocorrelation signal, while beat/downbeat confidence is additionally reduced when a competing beat/offbeat phase has similar onset energy. A low beat confidence means the analyzer cannot reliably choose which repeating accent is the metrical beat; it does not mean the tempo estimate itself is necessarily wrong. Treat all confidence values as relative evidence, not probabilities.

## Review checklist

Listen to the song while following the plot. Record:

1. Whether the beat markers stay aligned from the beginning through the end, or gradually drift.
2. Whether the estimated BPM is the perceived tempo or a half/double-time interpretation, especially where strong backbeats, syncopation, or subdivisions compete with the main pulse. Compare tempo confidence with beat confidence; a lower beat confidence flags competing phase interpretations.
3. Whether the provisional downbeats land on actual bar starts. Do not assume 4/4.
4. Whether amber onset marks correspond to meaningful audible attacks, and whether important attacks are missed.
5. Whether teal transitions correspond to audible changes in arrangement or dynamics.
6. Whether red hard-stop markers are genuine stops rather than quiet passages.
7. Whether the energy curve broadly follows the song's dynamics.

Review contrasting material, not just one easy track: a fast/percussive song, a slower song, and a song with tempo or arrangement changes. A single global tempo is expected to struggle with genuine tempo changes.

## Review notes to capture

- Song filename (do not commit the audio file).
- Approximate/known BPM, if available.
- Reported BPM and confidence.
- First obvious beat time and whether the grid drifts later.
- Any half-time/double-time interpretation.
- False or missed onset, section, and hard-stop candidates.
- Whether the plot is useful enough to inform later planning.

Do not commit copyrighted audio or original display media. Share the JSON and SVG only if you are comfortable sharing the filename and analysis metadata; the JSON includes the source filename and SHA-256, but not audio content.

## Current limitations

Phase 4 is an analysis-only stage. It does not generate a sequence or choreography. It does not identify vocals, syllables, instruments, lyrics, or semantic song sections. Downbeats and phrase boundaries are provisional, and the section candidates are based only on RMS energy changes. Real-song review is required before downstream planning should rely on these estimates.
