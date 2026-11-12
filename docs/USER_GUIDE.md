# User guide

This guide is for someone with a Light-O-Rama S6 display who wants a show for a song, without programming. Installation is in the [README quick start](../README.md#quick-start-windows-no-programming).

## What you need

- Your display's **S6 preview file** (`.lorprev`). This is the only description of your yard the program uses: every prop, its shape, its channels and where it stands.
- The **song** (MP3, M4A, WAV, FLAC, OGG and other common formats).
- **S6** to play the result, and to fine-tune it if you like.

Nothing is uploaded anywhere. The program runs on your computer and reads your files only when you choose them.

## Your first show

1. Double-click **Start LOR Sequencer**. Your browser opens the workspace.
2. Click **New show**.
3. **Your display:** choose the `.lorprev`. The panel says what it found, for example "7 arches, 14 snowflakes, 1 mega tree", and lists any prop it cannot sequence, with the reason (pixel and DMX props, or props that follow another prop).
4. **The song:** choose the audio file. It is analyzed for beats, bars, sections, high-pitched hits (tambourine, sleigh bells) and cymbal crashes. A three-minute song takes a few seconds to half a minute.
5. **Requirements (optional):** see below. Skip this the first time.
6. **Generate:** check the audio file name (it must match the song's name in S6's audio folder) and click **Generate show**.
7. Click **Show report** and read **Check in the yard**. Click **Plan picture** for the whole show at a glance.
8. Click **Open in the workspace** to watch the show against the music (press play; the lanes above the tracks show the beats, bars and sections it followed), then **Save sequence**.
9. Open the saved `.loredit` in the S6 Sequencer and play it.

To try everything without your own files, run `uv run lor-sequence-builder demo "Demo Show"` in the program folder: it writes an invented yard, an invented song and the finished show.

## How it plans a show

- The song is split into parts (intro, verse, chorus, bridge, outro...) by loudness, and each part gets an energy level. Quiet parts use a few props; loud parts use more and brighter; the last part can use everything.
- Each kind of prop has one job for the whole song, so you can tell what it is following: arches chase on the beat, mini trees trade beats, snowflakes fall (on the high-pitched hits when there are enough of them), a mega tree spins, decorations pulse, outlines and stars are the steady base.
- Groups take turns leading, handing off across the yard. A part that comes back (a second chorus) repeats its look; mid-energy parts trade bars left and right; the phrase before a louder part builds up; crashes flash the display.
- Motion follows how your props are laid out in the preview: rows chase from one end to the other, stacked snowflakes fall top to bottom, little clusters ripple.

Section names (verse, chorus) are guesses from loudness. To name them yourself, use the music review (below).

## Getting better results from your preview

The program reads your preview, so the preview decides how good the show can be.

- **Give props a specific S6 shape** (Arch, Tree, Star, Snowflake...) rather than plain lines. A prop drawn as lines is identified from its name, and one it cannot identify only gets simple pulses. The show report lists props it was unsure about.
- **Group rows in S6** (all the arches in one group, in order). Groups and their order decide chase order.
- **Set the start location** of multi-segment props (mega trees, arches with several segments) so spins and wipes run the right way.
- `uv run lor-sequence-builder analyze-preview display.lorprev --report display.analysis.json` shows, for every prop, what the program thinks it is and why. Fix anything wrong in the S6 Preview Editor and run it again.

## Requirements

Requirements are things the show must do on your display. In **New show**, choose a requirement, the props it is about (a kind of prop, an S6 group, or individual props) and, where needed, the parts of the song or a brightness, then **Add**:

- **Keep on all song:** for example the star.
- **Never use:** a prop that is broken or not up this year.
- **Keep dark during:** for example keep the mega tree dark in the verses.
- **Limit brightness to:** for example the mega tree at 60%.

They are remembered for that display, so the next show starts with them. On the command line, `lor-sequence-builder requirements display.lorprev` asks the same questions, and [examples/requirements](../examples/requirements/README.md) has ready-made profiles to use with `--rules`. With an Anthropic API key set (`ANTHROPIC_API_KEY`), requirements can also be typed in your own words.

## Singing faces

Faces built from separate props (mouth shapes, eyes, outline) sing when the program knows where the singing is. That needs the vocals add-on, which splits the voice out of the song on your computer:

```powershell
uv sync --extra vocals
```

It takes a few minutes per song. Without it, the mouths stay still and the report says so.

## Music review and lyrics

In the workspace, the lanes above the tracks can be corrected by ear: move or add beats, bars, crashes and hits, name the sections (Verse, Chorus, Bridge...), fix lyric words, and fit an even tempo between two bars you confirm. **Save music review** writes a `.review.json`; generating from it (`generate --analysis song.review.json`) uses your corrections and your section names. Lyrics can be loaded from LRC, SRT or VTT files; `uv sync --extra lyrics` adds offline transcription. See [SEQUENCER_UI.md](SEQUENCER_UI.md).

## Fine-tuning

Fine-tune in the S6 Sequencer: it is the full editor. The workspace's own editing is for quick fixes and for checking a show against the music before you open it in S6.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| Something is not set up | Run `uv run lor-sequence-builder doctor` in the program folder. It checks Python, the libraries, FFmpeg, audio decoding, the workspace files and the data folders, and says how to fix each problem. |
| "FFmpeg is required" | Install it: `winget install --id Gyan.FFmpeg -e` on Windows, `brew install ffmpeg` on macOS, `sudo apt install ffmpeg` on Debian or Ubuntu. Open a new window afterwards. |
| "uv" is not recognized | Install uv (README quick start, step 1), then open a new window. |
| The first start is slow | It is installing what it needs once; later starts take seconds. |
| The browser does not open | Open `http://127.0.0.1:8765/` yourself. If that port is busy, run `uv run lor-sequence-ui --port 8780`. |
| S6 plays no music | The sequence names the audio file; it must match the song's name in S6's audio folder. Set it in step 6 of New show (or `--music-filename`). |
| A prop stays dark | The show report's **Your props** table says why: not sequenceable (pixel, DMX, follows another prop), left out by a requirement, or not chosen by the plan. |
| A prop does the wrong thing | It was probably identified as something else. Check it with `analyze-preview`, give it a specific shape in the S6 Preview Editor, and generate again. |
| A chase runs backwards | Check the row's group order and the props' start locations in the preview. |
| Faces do not sing | Install the vocals add-on (above); the report says when it is missing. |

## Privacy

Your previews, songs and sequences stay on your computer. Requirements are remembered in your user data folder (`%LOCALAPPDATA%\lor-sequence-builder` on Windows). The only thing ever sent anywhere is requirement text you type in your own words, and only when you have set up a translator key yourself.
