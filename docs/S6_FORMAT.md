# Observed S6 LOREDIT format support

## Verified fixture scope

The source for the Phase 1 fixture is a sanitized sequence opened by the project owner in Light-O-Rama S6. The owner confirmed that it opens, has a neutral 51-prop grid with no house background, and plays audio after S6 prompts for the WAV and the owner selects it. The committed test fixture is a gzip-compressed, size-reduced derivative of that approved source: it retains all 48 sequence props, 51 preview prop identities, 81 channels, 8 timing grids, and representative INTENSITY, TWINKLE, and SHIMMER effects. Preview shape geometry is omitted from the reduced test fixture because Phase 1 tests sequence read/write preservation, not preview rendering. The full owner-tested sequence is not committed. The fixture uses the relative placeholder `musicFilename="synthetic_source.wav"`; the WAV is not committed.

Observed values in the source fixture:

- XML root element: `sequence`
- `saveFileVersion`: `15`
- `AppVersion`: `6.6.0.12`
- `totalCentiseconds`: `20925`
- `PreviewClass`: 51 `PropClass` elements
- `SequenceProps`: 48 `SeqProp` elements
- `TimingGrids`: 8 child elements
- Sequence effects and unknown XML sections are retained as opaque XML.

## Reader/writer contract

- Only `saveFileVersion="15"` is accepted. Other versions fail explicitly until verified against fixtures and S6.
- XML is parsed with `defusedxml`; DTD/entity declarations are rejected.
- The document is preserved as an XML tree. The writer does not reconstruct, normalize, or interpret unknown sections.
- The writer creates a new file and refuses to overwrite either the source or an existing destination.
- Semantic round-trip tests compare the parsed XML tree, not whitespace or XML declaration formatting. The compressed test fixture is expanded into a temporary `.loredit` file by the tests.

## Not established

This fixture establishes one working S6 6.6.0.12 / save-file-version-15 example. It does not establish compatibility with every S6 release, every v15 sequence feature, or older/newer save-file versions. The writer has not been verified against sequences containing constructs absent from this fixture. The CLI does not yet generate or edit effects; it only inspects and loss-preservingly rewrites a sequence document.

## Sequence-prop / preview referential integrity

The owner-tested source sequence exposed an S6 load warning when a `SequenceProps/SeqProp` record had an ID absent from `PreviewClass/PropClass`. S6 warned that the prop would be removed on save. The earlier source sequence contained one such record (`Fixture Prop 049`), with no child channels. It was removed from the sanitized fixture only. The reader now rejects any sequence prop whose ID is absent from the embedded preview. Preview-only props are allowed: the observed source contains 51 preview props and 48 sequence props. This is an observed compatibility rule, not a claim that every S6 file format version has identical constraints.
