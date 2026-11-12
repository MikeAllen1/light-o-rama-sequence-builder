# S4 and S5 sequence formats

Structural notes only. They were taken from owner-supplied sequences that are **not**
in this repository; no names, addresses, effects or metadata from them are recorded
here. Tests use invented sequences built in code (`tests/test_lms.py`).

## S5

S5 (seen: `AppVersion="5.6.0.6"`) saves `.loredit` with `saveFileVersion="15"`, the same
version and structure as S6: an embedded `PreviewClass`, `SequenceProps/SeqProp/channel`,
`TimingGrids`, and the same `INTENSITY` effect encoding. S5 sequences are read, inspected
and round-tripped by the existing `.loredit` code with no changes. S5's pixel motion
effects (`settings` strings such as `Mix_Average|...`) are kept as they are; the program
does not generate them.

## S4 (`.lms`, `saveFileVersion="14"`)

There is no preview. The root `sequence` holds:

- `channels/channel`: `name`, `color` (Windows COLORREF, `0x00BBGGRR`), `centiseconds`,
  `savedIndex`, and for an assigned LOR channel `deviceType="LOR"`, `unit`, `circuit`
  (and `network` when it is not the Regular network). Channels with no `deviceType` are
  unassigned placeholders.
- `channel/effect`: `type` (`intensity`, `twinkle`, `shimmer`), `startCentisecond`,
  `endCentisecond`, and either `intensity` or `startIntensity`/`endIntensity`.
- `channels/channelGroupList`: a group with its own `savedIndex`; members are
  `channelGroups/channelGroup/@savedIndex` and may be channels or other groups.
  Channels and groups share one `savedIndex` space.
- `timingGrids/timingGrid`: `saveID`, `type` (`fixed` with `spacing`, or `freeform` with
  `timing/@centisecond` children).
- `tracks/track`: `totalCentiseconds`, `timingGrid` (a `saveID`), `channels/channel/@savedIndex`
  references, and `loopLevels`.
- `animation`: the S4 visualizer grid (`rows`, `columns`, an optional background image
  path), with `row/column/@channel` cells naming a channel by `savedIndex`.

## How the program uses an S4 sequence

- **As the display.** Each assigned LOR channel becomes a one-channel, single-color prop
  whose address is copied verbatim; channel groups become prop groups (nested groups are
  flattened to their channels); the visualizer grid, when present, places each prop.
  Unassigned and non-LOR channels are listed and left dark.
- **As the template for the new show.** The output keeps every channel, group, track and
  the visualizer grid exactly; it replaces the effects, clears freeform timings and loop
  levels, adds a `Sections` freeform grid, and drops `author` and `createdAt`.
- Not verified yet: opening a generated `.lms` in the S4 Sequencer. The owner should
  open one and play it before relying on it.
