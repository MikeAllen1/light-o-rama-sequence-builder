# Singing faces

Faces drawn as separate props — an outline, mouth shapes, eyes — sing along: the mouth opens on each syllable (wider on stronger ones), the eyes blink, the outline stays on while the mouth moves, and the face rests in instrumentals.

Parts are recognized by their names in the preview: `outline`; `mouth` or `lips` with `closed`, `half`, `open` or `o`; `eyes open`, `eyes closed`.

## What it needs

The program has to know where the singing is. Two ways:

- **Word timings:** in New show, step 2, give a WhisperX word file (`.json`) for the song under **Word timings for lip-sync**. Works in every version, including the downloaded apps. With several singers, **Who the faces sing** picks the voice.
- **The vocals add-on** splits the voice out of the song on your computer. Only the version run from the source folder can install it (`uv sync --extra vocals`; large: PyTorch and a 67 MB model, downloaded once). It takes a few minutes per song.

Without either, the mouths stay still, the rest of the face lights with the show, and the report says so.
