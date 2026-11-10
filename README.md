# Light-O-Rama Sequence Builder

**A standalone Windows application for building polished, music-synchronized Light-O-Rama S6 shows.**

The goal is to make it easier to create complete, intentional light-show sequences from a song and an existing Light-O-Rama display. The output target is the native S5/S6 `.LOREDIT` sequence format—not just a legacy LMS export, a collection of unrelated effects, or an add-on pasted on top of an existing sequence.

The project is early-stage. The repository currently contains the initial data model, S6 inspection/display-import tools, audio-analysis groundwork, and automated tests. **Native sequence writing and the finished desktop application are not implemented yet.**

## What I am trying to build

I want to provide a song and my existing S6 display setup, then build a complete sequence that feels like someone deliberately arranged the lights to the music.

The application should understand more than where a beat occurs. It should help identify the structure and character of a song, then use that information to create coordinated lighting across the props in the display.

The intended result should have:

- **Musical structure:** intros, verses, choruses, bridges, builds, breakdowns, transitions, and outros.
- **Accurate timing:** editable beats, downbeats, subdivisions, accents, and phrase boundaries.
- **Musical expression:** changes in intensity, density, color, movement, and pacing that follow the song rather than repeating one pattern.
- **Coordinated props:** groups of props that work together, with individual moments when appropriate.
- **Intentional effects:** attacks, holds, fades, shimmer, twinkle, color changes, and transitions used for a reason.
- **A complete sequence:** effects should be part of the arrangement from the beginning, not disconnected effects added after the sequence is finished.
- **Native S6 output:** a valid `.LOREDIT` file that opens in the Light-O-Rama Sequencer and retains the intended props, timings, and effects.

The application should not simply put a flash on every detected beat. It should distinguish strong musical moments from background rhythm, use repetition deliberately, leave space when the music needs it, and build variation across the song.

## How the application is intended to work

The planned workflow is:

1. **Start a project and load a song.** The user selects an audio file. The application analyzes it locally and records the song duration, tempo candidates, beat candidates, transients/onsets, and relative energy.
2. **Review the musical timeline.** The user can correct the tempo, downbeat, beat grid, subdivisions, and song-section markers. Automated analysis is a starting point, not an unquestionable source of truth.
3. **Load the existing S6 display.** The user selects a sequence saved by Light-O-Rama S6. The application reads the preview and prop definitions, groups, channel mappings, element types, and color capabilities. The original preview information must be preserved when building the output.
4. **Organize the music.** The user identifies or edits song sections such as intro, verse, chorus, bridge, build, breakdown, and outro. The application should help identify likely sections but keep them editable.
5. **Plan the lighting arrangement.** Props and prop groups receive musical roles. For example, some props may carry the main rhythm, others may provide sustained background texture, and others may be reserved for major accents or featured moments.
6. **Generate coordinated effects.** A sequencing engine uses the musical timeline, section, prop capabilities, and arrangement rules to create effects. It should balance repetition with variation and coordinate the display instead of treating every prop as an unrelated track.
7. **Preview and refine.** The user reviews the sequence, adjusts timing and effects, and checks that the result looks intentional at normal playback speed—not just as isolated events in a timeline.
8. **Validate and export.** The application validates timing, prop/channel references, effect parameters, and required S6 structure before writing a native `.LOREDIT` file.
9. **Verify in Light-O-Rama S6.** The exported file is opened in the actual Sequencer. Compatibility is not considered proven until S6 opens it without repair/conversion problems and the saved sequence retains its content.

## Design principles

- **Music first.** Effects should support the song's phrasing, dynamics, and instrumentation.
- **Intent over event count.** More effects do not automatically make a better sequence.
- **Coherence over randomness.** Props should work as a coordinated display, with deliberate variation rather than arbitrary flashing.
- **Editable automation.** Analysis and generated effects are suggestions the user can review and change.
- **Preserve the display.** Existing prop definitions and preview information must not be casually discarded or reconstructed from incomplete assumptions.
- **Native format, verified.** Do not claim S6 compatibility based on well-formed XML alone.
- **Keep the user's files local.** Songs, original sequences, and display previews can contain copyrighted media references, private paths, GUIDs, and personal display details. Reference files should be sanitized before they are ever considered for source control.

## Current implementation

| Area | Status |
|---|---|
| Python package and command-line entry point | Implemented |
| Versioned intermediate sequence model | Initial implementation |
| Basic project validation | Initial implementation |
| S6 `.LOREDIT` XML inspection | Diagnostic reader implemented |
| Extract prop, channel, and group mappings | Initial implementation |
| Audio tempo/beat candidate analysis | Initial implementation |
| Onset/transient candidates and relative energy | Initial implementation |
| Editable musical timeline and song sections | Not implemented |
| Complete display/preview preservation | Not implemented |
| Sequencing and arrangement engine | Not implemented |
| Native S6 `.LOREDIT` writer | Not implemented |
| Windows desktop interface | Not implemented |
| Round-trip verification in S6 | Not implemented |

The XML reader has been tested against a real S6 6.6.0.12 file, but one example does not define the complete file format. See [the S6 format notes](docs/S6_FORMAT.md). Additional small reference files are needed for minimal sequences, RGB props, multi-channel props, and motion effects.

## Development setup

The project currently uses Python 3.11 or later. Windows is the primary target because the finished application is intended to work alongside Light-O-Rama S6.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,audio]"
```

Show available commands:

```powershell
lor-sequence-builder --help
```

Analyze a song:

```powershell
lor-sequence-builder analyze-audio "C:\Path\To\Song.mp3" --output build\audio-analysis.json
```

Extract prop and group information from an S6 sequence:

```powershell
lor-sequence-builder import-display "C:\Path\To\Display.loredit" --output build\display.json
```

Inspect an S6 sequence's XML structure:

```powershell
lor-sequence-builder inspect "C:\Path\To\Display.loredit"
```

Run the tests and lint checks:

```powershell
pytest
ruff check .
pip-audit
```

## Repository layout

```text
src/lor_sequence_builder/
  audio.py       Audio analysis and timing candidates
  cli.py         Command-line interface
  loredit.py     S6 XML inspection and display extraction
  model.py       Format-independent sequence model

tests/           Automated tests using synthetic XML and model data
docs/
  S6_FORMAT.md   Observations and requirements for native S6 compatibility
  ROADMAP.md     Development milestones
.github/
  workflows/     Test and security-analysis workflows
  dependabot.yml Dependency and GitHub Actions update schedule
SECURITY.md      Security reporting and safe-development policy
```

## Native S6 format research

Light-O-Rama documents that licensed sequence files use a standard XML format and that S5/S6 musical and animation sequences use the `.LOREDIT` extension. Legacy `.LMS` and `.LAS` files are not the native S5/S6 saved format.

- [Full Access XML Data Storage](https://info.lightorama.com/help/feature_comparison.htm)
- [Sequence file extensions](https://info.lightorama.com/help/concept_sequences.htm)
- [Upgrading legacy LMS/LAS sequences](https://info.lightorama.com/help/upgrading_sequences.htm)

The format research and the conditions for implementing the writer are documented in [docs/S6_FORMAT.md](docs/S6_FORMAT.md).

## Security and handling of project files

This repository is public. Do not commit passwords, access tokens, API keys, private keys, personal information, copyrighted audio, original show files, or unredacted display previews. Local media and sequence extensions are ignored by Git, but `.gitignore` is not a security boundary—review `git status` and staged changes before every commit.

See [SECURITY.md](SECURITY.md) for vulnerability reporting and the repository's security practices. See [docs/SECURITY_SETUP.md](docs/SECURITY_SETUP.md) for the GitHub settings checklist. GitHub-hosted controls such as Dependabot alerts, secret scanning, push protection, private vulnerability reporting, and branch rules must be enabled in repository settings; workflow files alone cannot turn those switches on.

## Project status

This is an independent, early-stage project. The immediate engineering priority is to learn and preserve the native S6 display/sequence structure, implement a minimal writer based on real S6 reference files, and prove that output in the actual Sequencer. The musical arrangement engine and desktop interface follow that foundation.
