# Phase 4 Real-Audio Review

Review date: 2026-11-10  
Branch: `phase-4/real-audio-review`  
Input set: 10 user-supplied tracks (MP3/MP4 audio streams)  
Audio files are not included in this repository.

## Verdict

**Phase 4 is not accepted.** The analyzer completes on all ten inputs, but the results expose material weaknesses in tempo selection, beat-phase confidence, section detection, and transient interpretation. These are directly relevant to downstream choreography. Phase 5 remains blocked.

The current implementation was reproduced against the supplied audio using the same FFmpeg normalization and the repository's deterministic RMS, positive frame-energy-flux, autocorrelation, phase-selection, energy-transition, and near-silence algorithms. The figures below are therefore a source-algorithm reproduction, not a claim that a separately installed CLI binary was executed.

## Per-track results

BPM values are the repository algorithm's global estimates. Beat confidence is the product of its tempo confidence and phase confidence. Onset count is the number of positive frame-energy-flux local peaks, not a count of musical beats or drum hits.

| Track | Duration | Estimated BPM | Tempo confidence | Phase confidence | Beat confidence | Onset candidates | Section candidates | Hard-stop candidates |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Christmas Vacation Intro | 48.6s | 170.69 | 0.6409 | 0.2051 | 0.1314 | 99 | 24.99s | 47.08s |
| Under the Christmas Tree | 230.7s | 98.63 | 0.5523 | 0.0868 | 0.0479 | 720 | 5.00s, 175.92s, 217.90s, 225.90s | 224.75s |
| It's the Most Wonderful Time | 152.6s | 200.09* | 0.1000 | 0.1361 | 0.0136 | 524 | 149.93s | 148.28s |
| Siberian Sleigh Ride | 188.5s | 170.03 | 0.4474 | 0.0630 | 0.0282 | 832 | 3.00s | 185.42s |
| Last Christmas | 208.3s | 118.21 | 0.6319 | 0.0119 | 0.0075 | 797 | 204.91s | 205.56s |
| Jingle Bells | 161.9s | 121.15 | 0.4600 | 0.0699 | 0.0322 | 576 | 159.93s | 156.73s |
| Christmas Time Is Here | 165.8s | 200.09* | 0.1000 | 0.0463 | 0.0046 | 132 | None | 162.23s |
| Deck the Halls | 96.0s | 200.09* | 0.1000 | 0.0203 | 0.0020 | 431 | None | 93.01s |
| Frosty the Snowman | 142.7s | 149.64 | 0.4468 | 0.1451 | 0.0648 | 386 | None | 140.74s |
| You're a Mean One, Mr. Grinch | 151.5s | 159.22 | 0.5479 | 0.0006 | 0.0003 | 340 | 106.95s, 143.93s | 105.25s, 106.45s, 150.38s |

*200.09 BPM is pinned near the configured 200 BPM ceiling; the current analyzer correctly caps tempo confidence at 0.10 for these three tracks. Treat these as boundary-censored estimates, not accepted tempos.*

## Revalidation against the mounted source audio

Reprocessed all ten original user-provided audio streams on 2026-11-10 using FFmpeg normalization and a source-equivalent reproduction of the current branch's deterministic analysis functions. The inputs were the original MP3/MP4 files available in the working session; no audio was committed to the repository. Durations and the derived metrics above were recalculated from those files. This was not an invocation of the installed project CLI, so it is recorded as a source-equivalent reproduction rather than a packaged-CLI integration test.

The re-run corrected a stale value in the earlier baseline table: the three 200.09 BPM boundary estimates now show the 0.10 confidence cap implemented in the current source. Phase confidence is shown separately so the extremely weak beat-grid support is visible rather than hidden inside the product.

## Findings

### P0 — Tempo selection is alias-prone and can pin to the configured ceiling

Three tracks return 200.09 BPM, effectively the 200 BPM upper bound: *It's the Most Wonderful Time*, *Christmas Time Is Here*, and *Deck the Halls*. This is a boundary warning, not evidence that those songs are truly 200 BPM.

A separate onset-envelope tempo analysis (librosa, used only as a diagnostic cross-check and not treated as ground truth) produced approximately 103 BPM, 112–118 BPM, and 96 BPM respectively. The repository result is close to a double-time interpretation for at least two of these tracks. The global estimate also diverges materially on *Under the Christmas Tree* (repository 98.63 BPM versus cross-check 161.5 BPM) and *You're a Mean One, Mr. Grinch* (159.22 versus 107.7 BPM).

The current alias rule selects the shortest local autocorrelation peak that retains at least half the strongest correlation. That rule systematically favors faster aliases when several periodicities are strong. It needs to expose plausible tempo alternatives or abstain when the evidence cannot distinguish them; merely increasing the BPM ceiling would hide the symptom, not solve it.

### P0 — Beat phase is not trustworthy on this sample

All ten tracks have beat-phase confidence below 0.21; six are below 0.05, and *Last Christmas* and *You're a Mean One, Mr. Grinch* are effectively unresolved (0.0075 and 0.0003 beat confidence).

The tempo confidence values (0.45–0.64) look materially healthier than the beat confidence values. The JSON does preserve the distinction, which is good, but a downstream consumer must not treat the tempo estimate as permission to use the beat grid. The planner must receive an explicit unusable/ambiguous beat-grid state or require human confirmation.

### P1 — The onset list is not a musical event map

The analyzer reports 99–832 candidates per track. These are peaks in positive changes between 50 ms frame energies. They are not spectral onsets, drum hits, note attacks, or all musically important accents. Dense tracks produce hundreds of marks, while quieter or legato attacks can be missed. The current field names and plot legend need to keep this limitation prominent; the planner must not blindly map each candidate to a lighting hit.

### P1 — Energy-only section detection is too sparse and poorly localized for arrangement planning

The detector returns zero to four candidates per song. Several songs with obvious internal arrangement changes produce none or only one. Conversely, candidates at 3s, 5s, or near the ending may be intro/outro energy changes rather than useful musical section boundaries. An eight-second rolling comparison and 55% threshold are too blunt to support phrase/section-aware choreography.

This is acceptable as a rough loudness-change diagnostic, but not as section detection. Keep it explicitly labelled as energy transitions and do not use it to label verse, chorus, bridge, or drop.

### P1 — Silence candidates need semantic restraint

Most tracks have a long trailing near-silence candidate, which may simply be encoded track tail. The Grinch track produces two separate internal candidates at 105.25s and 106.45s, illustrating how a pause or quiet passage can be split into multiple candidates. A sustained low-energy interval is not necessarily a hard stop. The current confidence value of 0.8 is fixed and overstates certainty for this use.

### P2 — The current global model cannot represent tempo changes

A single global tempo is expected to drift whenever the arrangement changes tempo or feel. The diagnostic cross-check showed local tempo alternatives on multiple tracks, but local estimates also jump between half/double-time interpretations. Do not add a naive sliding BPM curve and call it solved; local tempo tracking needs continuity constraints, confidence, and alias handling.

## Required Phase 4 follow-up work

1. Replace the shortest-acceptable-autocorrelation-peak rule with tempo-candidate ranking that explicitly evaluates half/double-time aliases. Return alternatives and ambiguity when evidence is insufficient.
2. Make beat-grid usability explicit and separate from tempo confidence. Do not present a low-confidence grid as an ordinary usable beat map.
3. Add tests for octave/half-time aliases, boundary-clamped estimates, sparse/ambiguous accents, and confidence behavior. Synthetic tests must include competing periodicities, not only clean click tracks.
4. Improve section-transition detection or explicitly narrow its contract to coarse energy-change hints. Add tests for gradual builds, drops, breakdowns, and quiet intros/outros.
5. Revisit hard-stop confidence and merge adjacent quiet intervals; distinguish track-tail silence from internal pause candidates where possible.
6. Document onset candidates as coarse energy-flux transients, not musical onsets.
7. Re-run this same ten-track set after changes. Compare against the current baseline and inspect the generated SVGs alongside listening; do not commit the supplied audio.

## Acceptance decision

- CLI/source-algorithm execution: reproduced successfully for all ten audio inputs.
- Real-world musical usefulness: **not accepted**.
- Phase 4 follow-up: required.
- Phase 5: **blocked** until the follow-up is reviewed and the owner explicitly approves the next phase.


## Follow-up implementation in PR #12

The initial report contract introduced in this follow-up was version 1.1 and included an explicit `beat_grid_status`: `unavailable` when no grid is emitted, `ambiguous` when tempo confidence multiplied by phase confidence is below 0.20, and `provisional` otherwise. The CLI prints this status separately from average beat-grid confidence. `provisional` is deliberately not called `usable` or `verified`; the threshold is a conservative routing hint, not a calibrated quality guarantee. Consumers should require review before treating the grid as authoritative.


The first attempted correction replaced the shortest qualifying local autocorrelation peak with the strongest local peak. CI exposed a clear regression: synthetic 120, 140, and 180 BPM material was returned as approximately 60–70 BPM, and the 220 BPM out-of-range case was returned as approximately 109 BPM. The same four failures reproduced on Linux and Windows.

That change has been reverted. The current implementation restores the previous shortest-local-peak heuristic, which avoids the newly introduced slow-tempo regression but retains a known risk of selecting double-time aliases on real music. The configured-range confidence cap remains in place for estimates pinned near a search boundary. The boundary regression test uses a 220 BPM click track with a deliberately narrow 100–110 BPM search range. The existing alias heuristic returns approximately 109 BPM in that range, allowing the test to verify that an estimate pinned near the configured ceiling is marked low confidence. An earlier attempt to test a 180 BPM track with a 180 BPM ceiling was invalid: the heuristic returned 171.51 BPM, outside the boundary guard band.

This rollback did not complete tempo alias selection. The v1.3 recheck below updates timing resolution and confidence behavior, but does not establish a musically correct tempo for every track. The next tempo improvement must compare aliases using additional evidence and preserve ambiguity rather than assuming that either the strongest or shortest autocorrelation peak is always musically correct.


## Production-sequence reference set supplied by the owner

The owner supplied seven finalized 2026 display sequences as examples of the actual production style. These are reference material, not a claim that every event is perfect and not a replacement for the written display rules. They are kept outside the repository because the native files contain the owner's complete preview and channel programming.

| Sequence | Duration | Events | Events/sec | Median event | Active props |
|---|---:|---:|---:|---:|---:|
| Christmas Vacation Intro | 48.57 s | 2,643 | 54.4 | 0.27 s | 48 |
| Merry Christmas | 209.25 s | 35,360 | 169.0 | 0.10 s | 48 |
| Curse of the Ice Queen | 111.49 s | 18,870 | 169.3 | 0.16 s | 47 |
| Underneath the Tree | 230.68 s | 39,506 | 171.3 | 0.18 s | 48 |
| First Snow | 231.69 s | 31,549 | 136.2 | 0.06 s | 47 |
| Christmas Eve / Sarajevo 12/24 | 203.17 s | 46,125 | 227.0 | 0.06 s | 47 |
| Rudolph the Red-Nosed Reindeer | 188.31 s | 20,947 | 111.2 | 0.13 s | 48 |

All seven files contain 49 configured props, with 47–48 showing event activity. The 195,000 total is a count of serialized effect records, not unique musical hits or a quality score. Exact duplicate records occur on Perimeter Lights in First Snow, Christmas Eve / Sarajevo, and Rudolph, so raw counts should be used descriptively rather than as a target. Only Christmas Vacation Intro and Underneath the Tree have matching audio files in the separate ten-track analysis set; the other five are not treated as matched audio/sequence pairs.

The two matched pairs have closely aligned durations: Christmas Vacation Intro is 48.58 s in audio versus 48.57 s in the sequence; Underneath the Tree is 230.66 s in audio versus 230.68 s in the sequence. This confirms duration correspondence, not event-by-event musical alignment.

The sequence files use centisecond timestamps. Their short-event distributions make the previous 50 ms audio-frame hop unsuitable for evaluating the owner's stated approximately 30 ms light lead. The analyzer therefore moves to a 10 ms hop with overlapping 50 ms RMS/energy-flux windows. This is a timing-resolution improvement only; it does not resolve tempo aliases, identify musical sections, or prove that any generated light event is musically correct. The JSON contract is version 1.3 and records both hop and window durations. Tempo estimation now rejects periodicity that explains less than 1% of onset-flux variance (preventing steady-tone window ripple from creating a tempo), and beat-phase confidence explicitly penalizes meaningful half-period accents. All seven production sequences remain owner-authored examples and are not automatically normalized or rewritten by the analyzer.


## v1.3 ten-track recheck

All ten supplied audio streams were reprocessed using an independent source-equivalent reproduction of the v1.3 feature and tempo logic: 50 ms RMS/energy-flux windows at a 10 ms hop, the 1% periodicity-variance floor, and half-period phase ambiguity penalty. This was not an invocation of the packaged CLI, so treat the figures as a reproducible source-equivalent check pending a final packaged-CLI run.

| Track | Duration | Selected BPM | Tempo confidence | Onset candidates | Beat-grid status |
|---|---:|---:|---:|---:|---|
| Christmas Vacation Intro | 48.58 s | 196.12 | 0.6484 | 274 | ambiguous |
| Under the Christmas Tree | 230.66 s | 96.88 | 0.6550 | 2,603 | ambiguous |
| It's the Most Wonderful Time | 152.57 s | 200.45* | 0.1000 | 1,947 | ambiguous |
| Siberian Sleigh Ride | 188.50 s | 167.04 | 0.7317 | 2,973 | ambiguous |
| Last Christmas | 208.25 s | 115.99 | 0.7044 | 1,467 | ambiguous |
| Jingle Bells | 161.94 s | 123.15 | 0.4552 | 1,236 | ambiguous |
| Christmas Time Is Here | 165.84 s | 200.45* | 0.1000 | 415 | ambiguous |
| Deck the Halls | 95.95 s | 193.91 | 0.7038 | 893 | ambiguous |
| Frosty the Snowman | 142.68 s | 148.56 | 0.4931 | 887 | ambiguous |
| You're a Mean One, Mr. Grinch | 151.53 s | 160.81 | 0.5610 | 1,114 | ambiguous |

*200.45 BPM is at the configured upper search boundary and is confidence-capped. The two matched production sequences again agree with their source-audio durations within 0.02 seconds.

The v1.3 phase check leaves all ten beat grids ambiguous. The strongest competing phase, including the half-period alternative, carries at least 46% of the selected phase score on this set. That is evidence that RMS/energy-flux alone cannot reliably decide which recurring accent is the metrical beat; it is not evidence that the songs have no beat. The selected BPM values also remain candidates rather than ground truth. Half/double-time alternatives remain material on several tracks, including Siberian Sleigh Ride, Deck the Halls, and Frosty the Snowman.

The v1.3 changes improve timestamp granularity, suppress steady-tone periodic ripple, expose the selected tempo in the candidate list, and make competing phase evidence more conservative. They do not yet satisfy the tempo-alias acceptance criterion or prove that the analysis is musically actionable. Phase 4 remains open; Phase 5 remains blocked.



## Independent tempo diagnostic cross-check

As a diagnostic only, the ten same Library audio files were also evaluated with librosa 0.11.0's onset-strength beat tracker at 11.025 kHz mono. This is not ground truth and is not used to overwrite the repository result; beat trackers have their own metrical priors and can also choose half-time or double-time interpretations.

| Track | Repository v1.3 BPM | librosa diagnostic BPM | Observation |
|---|---:|---:|---|
| Christmas Vacation Intro | 196.12 | 103.36 | Near double-time disagreement |
| Under the Christmas Tree | 96.88 | 161.50 | Material disagreement |
| It's the Most Wonderful Time | 200.45* | 103.36 | Boundary-censored, near double-time disagreement |
| Siberian Sleigh Ride | 167.04 | 161.50 | Broad agreement |
| Last Christmas | 115.99 | 117.45 | Broad agreement |
| Jingle Bells | 123.15 | 123.05 | Broad agreement |
| Christmas Time Is Here | 200.45* | 117.45 | Boundary-censored, material disagreement |
| Deck the Halls | 193.91 | 95.70 | Near double-time disagreement |
| Frosty the Snowman | 148.56 | 143.55 | Broad agreement |
| You're a Mean One, Mr. Grinch | 160.81 | 107.67 | Material disagreement |

*The repository estimate is at the configured upper search boundary and is confidence-capped.

This independent check broadly agrees with four tracks, flags likely half/double-time interpretation on three, and materially disagrees on three more. It does not tell us which estimate is musically correct. It does confirm that the repository's selected BPM cannot yet be treated as authoritative across this set. The correct acceptance outcome is to retain candidate alternatives and abstain from treating unresolved beat grids as usable, not to force agreement with librosa.


## Packaged CLI recheck procedure

The source-equivalent recheck above is not a substitute for running the installed project entry point. A repeatable harness is now available at `scripts/run_real_audio_review.py`. It invokes the locked `lor-sequence-builder analyze-audio` console command once for each of the ten named tracks, verifies that each run emits schema v1.3 JSON and an SVG, and writes per-track JSON/SVG files plus `summary.json` and `summary.csv`. It does not copy or modify the source audio and refuses to reuse a non-empty output directory.

From the repository root, with the ten original audio files in one folder:

```powershell
uv sync --locked --group dev
python scripts/run_real_audio_review.py --input-dir "C:\\Path\\To\\TenTracks" --output-dir ".\\dist\\phase4-real-audio-cli"
```

The harness uses `uv run --locked --no-sync lor-sequence-builder analyze-audio` internally, so it tests the installed console entry point from the locked project environment rather than calling the analysis function directly. It returns a non-zero exit code if any track fails, produces a missing/invalid report, or emits a schema version other than 1.3. Keep the generated reports outside version control; review the SVGs alongside listening and compare the selected tempo/candidate list with the v1.3 baseline table above.

**Status:** harness added; packaged CLI execution and owner review of the ten generated SVGs remain pending. Do not mark Phase 4 accepted until those results are reviewed and tempo alias behavior is resolved or explicitly abstained from.
