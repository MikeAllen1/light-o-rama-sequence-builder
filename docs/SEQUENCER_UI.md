# Browser Sequencing Workspace

## Product boundary

The sequencing workspace is browser-based during development. It runs from a local Python loopback server and is not a desktop application. Do not introduce Electron, Tauri, or another desktop wrapper until the final delivery stage.

## First release

The workspace opens a native S6 v15 `.loredit` and its matching audio, then renders:

- Native prop and channel tracks from `SequenceProps`.
- Group hierarchy from embedded `PreviewClass/PropGroup/member` data.
- Channel-less sequence entries whose IDs match a native `PropGroup` are treated as group placeholders, not duplicate empty prop tracks; sequenced member props remain nested under the group.
- Native effect intervals and settings from channel `effect` elements.
- Native free timing grids and fixed grid spacing.
- A waveform decoded from the selected audio file.
- Confidence-weighted beat/downbeat candidates, pixel-decimated transient candidates, RMS energy, four-bar phrase, section-change, and near-silence lanes from the existing audio analyzer.
- Optional vocal-region and syllable-candidate lanes from `vocals-1.0` JSON.
- A local-tempo lane (BPM once per second) so tempo changes, rubato intros and swing are visible instead of hidden behind one BPM.
- High-pitched hit (tambourine, sleigh bells, hi-hats) and cymbal-crash-candidate lanes.
- A lyrics track from `lyrics-1.0` JSON or an LRC, SRT or VTT file. Imported text is the user's own; transcribed lines are drawn with dashed outlines and labeled unverified, with a tick at each recognized word.
- Bar numbers on the ruler: from a native `Bars` grid when the sequence has one, otherwise numbered estimated bars (`~12`) from downbeat candidates.
- Click navigation: clicking any lane snaps to the nearest event, moves the playhead there and lists in the inspector the lyric line and its word timings, and how many effects start there and which props are lit.
- A possible-out-of-sync check: strong musical moments (bar starts, crash candidates, the loudest tenth of the transients) whose nearest big lighting change (four or more channels starting together) is 40 to 150 ms away. It reports the evidence and tolerance, not a verdict; chases and subdivisions between beats are not flagged.

The reference lanes are ordered like a DAW arrangement: lyrics and vocals directly under the waveform, then song structure (sections, pauses, phrases), then rhythm (downbeats, beats, tempo, crashes, hits, transients, energy), then the sequence's native timing grids, with the out-of-sync check just above the lighting tracks.

The shared horizontal extent covers the longer of the sequence and selected audio, so neither the lighting sequence nor an audio tail is silently clipped when their durations differ. Audio analysis timestamps are seconds from the decoded audio start and are mapped onto the same horizontal time axis as the sequence's centisecond timestamps. Native timing grids and inferred audio-analysis events remain visually and semantically distinct.

## Editing

Effects can be edited in place; nothing is written until **Export edited copy**.

| Action | How |
| --- | --- |
| Select / add to selection | Click an effect; Shift- or Ctrl-click adds or removes |
| Move | Drag a selected effect; every selected effect moves together (in time) |
| Trim | Drag an effect's start or end edge |
| Create | Drag across an empty part of a channel row, or double-click it (one beat, or 0.5 s) |
| Edit | Inspector: effect type (Intensity, Twinkle, Shimmer), level, fade from/to, exact start and end |
| Delete, duplicate | Delete key; Ctrl+D places a copy right after the selection |
| Copy, cut, paste | Ctrl+C, Ctrl+X, then click a time and Ctrl+V |
| Nudge | Arrow keys: 0.01 s; with Shift, 0.10 s |
| Undo / redo | Ctrl+Z; Ctrl+Y or Ctrl+Shift+Z (300 steps) |
| Retime | Click a flag on the out-of-sync lane, then **Retime the lighting change to this moment**: the effects that start at the flagged change move onto the musical moment, and the effects that led into them end there |

Moves, trims and new effects snap within 8 pixels to the targets ticked in the edit bar: native LOR grids, beats, bars, transients, high hits and crashes, vocal onsets, lyric words, and other effects' edges. Hold Alt to place freely.

Every edit is checked before it is applied: effects may not overlap on a channel, have no length, start before the song or run past the end. A refused edit changes nothing and says why. Overlaps already in the source are left alone; S6 itself sometimes saves an exact duplicate of an effect.

Export rebuilds only the channels that were edited (marked with an amber edge); every other byte of the file is kept as it was, including line endings and S6's ` />` spacing. The local server reads the result with the same safe reader used for every sequence (version, XML limits, prop references) and checks every effect's timing, then the browser downloads it as `<name> (edited).loredit`. The source file is never changed. Exporting without edits gives back a byte-identical file; this was confirmed on the owner's seven finished sequences, checked locally and not committed, along with deleting and duplicating effects in each.

Effects of types other than Intensity, Twinkle and Shimmer keep their own settings; only their timing can be edited. Moving an effect to another channel is not supported yet.

## Local processing and safety

Run with:

```powershell
uv run lor-sequence-ui
```

The server binds to `127.0.0.1` only. The browser sends selected audio to a bounded local endpoint; the server runs the existing FFmpeg/librosa pipeline in a temporary directory and deletes the upload and outputs afterward. No audio is sent to a remote service. The original selected audio and LOREDIT remain read-only; an edited sequence is checked by a second bounded local endpoint (`/api/export`, same-origin only, 50 MiB) and nothing is kept on disk.

The browser parser rejects DTD/entity declarations and enforces the 50 MiB, 100,000-element, and 256-level bounds used by the sequence reader. Only S6 v15 sequences are supported.

## Analysis limitations

- BPM, beats, downbeats, transients, section candidates, and pauses are estimates with heuristic confidence.
- Meter is selected as 3/4 or 4/4; it is not detected automatically by the current analyzer.
- Section candidates are not labeled as verse or chorus.
- The vocal-region and syllable lanes come from loudness and onsets on vocals-only audio; they are not word timing. Word timing comes from the lyrics track: imported LRC/SRT/VTT, or the optional offline transcription add-on (`uv sync --extra lyrics`, then `lor-sequence-builder lyrics --audio vocals.wav --output song.lyrics.json`), which marks every line and word unverified.
- Crash candidates and the out-of-sync check are heuristics. On the owner's four finished reference shows (checked locally, not committed), 82 to 98% of strong moments had a big lighting change within 40 ms and 2 to 9% were flagged as near misses.
- The current UI can import a saved `vocals-1.0` report; automatic vocal separation is handled by the separate Phase 8 work.

## Follow-on work

1. Musical editing: manual vocal phrase and lyric markers, reviewed beat/bar grids, tempo/meter changes, transient/vocal snapping, and out-of-sync diagnostics.
2. Professional workflow: reusable layouts, track visibility/mute, keyboard shortcuts, event inspector, and performance work on larger displays.
3. Final delivery: desktop wrapper and packaging only after the browser sequencing and editing workflows are complete.
