# Rules and display requirements

Every choreography Timeline is checked before a sequence is written. The writer runs the checks itself, against the same preview the sequence is built from, so a Timeline that breaks an error-level rule never reaches the `.loredit` file. The rule report is always written, so you can see why.

## Outcomes

Each rule and requirement reports one of:

| Outcome | Meaning |
| --- | --- |
| `PASS` | It applied and nothing broke it. |
| `FAIL` | An error. Each finding names the prop, channel and time (`m:ss.cc`, as S6 shows it). The sequence is not written. |
| `WARN` | A warning finding. The sequence is still written; the finding is in the report. |
| `N/A` | The display or song has nothing the rule is about (no singing face, no falls, vocals not analyzed yet). This is never counted as passed. |
| `OFF` | A profile turned it off. |

Rules never repair the choreography.

## Built-in rules

These ship in `src/lor_sequence_builder/rules/default.yaml` and apply to every display.

| Rule id | What it checks | Default |
| --- | --- | --- |
| `effects_well_formed` | Effects start before they end, sit inside the song, use intensities 0 to 100; fades change intensity and other effects hold one. | error, locked |
| `known_props_and_channels` | Every effect uses a prop from the preview, a channel that prop has, and a prop that can be sequenced (not linked to a master, verified channel layout). | error, locked |
| `no_overlapping_effects` | No two effects overlap on one channel. | error, locked |
| `movements_complete` | A chase, fill or fall reaches every prop it lists, in order, inside its time span. | error |
| `chases_follow_layout` | Chases and fills across several props follow the preview: row order, or left/right/up/down by position. | error |
| `falls_go_down` | Falls run top to bottom, by prop height or, within one prop, by the string start location. | error |
| `face_outline_with_mouth` | Whenever a mouth is on, the face outline is on. Applies only to faces that have a separate outline prop and mouth prop. | error |
| `mouths_only_during_vocals` | Mouths move only while someone is singing. Not applicable until vocal analysis exists (Phase 8). | error |
| `single_color_only_where_possible` | A specific color is asked only of a prop that can show it alone (never of a combined-color strand). | error |
| `motion_stops_at_hard_stops` | No movement runs through a hard stop in the music. | error |
| `not_everything_at_once` | Warns when at least `max_share` of all channels are on for longer than `max_seconds`, outside `allow_sections`. | warning |

Locked rules protect the sequence file itself and cannot be relaxed or turned off.

Face parts are recognized by words in their prop names: `outline_names` (default `[outline]`) and `mouth_names` (default `[mouth, lips]`). A part named like a mouth is always a mouth. A face drawn as a single prop has no separate outline, so the outline rule reports `N/A` for it.

## Your own profile

A profile is a YAML file you pass with `--rules`. Repeat `--rules` to stack several; later files win.

```yaml
schema_version: rules-1.0
name: My display
description: Optional text.

rules:
  not_everything_at_once:
    max_seconds: 12
  falls_go_down:
    severity: warning

requirements:
  - id: star-always-on
    type: keep_on
    props: {names: [Tree Topper]}
```

Merge behavior:

- The built-in profile always loads first.
- Under `rules:`, only the keys you give change; everything else keeps the value from the layer below.
- `requirements:` are added to those of earlier layers. Reusing an id is an error, not a replacement.
- Unknown keys, unknown rule ids, wrong types, out-of-range values, and duplicate keys fail with a message naming the file and the key.
- `yes`, `no`, `on` and `off` are read as plain words, so `severity: off` works. Only `true` and `false` are booleans.
- The effective merged profile is recorded in every rule report.

### Requirements

Each requirement picks props in exactly one way:

- `{all: true}`
- `{role: arch}`: any role from `analyze-preview` (arch, mini_tree, mega_tree, star, singing_face, icicles, outline, snowflake, decor)
- `{group: Arches}`: an S6 prop group
- `{names: ["Window *", Tree Topper]}`: prop names, case-insensitive, `*` and `?` wildcards

Shared fields are `id`, `type`, `props`, `severity` (default `error`) and `note`.

| Type | Extra fields | Meaning |
| --- | --- | --- |
| `keep_on` | `during` (section names, optional) | Every channel stays lit for the whole song or the listed sections. For a prop with a channel per color, any one color counts. |
| `never_use` | | The props are never lit. |
| `colors_only` | `colors` | The props show only these colors. A combined-color strand cannot be limited and is reported. |
| `max_intensity` | `max` (0 to 100) | The props never go above this intensity. |
| `quiet_during` | `sections` | The props are dark during these sections. |
| `move_direction` | `direction`, `movement` (chase, fill or fall; default chase) | Movements across only these props run in this direction. |

A requirement that matches no sequenceable prop is reported as a warning, because it is usually a typo. Props linked to a master prop are driven through the master, so a requirement on them is reported rather than applied.

See `examples/rules-sample-a.yaml` and `examples/rules-sample-b.yaml` for fictional examples.

## Timeline format

The planner (Phase 7) writes this JSON. You can also write one by hand to try the rules and the writer.

```json
{
  "schema_version": "choreography-1.0",
  "duration_centiseconds": 2000,
  "effects": [
    {"prop_id": "...", "channel_index": 0, "start_centisecond": 100, "end_centisecond": 200,
     "kind": "on", "start_intensity": 100, "end_intensity": 100,
     "color": null, "movement_id": "chase-1"}
  ],
  "movements": [
    {"movement_id": "chase-1", "kind": "chase", "prop_ids": ["...", "..."],
     "direction": "left_to_right", "start_centisecond": 100, "end_centisecond": 300}
  ],
  "sections": [{"label": "verse", "start_centisecond": 0, "end_centisecond": 1000}],
  "hard_stops_centiseconds": [],
  "vocal_regions": null
}
```

- Times are integer centiseconds. `prop_id` is the preview's prop id; `channel_index` counts from 0 in the prop's channel list.
- Effect kinds are `on`, `fade`, `twinkle` and `shimmer`, the effect types seen in native S6 sequences.
- Movement directions are `left_to_right`, `right_to_left`, `top_to_bottom`, `bottom_to_top`, `row_order` and `reverse_row_order`.
- `vocal_regions: null` means vocals were not analyzed; `[]` means the song has none.

## Commands

```powershell
uv run lor-sequence-builder list-rules --rules .\my-display.yaml
uv run lor-sequence-builder check-timeline .\display.lorprev .\plan.json --rules .\my-display.yaml --report .\plan.rules.json
uv run lor-sequence-builder build-from-timeline --preview .\display.lorprev --timeline .\plan.json --music-filename "Song.mp3" --output .\song.loredit --report .\song.rules.json --rules .\my-display.yaml
```

`check-timeline` and `build-from-timeline` exit with 1 when there are rule errors and 2 when an input is invalid. Inputs are never modified, and outputs must be new paths.
