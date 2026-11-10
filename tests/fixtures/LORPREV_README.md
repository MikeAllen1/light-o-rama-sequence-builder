# LORPREV fixture notes

- `default_empty.lorprev` is a generic zero-prop S6 export retained only as a negative test for the required zero-prop failure.
- `synthetic_display.lorprev` is a small fictional Revision 0 fixture used to test basic element and provenance preservation.
- The Revision 1 golden structure is generated at test time from fictional data. It exercises a 51-prop collection, square and hexagon shapes, multiple TraditionalType values, multi-entry ChannelGrid syntax, shape geometry, and MasterPropId relationships.
- The owner-uploaded Revision 1 preview is used only as private development evidence. It is not copied, committed, or published.
- Revision 0 and Revision 1 are the only standalone preview revisions verified by the current fixtures. Other revisions fail explicitly.
- Controller/channel semantics are not interpreted by this phase. Values such as ChannelGrid and MasterPropId are retained as raw source attributes with provenance.
- The synthetic fixture has not been independently opened/imported by S6. It is parser-development evidence, not proof that this generated fixture is accepted by S6.
