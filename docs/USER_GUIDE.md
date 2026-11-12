# User guide

This guide is for someone with a Light-O-Rama S6 display who wants a show for a song, without programming. Installation is in the [README quick start](../README.md#quick-start-windows-no-programming).

## What you need

- Your display's **S5/S6 preview file** (`.lorprev`). This is the only description of your yard the program uses: every prop, its shape, its channels and where it stands.
- **With S4** (which has no previews): one of your own S4 sequences (`.lms`) instead. Any song you have sequenced for the display will do; only its channels are used. Each channel becomes a prop, channel groups are kept, and the show is saved as a new `.lms` with exactly the same channels. Name channels plainly ("Arch 3", "Mini Tree 2", "Roof") so the program can tell what they are. The 10-second display test is S5/S6 only.
- The **song** (MP3, M4A, WAV, FLAC, OGG and other common formats).
- **S4, S5 or S6** to play the result, and to fine-tune it if you like. S5 previews and sequences work exactly like S6's.

Nothing is uploaded anywhere. The program runs on your computer and reads your files only when you choose them.

## Your first show

1. Double-click **Start LOR Sequencer**. Your browser opens the workspace.
2. Click **New show**. (Or right-click your preview in File Explorer and choose **Build a show with LOR Sequencer**: the app opens with that display already chosen. The installer offers this; S6 stays the program that opens previews.)
3. **Your display:** choose the `.lorprev` (S5/S6) or one of your `.lms` sequences (S4). The panel says what it found, for example "7 arches, 14 snowflakes, 1 mega tree", and lists any prop it cannot sequence, with the reason (pixel and DMX props, or props that follow another prop).
4. **The song:** choose the audio file. It is analyzed for beats, bars, sections, high-pitched hits (tambourine, sleigh bells) and cymbal crashes. A three-minute song takes a few seconds to half a minute.
5. **Requirements (optional):** see below. Skip this the first time.
6. **Generate:** pick a **style** (below), check the audio file name (it must match the song's name in the Sequencer's audio folder) and click **Generate show**.
7. Click **Show report** and read **Check in the yard**. Click **Plan picture** for the whole show at a glance.
8. Click **Save show** to get the `.loredit` file now, or **Open in the workspace** first.Click **Open in the workspace** (or **Yard view** at the top) to watch it: the yard view opens above the timeline, and play lights your yard with the song (the lanes above the tracks show the beats, bars and sections it followed). **Save sequence** saves it from there.
9. Open the saved `.loredit` (S5/S6) or `.lms` (S4) in the Sequencer and play it.

## A whole playlist at once

In New show, after choosing your display (and any requirements and a style), **Choose songs** under **A whole playlist at once** and pick several songs. Each gets its own show, built one after another, with a line saying how it went. **Save all shows** downloads them in one zip with their reports. Each sequence plays its song under the song's own file name, so copy the songs into S6's audio folder as they are. Faces stay still in batch shows; build a song on its own to make them sing. On the command line: `lor-sequence-builder generate-batch --preview display.lorprev --songs "Playlist" --output "Shows"`.

## Check your wiring first: the 10-second display test

After step 3, **Make 10-second test** builds a short sequence that lights your display in a fixed order, so anything dark or out of place points at wiring, a controller address or the preview:

| Time | What lights |
| --- | --- |
| 0.5 to 6.5 s | One kind of prop at a time: outlines, icicles, arches, mini trees, mega trees, stars, snowflakes, faces, decorations. A prop with several channels lights them one after another in channel order, so a strand wired backwards shows. A singing face shows its outline and steps through each mouth. |
| 6.5 to 9.0 s | A sweep across the yard from left to right. |
| 9.0 to 10.0 s | Everything on, then a fade. |

**Watch test** plays it on the yard view. **Save test** downloads a zip with the sequence, its sound (`LOR Display Test.wav`, which goes in S6's audio folder) and a "what to watch" list of when each prop should light. On the command line: `lor-sequence-builder display-test --preview display.lorprev --output "Display Test"`.

To try everything without your own files, run `uv run lor-sequence-builder demo "Demo Show"` in the program folder: it writes an invented yard, an invented song and the finished show.

## How it plans a show

- The song is split into parts (intro, verse, chorus, bridge, outro...) by loudness, and each part gets an energy level. Quiet parts use a few props; loud parts use more and brighter; the last part can use everything.
- Each kind of prop has one job for the whole song, so you can tell what it is following: arches chase on the beat, mini trees trade beats, snowflakes fall (on the high-pitched hits when there are enough of them), a mega tree spins, decorations pulse, outlines and stars are the steady base.
- Groups take turns leading, handing off across the yard. A part that comes back (a second chorus) repeats its look; mid-energy parts trade bars left and right; the phrase before a louder part builds up; crashes flash the display.
- Motion follows how your props are laid out in the preview: rows chase from one end to the other, stacked snowflakes fall top to bottom, little clusters ripple.

### Styles

The same song and display can be arranged with a different character. A style decides what each kind of prop does and what it moves on (a whole phrase, a bar, every other beat, the beat, or the half beat), so the three styles are genuinely different shows, not one show with different brightness:

- **Classic** (default): arches chase on the beat and bounce back in the big parts, decorations take turns, the mega tree spins, a flash opens each louder part.
- **High energy:** motion on the half beat, bouncing chases, outlines that pulse with the beat, a mega tree that fills bar by bar, sharp hits, and a dark beat before each big part so it lands harder. For fast, loud songs.
- **Elegant:** motion on bars and phrases instead of beats. Arches fill and wave, decorations breathe one after another, the mega tree breathes and turns slowly, louder parts swell in, softer brightness, no flashes. For ballads.

In every style, look-alike props (two reindeer, three pillars, a row of snowmen) never do exactly the same thing at the same time; they take turns, ripple or breathe one after another. The show grows as the song goes, so the last chorus is the fullest; Classic and High energy move a returning chorus or verse a new way, while Elegant repeats it. When a song ends on a few big hits, the left side lights on the first, the right on the next and the whole display on the last, then it fades out from the edges inward. Section changes are moved onto four-bar phrase lines unless you marked them yourself in a music review.

The program also listens for three things in the song:

- **The drums.** It separates kick and snare hits. In Classic and High energy, a row of pillars or outlines follows the kick and decorations answer the snare; a song without clear drums uses the beat instead.
- **Unexpected chords.** A bar that leans on notes the rest of the song rarely plays (a borrowed chord, a key change) drops most of the yard low for that bar while the showpiece (the mega tree, or the prop with the most channels) carries the moment.
- **The words.** With timed lyrics, a prop the singer names lights on the word: "tree" lights the trees, "snowman" the snowmen, and any word from a prop's own name ("reindeer", "pillar", "Santa") lights that prop, at most once every four seconds. Lyrics come from a music review saved in the workspace, or on the command line from `--lyrics song.lrc` (LRC, SRT or VTT).

Everything is worked out on your computer; nothing is sent anywhere.

A style never changes which rules the show must pass. On the command line: `generate ... --style energetic`.

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

In the workspace, the lanes above the tracks can be corrected by ear: move or add beats, bars, crashes and hits, name the sections (Verse, Chorus, Bridge...), fix lyric words, and fit an even tempo between two bars you confirm. **Save music review** writes a `.review.json`; **More ▾ › Open music review** opens it again later, and generating from it (`generate --analysis song.review.json`) uses your corrections and your section names. Lyrics can be loaded from LRC, SRT or VTT files; `uv sync --extra lyrics` adds offline transcription. See [SEQUENCER_UI.md](SEQUENCER_UI.md).

## Keyboard shortcuts

In the workspace: **Space** or **K** play and pause, **J** and **L** go back and forward 5 seconds, **Home** goes to the start, **Y** shows the yard view, and **?** lists them all. Everything else can be reached with **Tab**.

## Fine-tuning

Fine-tune in the S6 Sequencer: it is the full editor. The workspace's own editing is for quick fixes and for checking a show against the music before you open it in S6.

## Updating

When a new version is out, the app says so in the bottom corner. Download the installer and run it over the copy you have: it closes the app, replaces it and keeps your settings.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| A button does nothing, or something looks wrong | Click **Copy diagnostics** at the bottom of the start page and paste it into your message or GitHub issue. It has the version, the system checks, your last clicks and recent errors. Home folder paths are shortened, but error lines can name files you chose, so read it over first. The log itself is in `%LOCALAPPDATA%\lor-sequence-builder\logs`. |
| Something is not set up | Run `uv run lor-sequence-builder doctor` in the program folder. It checks Python, the libraries, FFmpeg, audio decoding, the workspace files and the data folders, and says how to fix each problem. |
| "FFmpeg is required" | Install it: `winget install --id Gyan.FFmpeg -e` on Windows, `brew install ffmpeg` on macOS, `sudo apt install ffmpeg` on Debian or Ubuntu. Open a new window afterwards. |
| "uv" is not recognized | Install uv (README quick start, step 1), then open a new window. |
| The first start is slow | It is installing what it needs once; later starts take seconds. |
| The browser does not open | Open `http://127.0.0.1:8765/` yourself. If that port is busy, run `uv run lor-sequence-ui --port 8780`. |
| S6 plays no music | The sequence names the audio file; it must match the song's name in S6's audio folder exactly, ending included (`.mp3`, `.wav`). New show warns under the file name box when they differ. Set it in step 6 of New show (or `--music-filename`). |
| A prop stays dark | The show report's **Your props** table says why: not sequenceable (pixel, DMX, follows another prop), left out by a requirement, or not chosen by the plan. |
| A prop does the wrong thing | It was probably identified as something else. Check it with `analyze-preview`, give it a specific shape in the S6 Preview Editor, and generate again. |
| A chase runs backwards | Check the row's group order and the props' start locations in the preview. |
| Faces do not sing | Install the vocals add-on (above); the report says when it is missing. |

## Recent shows

Every show New show builds is also kept on this computer, and the start page lists the newest 30 under **Your recent shows**: **Open** shows it in the workspace with the yard view (choose **Open audio** to hear it), **Save** downloads the `.loredit` again, **Report** shows its report, and **Remove** deletes it. They live in `%LOCALAPPDATA%\lor-sequence-builder\shows`.

## Privacy

Your previews, songs and sequences stay on your computer. Requirements and recent shows are kept in your user data folder (`%LOCALAPPDATA%\lor-sequence-builder` on Windows). Two things ever reach the internet. When the program starts, it asks GitHub whether a newer version has been published; that request carries nothing about you or your files. If one is out, a note in the corner links to the installer: **Later** skips that version, and **Stop checking** turns the check off (or set `LOR_NO_UPDATE_CHECK=1`). **Check for updates** at the bottom of the start page asks on demand. The other is requirement text you type in your own words, and only when you have set up a translator key yourself.

## The More menu

The workspace's **More ▾** button holds two optional files. You do not need either for a normal show: opening the audio analyzes the song.

- **Open music review**: a `.review.json` you saved with **Save music review** (or a song's `.analysis.json` from the command line). It brings back your corrected beats, sections and lyrics. Available once a sequence is open.
- **Open singing timing**: the `.vocals.json` saved with a show that has singing faces. It adds singing lanes for lining up mouth effects with the words. Available once the song (or its music review) is open.

Hover an item to see what it takes, or what to open first. Choosing the wrong kind of file says which item it belongs to.

