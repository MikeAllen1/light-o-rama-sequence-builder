# LORPREV fixture notes

- `default_empty.lorprev` is a generic zero-prop S6 export retained only as a negative test for the required zero-prop failure.
- `synthetic_display.lorprev` is a small fictional Revision 0 fixture used to test basic element and provenance preservation.
- `s6_revision_1_export.lorprev.gz` is a base64-encoded gzip transport copy of the owner's fictional standalone `.lorprev` exported by Light-O-Rama S6. Tests decode it to the original XML before parsing. The XML fixture is sanitized by replacing the preview/scene/prop IDs and display/scene names with synthetic values; its 51 props, channel-grid values, shapes, geometry, and other structural source values are retained.
- The Revision 1 S6 export contains 51 props, one scene, one empty `PropViews`, 1,900 geometry points, 46 square props, 5 hexagon props, six shape names, and eight `Channel_per_color` props. It has no controller or group elements; this phase does not invent them.
- `default_empty.lorprev` remains a negative zero-prop test. The runtime-generated Revision 1 test remains supplemental synthetic coverage, not the primary golden fixture.
- Revision 0 and Revision 1 are the only standalone preview revisions covered by current fixtures. Other revisions fail explicitly.
- Controller/channel semantics are not interpreted by this phase. Values such as `ChannelGrid` and `MasterPropId` are retained as raw source attributes with provenance.

