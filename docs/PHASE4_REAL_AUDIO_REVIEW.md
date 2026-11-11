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

| Track | Duration | Estimated BPM | Tempo confidence | Beat confidence | Onset candidates | Section candidates | Hard-stop candidates |
|---|---:|---:|---:|---:|---:|---:|---|
| Christmas Vacation Intro | 48.6s | 170.69 | 0.6409 | 0.1314 | 99 | 25s | 47.08s |
| Under the Christmas Tree | 230.7s | 98.63 | 0.5523 | 0.0479 | 720 | 5s, 176s, 218s, 226s | 224.75s |
| It's the Most Wonderful Time | 152.6s | 200.09 | 0.6033 | 0.0821 | 524 | 150s | 148.28s |
| Siberian Sleigh Ride | 188.5s | 170.03 | 0.4474 | 0.0282 | 832 | 3s | 185.42s |
| Last Christmas | 208.3s | 118.21 | 0.6319 | 0.0075 | 797 | 205s | 205.56s |
| Jingle Bells | 161.9s | 121.15 | 0.4600 | 0.0321 | 576 | 160s | 156.73s |
| Christmas Time Is Here | 165.8s | 200.09 | 0.5607 | 0.0260 | 132 | None | 162.23s |
| Deck the Halls | 96.0s | 200.09 | 0.5337 | 0.0108 | 431 | None | 93.01s |
| Frosty the Snowman | 142.7s | 149.64 | 0.4468 | 0.0648 | 386 | None | 140.74s |
| You're a Mean One, Mr. Grinch | 151.5s | 159.22 | 0.5479 | 0.0003 | 340 | 107s, 144s | 105.25s, 106.45s, 150.38s |

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
