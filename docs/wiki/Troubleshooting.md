# Troubleshooting

| Problem | What to do |
| --- | --- |
| Windows says "Windows protected your PC" | Click **More info**, then **Run anyway**. The installer is not code-signed yet. |
| macOS says it cannot check the app | **System Settings → Privacy & Security → Open Anyway** (see [Installing](Installing)). |
| The Linux AppImage does nothing | Install FUSE (`libfuse2`, or `libfuse2t64` on Ubuntu 24.04), or run it with `--appimage-extract-and-run`. |
| S6 plays no music | The sequence names the audio file; it must match the song's name in S6's audio folder exactly, ending included. Change it under **Advanced** in step 4 of New show. |
| A prop stays dark | The show report's **Your props** table says why: not sequenceable (DMX, follows another prop, or a pixel prop without **Light the pixel props**), left out by a requirement, or not chosen by the plan. |
| A prop does the wrong thing | It was probably identified as something else. Give it a specific shape in the S6 Preview Editor and generate again. |
| A chase runs backwards | Check the row's group order and the props' start locations in the preview. |
| Faces do not sing | Give word timings in step 2, or install the vocals add-on (see [Singing Faces](Singing-Faces)). |
| The beat feels off on a swing or very loose song | Correct the beats in a music review in the workspace, save it, and generate from it. |
| A button does nothing, or something looks wrong | Click **Copy diagnostics** at the bottom of the start page and paste it into an issue. Read it over first: error lines can name files you chose. |

Still stuck? [Open an issue](https://github.com/MikeAllen1/light-o-rama-sequence-builder/issues/new/choose) with the diagnostics. Please don't attach your own show files, previews or songs to a public issue.
