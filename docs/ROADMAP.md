# Development Roadmap

## Phase 1 — Native format foundation

- [x] Establish the project and package structure.
- [x] Define a format-independent sequence model.
- [x] Add structural and timing validation.
- [x] Add a read-only XML inspection command.
- [x] Inspect a real S6 6.6.0.12 LOREDIT file.
- [x] Document the observed XML sections, props, channels, effects, and timing grids.
- [x] Add semantic inspection tests and automated test workflow.
- [ ] Collect additional S6 fixtures for RGB, multi-channel, and motion-effect sequences.
- [ ] Document the supported XML structures and version requirements across fixtures.
- [ ] Implement a minimal native LOREDIT writer.
- [ ] Verify generated files in S6.

## Phase 2 — Music analysis

- [x] Load common audio formats through the optional librosa audio dependency.
- [x] Detect an initial tempo estimate and beat candidates.
- [x] Detect onset candidates and a relative per-second energy curve.
- [ ] Evaluate beat/downbeat candidates against manually verified timing.
- [ ] Identify phrase boundaries and likely song sections.
- [ ] Provide editable timing and section markers.

## Phase 3 — Display and sequencing

- [x] Extract prop, channel, and group mappings from an existing S6 sequence.
- [ ] Preserve and reuse the complete original preview XML when generating a new sequence.
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
