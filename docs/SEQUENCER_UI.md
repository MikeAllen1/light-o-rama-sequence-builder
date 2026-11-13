# Browser Sequencing Workspace

## Product boundary

The sequencing workspace runs from a local Python loopback server. `lor-sequence-ui` opens it in a browser; the Windows desktop app opens the same workspace in its own window. Sequencing logic stays in the workspace and the Python engine, never in the desktop layer.

## First release

The workspace opens a native S5/S6 `.loredit` (or S4 `.lms`), whatever its save-file version, and its matching audio, then renders:

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

## Yard view

**Yard view** (toolbar) draws the display above the timeline and lights it at the playhead, so a show can be watched against the music without opening S6. The drawing comes from the preview that S6 keeps inside every sequence:
- Props drawn as lines use their own points; unconnected lines are drawn as pairs.
- Shapes drawn in a box are simplified: arches as arcs, trees as fanned strands from the top, stars, snowflakes (center out), circles, and rectangles for anything else. Rotation is applied.
- Each channel is one part of its prop, in channel order.
- Colors come from the channel grid. Multicolor strings alternate their colors along the strand.

Brightness follows each channel's effects: steady and fading intensity exactly, twinkle and shimmer as a random flicker. Unlit strands stay faintly visible so the layout reads. During playback the view follows the song. Without audio, clicking a time on the tracks shows that moment. New show opens the yard view with every generated show.

It is an approximation for review: S6's own visualizer remains the reference for exact shapes and pixel effects. A sequence without an embedded preview shows a message instead.

## Building a new show

**New show** (or **Build a new show** on the start page) runs the whole generator from the browser, one step at a time:

1. **Your display:** choose the S6 preview (.lorprev). The panel says what it found (for example "4 arches, 1 mega tree, 4 mini trees") and lists any prop it cannot sequence, with the reason.
2. **The song:** choose the audio file; it is analyzed on this computer.
3. **Requirements (optional):** keep props on, never use them, keep them dark during chosen parts of the song, or limit their brightness, chosen from the display's own kinds of props, groups and prop names. With a translator configured (`ANTHROPIC_API_KEY`), they can also be typed in plain English. Requirements are remembered per display in the user's data folder (`%LOCALAPPDATA%\lor-sequence-builder\requirements` on Windows), keyed by the preview's own id, so the next show for the same display starts with them.
   **Make 10-second test** (once the display is chosen) builds a display test that lights each kind of prop in turn, sweeps left to right, then lights everything; **Watch test** plays it on the yard view and **Save test** downloads it with its sound and a list of what should light when.
4. **Generate:** set the audio file name as S6 should find it, choose whether faces sing (needs the vocals add-on), and generate. Every rule is checked; the panel lists the song's parts, the props used and left out, and the planner's notes. **Save show** downloads the `.loredit` straight away; **Plan picture** opens the whole show at a glance; **Open in the workspace** (or **Yard view** in the top bar) loads the sequence with the song and its analysis so it can be reviewed against the music, and **Save sequence** downloads `<song> (generated).loredit`.

The files are kept in a private temporary folder for the session (at most four sessions, two hours each) and deleted when the session ends or the workspace stops. The endpoints accept only same-origin requests on the loopback address, with the same size limits as the command line.

Fine-tuning belongs in S6: the workspace's own editing is for quick fixes and for checking a show against the music.

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

## Music review

The reference lanes can be corrected by ear before sequencing. Beats, bars (downbeats), cymbal crashes, high hits, sections and lyric lines are editable:

| Action | How |
| --- | --- |
| Select | Click a marker or lyric line; the inspector shows its time, status and what is lit there |
| Move | Drag it; it snaps to the targets ticked in the edit bar (Alt places freely) |
| Add | Double-click an empty spot in the lane |
| Delete, confirm | Delete key; Enter or **Confirm** marks an estimate as right |
| Exact time | Type it in the inspector and **Apply** |
| Name a section | Pick Intro, Verse, Pre-chorus, Chorus, Bridge, Instrumental, Breakdown, Solo, Outro or Finale |
| Fix lyrics | Type the corrected words; drag a line or its edges to retime it. Corrected or confirmed lines are verified |
| Tempo map | Confirm two bars, select the earlier one and **Fit bars and beats evenly**: the bars and beats between them are spread evenly at the chosen meter (the bar count defaults to the nearest whole number) |

Every marker carries a status: `auto` (an estimate), `confirmed` (placed or confirmed by you, drawn with a filled diamond) or `fitted` (spread between confirmed bars, a hollow diamond). Lane labels show how many are confirmed (`✓12`). Corrections share the undo history with effect edits.

Fitting one stretch at a time is how tempo changes and rubato passages get an accurate grid: anchor the bars you can hear, fit between them, and leave steady stretches alone. Changing the meter after you start a review does not re-run the analysis; it sets the meter used for fitting.

**Save music review** downloads `<name>.review.json` (`music-review-1.0`): the corrected analysis (still a valid audio-analysis v2.0 report, with the optional `status` and section `label` fields), the reviewed lyrics and the meter. **More ▾ › Open music review** opens it again (enabled once a sequence is open); once a review is loaded, opening the audio does not replace it with a fresh analysis. The generator accepts it in place of an analysis:

```powershell
uv run lor-sequence-builder generate --preview display.lorprev --analysis song.review.json --output song.loredit
```

Section names from the review replace the planner's loudness guesses (and work with requirements such as "quiet during the bridge"); corrected beats, bars, crashes and hits drive the timing. Checked locally on one of the owner's songs (not committed): confirming two bars and fitting eight bars between them, naming a section, saving, and generating from the review.

## Local processing and safety

Run with:

```powershell
uv run lor-sequence-ui
```

The server binds to `127.0.0.1` only. The browser sends selected audio to bounded local endpoints; FFmpeg/librosa analysis and waveform processing run on the user's computer. No audio or preview is sent to a remote service. The original selected audio and LOREDIT remain read-only; an edited sequence is checked by a same-origin local endpoint and downloaded as a new file.

### Guided new-show workflow

The browser can also create a show from a `.lorprev` preview, selected audio, and structured or plain-English requirements. Preview, audio, analysis, generated sequence, picture, and rule report are held in a per-show temporary session. At most four sessions are retained. A session becomes invalid after two hours without activity; its temporary folder is removed on the next session cleanup or server shutdown. Only the latest generated result is retained in a session, so repeated generation does not accumulate output files.

Structured requirements are validated locally and remembered in the user's local application cache. If plain-English requirement translation is configured, only that text and the required preview-derived context are sent to the configured Anthropic API; audio files are not sent. Generation and rule checking remain local. A failed rule check returns its report to the browser rather than presenting an unusable sequence as a successful result.

The browser parser rejects DTD/entity declarations and enforces the 50 MiB, 100,000-element, and 256-level bounds used by the sequence reader. Any save-file version opens: S5/S6 sequences are recognized by their `SequenceProps`, S4 sequences by their flat channel list.

## Analysis limitations

- BPM, beats, downbeats, transients, section candidates, and pauses are estimates with heuristic confidence.
- Meter is selected as 3/4 or 4/4; it is not detected automatically by the current analyzer.
- Section candidates are not labeled as verse or chorus.
- The vocal-region and syllable lanes come from loudness and onsets on vocals-only audio; they are not word timing. Word timing comes from the lyrics track: imported LRC/SRT/VTT, or the optional offline transcription add-on (`uv sync --extra lyrics`, then `lor-sequence-builder lyrics --audio vocals.wav --output song.lyrics.json`), which marks every line and word unverified.
- Crash candidates and the out-of-sync check are heuristics. On the owner's four finished reference shows (checked locally, not committed), 82 to 98% of strong moments had a big lighting change within 40 ms and 2 to 9% were flagged as near misses.
- The workspace can import a saved `vocals-1.0` report; New show splits the vocals itself (Phase 8) when the vocals add-on is installed.

## Follow-on work

1. Musical editing: vocal phrase markers, meter changes within a song, and word-level lyric retiming.
2. Professional workflow: reusable layouts, track visibility/mute, keyboard shortcuts, event inspector, and performance work on larger displays.
3. Code signing for the Windows installer.
