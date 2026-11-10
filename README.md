# LOR S6 Auto Sequencer

A music-aware lighting sequence generation toolkit designed for Light-O-Rama S6.

> Status: early foundation. Native `.LOREDIT` writing is not implemented until the format is verified against real S6-generated files. The project will use a versioned intermediate sequence model and explicit export adapters.

## Goals

- Analyze music structure and timing, not just raw beat detections.
- Generate intentional, coordinated effects that follow musical phrases and arrangement.
- Model display props, groups, colors, and capabilities explicitly.
- Validate timing, overlaps, intensity transitions, and prop assignments before export.
- Preserve a clear path to S6-compatible output using verified formats and fixtures.

## Architecture

1. **Audio analysis** — extract tempo candidates, beat/downbeat candidates, energy, onset strength, and section boundaries.
2. **Arrangement model** — represent intro, verse, chorus, bridge, breakdown, build, and outro as editable musical regions.
3. **Display model** — describe props, prop groups, element types, colors, and sequencing capabilities.
4. **Sequence planner** — produce coordinated effect plans based on musical roles and phrase-level variation.
5. **Intermediate representation (IR)** — store absolute-time events with explicit targets, effect parameters, and provenance.
6. **Validation** — reject malformed timing, unintended gaps, conflicting effects, excessive event density, and unsupported targets.
7. **Export adapters** — initially support a documented interchange format; add S6 export only after its structure is verified using S6-created `.LOREDIT` fixtures or an officially supported route.

## Design principles

- Musical context takes priority over indiscriminate beat flashing.
- Repetition should be intentional, with controlled variation between phrases.
- Effects should have coherent attacks, holds, fades, and transitions.
- No destructive edits to source audio, previews, or existing sequences.
- Generated output must be inspectable and reproducible.
- Never label an export as native S6 unless it opens correctly in S6 and passes fixture-based validation.

## Current format facts

Light-O-Rama documents `.LOREDIT` as the sequence extension for S5 and later, including S6. The Sequencer also provides an explicit **Export as LMS/LAS** operation for legacy formats. Therefore `.LMS` is not the native S6 output format.

References:
- https://info.lightorama.com/help/concept_sequences.htm
- https://info.lightorama.com/help/upgrading_sequences.htm
- https://www.lightorama.com/downloads/6.6.8/help/sequencer_file_menu.htm

## Development status

This repository is currently the project scaffold. No native `.LOREDIT` writer is claimed yet. The next milestone is to collect sanitized sample `.LOREDIT` files created by S6 (simple musical sequence, RGB sequence, and a sequence containing motion effects) and document their structure before implementing the adapter.

## Suggested workflow

1. Create or export a small test sequence in S6.
2. Add sanitized fixtures to a local test-fixture directory (do not commit copyrighted music or private display data).
3. Build and test the intermediate sequence model.
4. Implement and validate each export path against S6.
