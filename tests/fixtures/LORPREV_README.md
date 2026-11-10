# LORPREV fixture notes

- `default_empty.lorprev` is the owner-supplied 351-byte S6 export. It contains PreviewClass Revision="0", one Scene, an empty PropViews element, and no PropClass elements. It is retained as a negative zero-prop test fixture because it contains no personal display information.
- `synthetic_display.lorprev` is a fictional XML fixture based on the standalone root/container structure observed in the exported default preview and PropClass/shape structures observed in the Phase 1 sequence sample. All IDs, names, channel-grid values, and geometry are fabricated for testing.
- The synthetic fixture has **not** been independently opened/imported by S6. It is parser-development evidence only, not proof that this generated file is accepted by S6.
- Revision 0 is the only standalone preview revision observed so far. No other revision is claimed as supported.
- Controller/channel semantics beyond raw source preservation are not inferred. Values such as ChannelGrid remain raw attributes with provenance.
