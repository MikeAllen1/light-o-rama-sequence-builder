# S6 Native Sequence Format

## Verified facts

Light-O-Rama's official documentation establishes the following:

- Musical and animation sequences in S5 and S6 use the `.LOREDIT` extension.
- Licensed Light-O-Rama sequence files use a standard XML save format.
- Light-O-Rama explicitly notes that technically advanced users can build tools that edit these XML files, while warning that small structural mistakes can make a sequence unreadable.
- The Sequencer can export legacy `.LMS` and `.LAS` formats, but those are not the native S5/S6 save format.

Official references:

- [Feature Comparison — Full Access XML Data Storage](https://info.lightorama.com/help/feature_comparison.htm)
- [Concepts — Sequences](https://info.lightorama.com/help/concept_sequences.htm)
- [Upgrading LAS/LMS Sequences](https://info.lightorama.com/help/upgrading_sequences.htm)

## Findings from an actual S6 6.6.0.12 file

A user-supplied sequence saved by S6 6.6.0.12 was inspected locally. The original file is intentionally not stored in this repository because it contains display configuration, local machine paths, and media metadata.

The following structural observations are confirmed in that sample:

### Root element

The document root is `sequence`. The sample root includes these format-related attributes:

- `saveFileVersion="15"`
- `AppVersion="6.6.0.12"`
- `totalCentiseconds="20925"`

The sample's duration is therefore 20,925 centiseconds (209.25 seconds). Other root attributes include user, song, local media path, and UI state; those are deliberately omitted from this documentation.

### Top-level sections

The root contains these sections in this order:

1. `PreviewClass`
2. `BeatChannels`
3. `Subsequences`
4. `SequenceProps`
5. `ArchivedProps`
6. `RgbAggregates`
7. `TimingGrids`
8. `BeatView`
9. `PropViews`
10. `MotionPaks`
11. `pictures`

Do not assume every section is optional or required based on one file. Preserve the section ordering and defaults observed in files created by the target S6 version until tests establish otherwise.

### Preview and sequence prop relationship

- `PreviewClass` contains `PropClass` elements.
- Each `PropClass` has an `id` and preview/display attributes such as `Name`, `DeviceType`, `ChannelGrid`, `TraditionalType`, and color settings.
- A `PropClass` can contain a `shape` element with geometry data.
- `SequenceProps` contains `SeqProp` elements.
- A `SeqProp` carries an `id`, `name`, and flags including `EnablePixelChannels` and `OverlayMotionRows`.
- In this sample, 49 sequence props and 51 preview prop definitions were present. Most IDs matched across the two sections, but at least one sequence prop had no corresponding preview definition. The writer must not assume a perfect one-to-one mapping.

### Channels and effects

The sample contains 81 `channel` elements and 33,839 `effect` elements.

The observed hierarchy is:

```xml
<SequenceProps>
  <SeqProp id="..." name="...">
    <channel row="0" col="0" color="0">
      <effect
        startCentisecond="..."
        endCentisecond="..."
        intensity="..."
        settings="INTENSITY" />
    </channel>
  </SeqProp>
</SequenceProps>
```

The example above is an abbreviated structural illustration, not a complete schema or a guaranteed minimal valid file.

Observed effect settings in this sample:

- `INTENSITY`: 33,486 effects
- `TWINKLE`: 274 effects
- `SHIMMER`: 79 effects

Observed effect attributes include:

- `startCentisecond`
- `endCentisecond`
- `settings`
- `intensity`
- `startIntensity`
- `endIntensity`

Effects can use a constant `intensity` or a start/end intensity pair. The sample does not establish the complete parameter model for other effect types.

### Timing grids

`TimingGrids` contains both `TimingGridFree` and `TimingGridFixed` elements.

- Free grids contain child `timing` elements with a `centisecond` attribute.
- Fixed grids use a `spacing` attribute.
- The sample contains eight grids, including beat, bar, section, and sixteenth-note grids.

The application should preserve named grids and their exact timing values. It must not flatten multiple timing grids into a single beat track.

### Views and motion data

The sample also contains `PropViews`, with saved view definitions and `ViewMember` entries. The sample's `MotionPaks` section is empty. This does not establish the schema for motion effects.

## What remains to be learned

One sequence is a useful starting point, not a complete schema. Additional S6-created fixtures are still required for:

- Minimal sequence structure and required empty sections
- RGB props, pixel channels, and RGB effect encoding
- Multi-channel and grouped props
- Motion effects and MotionPak references
- Effect settings and parameters beyond the observed intensity, twinkle, and shimmer examples
- Audio/media references and path behavior
- Required IDs, defaults, version metadata, and S6 round-trip behavior

Do not invent missing fields or assume the older LMS structure is interchangeable with LOREDIT.

## Required additional S6-created reference files

Create small test sequences in the installed S6 application and save them normally as `.LOREDIT` files:

1. **Minimal musical sequence** — one simple prop, a few intensity events, and a few timing marks.
2. **RGB sequence** — one RGB prop with color changes and multiple effect types.
3. **Multi-prop sequence** — several props, groups, and different element types.
4. **Motion-effect sequence** — include a motion effect if the installed S6 license supports it.

Keep each original S6 file unchanged. Place sanitized copies under a local `tests/fixtures/` directory for analysis. Do not commit copyrighted music, personal media, or private preview details.

## Format implementation gate

The native writer is ready to be implemented only when:

- The required XML structure is understood from reference files.
- A generated minimal sequence opens in S6 without a repair or conversion prompt.
- The saved file can be reopened and retains its props, timings, and effects.
- RGB and motion effects pass their corresponding fixture tests.
- The exporter does not silently discard unsupported information.

The current `inspect` command is diagnostic only. It does not modify sequence files.


## Phase 1 reader/writer implementation status

The approved V13 source fixture was sanitized into a neutral 51-prop grid and opened by the owner in Light-O-Rama S6. The owner confirmed that the layout displayed without the house background. The writer-generated round-trip output was also opened in S6 and the owner confirmed it was fine. The audio reference uses the relative placeholder `synthetic_source.wav`; S6 prompts the owner to locate the WAV, which then plays.

The compact automated fixture committed at `tests/fixtures/basic_show.loredit.gz` is a reduced derivative of the approved source. It retains 48 sequence props, 51 preview prop identities, 81 channels, 8 timing grids, and representative INTENSITY, TWINKLE, and SHIMMER effects. Preview shape geometry is omitted from the compact fixture because Phase 1 tests sequence read/write preservation, not preview rendering. The full owner-tested neutral-grid sequence and audio are not committed.

The reader/writer implementation:

- Accepts only `saveFileVersion="15"`; other versions fail clearly.
- Parses XML with `defusedxml`, explicitly forbidding DTDs, entities, and external references.
- Preserves the XML tree opaquely, including sections and attributes it does not interpret.
- Validates sequence-prop IDs against embedded preview prop IDs on both read and write.
- Writes through a temporary file and atomically creates the destination using a same-directory hard link; it refuses to replace existing files.
- Exposes `inspect` and `roundtrip` commands.

The current automated suite has 15 passing tests locally. GitHub CI (pytest, Ruff, strict mypy, dependency audit, and CodeQL) remains the authoritative project check and is pending on the current PR head.
