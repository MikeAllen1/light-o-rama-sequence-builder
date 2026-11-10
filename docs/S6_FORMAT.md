# S6 Native Sequence Format

## Verified facts

Light-O-Rama's official documentation establishes the following:

- Musical and animation sequences in S5 and S6 use the `.LOREDIT` extension.
- Licensed Light-O-Rama sequence files use a standard XML save format.
- Light-O-Rama explicitly notes that technically advanced users can build tools that edit these XML files, while warning that small structural mistakes can make a sequence unreadable.
- The Sequencer can export legacy `.LMS` and `.LAS` formats, but these are not the native S5/S6 save format.

Official references:

- [Feature Comparison — Full Access XML Data Storage](https://info.lightorama.com/help/feature_comparison.htm)
- [Concepts — Sequences](https://info.lightorama.com/help/concept_sequences.htm)
- [Upgrading LAS/LMS Sequences](https://info.lightorama.com/help/upgrading_sequences.htm)

## What remains to be learned

The public documentation confirms XML but does not provide a complete current S6 schema. We must learn and test:

- Root element and required root attributes
- Version and compatibility metadata
- How the sequence embeds or references its preview
- Prop, group, and channel identifiers
- Timing grids and timing markers
- Musical effects and effect parameter encoding
- RGB and pixel element representation
- Motion-effect data and external file references
- Audio/media references and relative path behavior
- How S6 handles unknown, missing, or optional fields

Do not invent missing fields or assume the older LMS structure is interchangeable with LOREDIT.

## Required S6-created reference files

Create small test sequences in the installed S6 application and save them normally as `.LOREDIT` files. Use a separate test preview and short or silent media where practical.

1. **Minimal musical sequence** — one simple prop, a few intensity events, and a few timing marks.
2. **RGB sequence** — one RGB prop with color changes and multiple effect types.
3. **Multi-prop sequence** — several props, groups, and different element types.
4. **Motion-effect sequence** — include a motion effect if the installed S6 license supports it.

Keep each original S6 file unchanged. Place sanitized copies under a local `tests/fixtures/` directory for analysis. Do not commit copyrighted music, personal media, or private preview details.

## Format implementation gate

The native writer is ready to be implemented only when:

- The required XML structure is understood from the reference files.
- A generated minimal sequence opens in S6 without a repair or conversion prompt.
- The saved file can be reopened and retains its props, timings, and effects.
- RGB and motion effects pass their corresponding fixture tests.
- The exporter does not silently discard unsupported information.

Until these conditions are met, the `inspect` command is diagnostic only. It does not modify sequence files.
