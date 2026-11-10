# Development Roadmap

## Phase 1 — Native format foundation

- [x] Establish the project and package structure.
- [x] Define a format-independent sequence model.
- [x] Add structural and timing validation.
- [x] Add a read-only XML inspection command.
- [ ] Analyze S6-created LOREDIT fixtures.
- [ ] Document the supported XML structures and version requirements.
- [ ] Implement a minimal native LOREDIT writer.
- [ ] Verify generated files in S6.

## Phase 2 — Music analysis

- [ ] Load common audio formats.
- [ ] Detect tempo candidates and beat/downbeat confidence.
- [ ] Analyze onset strength, energy, and frequency bands.
- [ ] Identify phrase boundaries and likely song sections.
- [ ] Provide editable timing and section markers.

## Phase 3 — Display and sequencing

- [ ] Import or map the user's display preview.
- [ ] Model props, groups, element types, and colors.
- [ ] Define musical roles for props and prop groups.
- [ ] Generate coherent phrases, transitions, and coordinated effects.
- [ ] Add density, repetition, and variation controls.

## Phase 4 — Desktop application

- [ ] Build a Windows desktop interface.
- [ ] Add audio and timeline views.
- [ ] Add prop mapping and effect editing.
- [ ] Add sequence preview and validation feedback.
- [ ] Export native S6 LOREDIT files.

## Phase 5 — Quality and compatibility

- [ ] Add fixture-based regression tests.
- [ ] Test generated files in the target S6 release.
- [ ] Test large displays and long sequences.
- [ ] Document supported effects and known limitations.
