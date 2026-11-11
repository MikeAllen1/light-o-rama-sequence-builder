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

A sequence saved by Light-O-Rama S6 6.6.0.12 was inspected locally. The source file is not stored in this repository. The observations below describe format structure only; source-specific identifiers, values, counts, and media metadata are intentionally excluded.

The following structural observations are confirmed in that sample:

### Root element

The document root is `sequence`. The root uses format-related attributes including `saveFileVersion`, `AppVersion`, and `totalCentiseconds`. Preserve the values emitted by the target S6 version; do not copy source-specific values into examples or fixtures. Other root attributes may include user, song, local media path, and UI state, and are deliberately omitted from this documentation.

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
- The inspected file showed that sequence props and preview prop definitions do not necessarily form a perfect one-to-one mapping. The writer must validate each reference and must not assume every sequence prop has a corresponding preview definition.

### Channels and effects

The inspected structure contains `channel` elements nested under `SeqProp` elements, with `effect` elements nested under channels.

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

Effect settings observed include:

- `INTENSITY`
- `TWINKLE`
- `SHIMMER`

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
- The inspected file includes multiple named grids, including beat, bar, section, and sixteenth-note grids.

The application should preserve named grids and their exact timing values. It must not flatten multiple timing grids into a single beat track.

### Views and motion data

The inspected file contains `PropViews`, with saved view definitions and `ViewMember` entries. Its `MotionPaks` section does not establish the schema for motion effects.

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

Keep each original S6 file unchanged and local. Do not commit original or sanitized owner/customer files or derivatives. Build separate fictional, hand-authored or runtime-generated synthetic fixtures from non-sensitive structural observations. Do not commit copyrighted music, personal media, or private preview details.

## Broader format support gate

The native writer's initial v15 round-trip is implemented and has passed the owner S6 gate. Broader format support is not established until:

- The required XML structure is understood from reference files.
- A generated minimal sequence opens in S6 without a repair or conversion prompt.
- The saved file can be reopened and retains its props, timings, and effects.
- RGB and motion effects pass their corresponding fixture tests.
- The exporter does not silently discard unsupported information.

The `inspect` command is diagnostic only. The `roundtrip` command writes a new copy; it does not edit the source sequence.


## Phase 1 reader/writer implementation status

The Phase 1 human verification gate was completed: the owner opened the writer-generated round-trip output in S6 and confirmed that it loaded. That local check does not authorize retaining the source sequence or any derivative in the repository. The original owner-derived fixture and its derivatives were removed from the current tree in PR #15. Current automated regression tests use fictional synthetic XML, either hand-authored or generated at test time.

The reader/writer implementation:

- Accepts only `saveFileVersion="15"`; other versions fail clearly.
- Parses XML with `defusedxml`, explicitly forbidding DTDs, entities, and external references.
- Preserves the XML tree opaquely, including sections and attributes it does not interpret.
- Validates sequence-prop IDs against embedded preview prop IDs on both read and write.
- Writes through a temporary file and atomically creates the destination using a same-directory hard link; it refuses to replace existing files.
- Exposes `inspect` and `roundtrip` commands.

Historical Phase 1 verification included passing GitHub Tests and CodeQL checks. The owner separately opened the writer-generated output in S6 and confirmed it loaded. Current regression coverage uses synthetic fixtures; this historical acceptance record is not evidence that source files or derivatives remain in the repository.
