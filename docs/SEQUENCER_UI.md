# Browser Sequencing Workspace

## Product boundary

The sequencing workspace is browser-based during development. It runs from a local Python loopback server and is not a desktop application. Do not introduce Electron, Tauri, or another desktop wrapper until the final delivery stage.

## First release

The first release is a read-only reference workspace. It opens a native S6 v15 `.loredit` and its matching audio, then renders:

- Native prop and channel tracks from `SequenceProps`.
- Group hierarchy from embedded `PreviewClass/PropGroup/member` data.
- Native effect intervals and settings from channel `effect` elements.
- Native free timing grids and fixed grid spacing.
- A waveform decoded from the selected audio file.
- Estimated beat, downbeat, transient, RMS energy, four-bar phrase, section-change, and near-silence lanes from the existing audio analyzer.
- Optional vocal-region and syllable-candidate lanes from `vocals-1.0` JSON.

The shared horizontal extent covers the longer of the sequence and selected audio, so neither the lighting sequence nor an audio tail is silently clipped when their durations differ. Audio analysis timestamps are seconds from the decoded audio start and are mapped onto the same horizontal time axis as the sequence's centisecond timestamps. Native timing grids and inferred audio-analysis events remain visually and semantically distinct.

## Local processing and safety

Run with:

```powershell
uv run lor-sequence-ui
```

The server binds to `127.0.0.1` only. The browser sends selected audio to a bounded local endpoint; the server runs the existing FFmpeg/librosa pipeline in a temporary directory and deletes the upload and outputs afterward. No audio is sent to a remote service. The original selected audio and LOREDIT remain read-only.

The browser parser rejects DTD/entity declarations and enforces the 50 MiB, 100,000-element, and 256-level bounds used by the sequence reader. Only S6 v15 sequences are supported.

## Analysis limitations

- BPM, beats, downbeats, transients, section candidates, and pauses are estimates with heuristic confidence.
- Meter is selected as 3/4 or 4/4; it is not detected automatically by the current analyzer.
- Section candidates are not labeled as verse or chorus.
- The current vocal analysis works on vocals-only audio and estimates vocal regions/syllables from loudness and onsets. It does not recognize words or produce lyric timestamps.
- The current UI can import a saved `vocals-1.0` report; automatic vocal separation is handled by the separate Phase 8 work.

## Follow-on work

1. Editing: select/move/resize effects, create effects, multi-select, undo/redo, snapping to reviewed musical events, and safe new-file export.
2. Musical editing: manual vocal phrase and lyric markers, reviewed beat/bar grids, tempo/meter changes, transient/vocal snapping, and out-of-sync diagnostics.
3. Professional workflow: reusable layouts, track visibility/mute, keyboard shortcuts, event inspector, and performance work on larger displays.
4. Final delivery: desktop wrapper and packaging only after the browser sequencing and editing workflows are complete.
