# LORPREV fixture notes

- `default_empty.lorprev` is a generic zero-prop S6 export retained only as a negative test for the required zero-prop failure.
- `synthetic_display.lorprev` is a small fictional Revision 0 fixture used to test basic element and provenance preservation.
- The exact Light-O-Rama S6 application version used for the Revision 1 export was not recorded with the source artifact and remains an explicit evidence gap; do not assume the Phase 1 LOREDIT test version applies.
- Human import verification: complete. On 2026-11-10, the owner opened the sanitized Revision 1 `.lorprev` fixture supplied for S6 import and confirmed that it loads successfully. This verifies the sanitized preview is accepted by S6.
- `s6_revision_1_export.lorprev.gz` is a base64-encoded gzip transport copy of the owner's fictional standalone `.lorprev` exported by Light-O-Rama S6. Tests decode it to the original XML before parsing. The XML fixture is sanitized by replacing the preview/scene/prop IDs and display/scene names with synthetic values; its 51 props, channel-grid values, shapes, geometry, and other structural source values are retained.
- The Revision 1 S6 export contains 51 props, one scene, one empty `PropViews`, 1,900 geometry points, 46 square props, 5 hexagon props, six shape names, and eight `Channel_per_color` props. It has no controller or group elements; this phase does not invent them.
- `default_empty.lorprev` remains a negative zero-prop test. The runtime-generated Revision 1 test remains supplemental synthetic coverage, not the primary golden fixture.
- Revision 0 and Revision 1 are the only standalone preview revisions covered by current fixtures. Other revisions fail explicitly.
- `ChannelGrid` is exposed as semicolon-delimited entries with comma-separated raw fields; the parser deliberately does not assign field meanings or controller identities. Geometry `<point>` x/y attributes are exposed as typed coordinate values with individual provenance. `MasterPropId` remains a raw source reference. No controller or group nodes were present in the export, so none are synthesized.

