# Audio Analysis Review

Phase 4 acceptance is measured, not eyeballed. Any sequence you have already timed by hand is ground truth: its free timing grids record where you heard the beats, bar starts, and sections. The `evaluate-analysis` command scores the analyzer against those grids.

Automated tests use synthetic audio. They prove the code behaves correctly on known inputs, not that it lines up with real music. Only real songs prove that.

## 1. Analyze a song

Requirements: Python 3.12, the project environment installed with `uv sync --locked`, and FFmpeg available on `PATH`.

```powershell
uv run lor-sequence-builder analyze-audio .\song.mp3 --output-json .\song.analysis.json --plot .\song.analysis.svg
```

Both output paths must be new files. The source audio is never modified.

For songs counted in 3 (waltz time), add `--beats-per-bar 3`. The default is 4. Meter is not detected automatically.

## 2. Score it against your own timing grids

Use a sequence for the same audio file that contains free timing grids you placed or corrected by ear. Pass the grid names exactly as they appear in the Sequencer:

```powershell
uv run lor-sequence-builder evaluate-analysis --analysis .\song.analysis.json --sequence .\song.loredit --beats-grid "Beats" --bars-grid "Bars" --sections-grid "Sections"
```

Any of the three grid options may be omitted. The sequence is opened read only. If a name is wrong, the error lists the grids that exist. If two grids share a name, rename one so the reference is unambiguous.

Each line reports how many of your marks were matched, how many events the analyzer produced, and precision, recall, and F-measure:

- **Beats and bars** count as matched within 70 ms, the standard tolerance for beat tracking.
- **Sections** count as matched within 2 seconds.
- **Precision** is the share of the analyzer's events that landed on one of your marks. **Recall** is the share of your marks that the analyzer found. **F-measure** combines them.

Grid quality matters. A grid made by an automatic tool and never corrected may drift; score against the grid you trust.

If beats score well but bars score near zero, check whether your bar grid is offset by a whole beat. A bar grid built by counting every fourth beat mark from the wrong starting beat is shifted for the entire song. Shifting the analyzer's downbeats by one beat and re-scoring makes this visible.

## 3. Acceptance targets

| Measure | Target | What it means |
|---|---|---|
| Beats F-measure | ≥ 0.85 | Beat markers sit on the beats you hear |
| Bars F-measure | ≥ 0.85 | Bar starts land on the musical "one" |
| Section recall | Reported, no gate | Section placement is partly taste; two grids by the same person can disagree |

Review at least three contrasting songs: one fast and percussive, one slower, and one with tempo or arrangement changes.

## 4. Read the plot

- **Blue line:** one-second RMS energy (loudness), not musical importance.
- **Green lines:** beats from the dynamic-programming beat tracker.
- **Purple lines:** downbeats (bar starts), chosen where harmony changes most often, assuming four beats per bar. Below four bars of evidence, or with no clear harmonic pattern, the first beat is used and confidence is near zero.
- **Amber marks:** onsets (audible attacks).
- **Teal dashed lines:** section candidates. Structural candidates come from self-similarity plus loudness change at bar starts; energy candidates come from broad loudness transitions. Neither carries verse/chorus labels.
- **Red lines:** sustained near-silence, including leading silence.

## 5. Confidence values

All confidence values are heuristic and uncalibrated. Treat them as relative evidence, not probabilities.

- **Tempo confidence:** the share of the song whose local tempo agrees with the reported tempo (or its half/double). Low values suggest tempo changes or an ambiguous pulse.
- **Beat confidence:** how much stronger the onsets on the beats are than the onsets halfway between them. Strong off-beat accents lower it.
- **Downbeat confidence:** how clearly one bar position wins on harmonic change.

## Privacy

Do not commit audio, real show files, or analysis outputs from copyrighted songs. The JSON includes the source file name and SHA-256 but no audio content.

## Current limitations

- One dominant tempo per song; tempo changes lower tempo confidence rather than being tracked.
- Half-time and double-time readings describe the same pulse and cannot always be distinguished.
- Downbeats use the configured beats per bar (4 by default); meter is not detected.
- Loosely swung recordings can lower beat agreement, and songs whose harmony does not mark the bar give low downbeat confidence.
- Section candidates are not labelled and agree only moderately with human section marks.
- Vocals, syllables, instruments, and lyrics are not detected.
