# Development Roadmap

This roadmap follows the phase order and acceptance gates in [PLAN.md](PLAN.md). Every phase below is built, merged and shipped in the Windows app (latest: [v0.1.10](https://github.com/MikeAllen1/light-o-rama-sequence-builder/releases/latest)); every phase issue is closed. Where a box is unticked, only the owner's formal sign-off is outstanding.

- [x] Phase 0 — Repository scaffold and CI
- [x] Phase 1 — Native S6 LOREDIT v15 reader/writer; owner confirmed the round-trip file opens in S6
- [x] Phase 2 — Standalone/embedded LORPREV parser, prop groups, channel-address provenance, and hardening; merged in PR #6
- [x] Phase 3 — Fixed-tempo Timeline walking skeleton; owner confirmed the generated sequence opens and renders in S6
- [x] Phase 4 — Audio analysis; librosa rework accepted; swing and rubato are a known limitation (experimental vocal-guided beats, off by default)
- [x] Phase 4b — Scratch-built native sequence writer (no template required); owner S6 open-test passed
- [x] Phase 5 — Prop classifier and `analyze-preview`; owner confirmed on a real display
- [x] Phase 6 — Rules engine and user-profile layering
- [x] Phase 6b — Optional "any specific requirements?" step, remembered per display
- [ ] Phase 7 — Section-aware choreography planner v1 (Issue #38). Shipped; the owner has played generated shows of their own songs in S6 since 2026-11-11, and fades, `TWINKLE` and `SHIMMER` were confirmed in S6. Formal sign-off not yet recorded.
- [ ] Phase 8 — Vocal separation, syllable timing, and singing faces (Issue #43). Shipped; owner playback of singing faces on real vocals not yet recorded.
- [ ] Phase 9 — Planner v2: motifs, call and response, signature moments, dynamics, styles, yard view (Issue #52). Shipped and tuned through several rounds of owner review against the owner's own and WOW Lights sequences; formal sign-off not yet recorded.
- [x] Phase 10 — Reports, packaging, documentation, and installation polish (Issue #60); the owner installs and uses the Windows app
- [x] Phase 11A — Browser sequencing workspace (Issue #47); real-sequence acceptance passed on 2026-11-13
- [x] Phase 11B — Effect editing, checked export, and music review with a tempo map (Issue #49)
- [x] Final delivery — Windows desktop app, installer and portable zip, published on GitHub releases from a tag; the owner installs and uses it

## Still open

- **Owner sign-off** for Phases 7, 8 and 9 (above).
- **Code signing** for the Windows installer, so Windows stops warning about it. It needs the owner's Azure Trusted Signing account.
- **Vocal-guided beats** (swing and rubato songs) stay experimental and off by default until they help on real songs.
- Out of scope: pixel (RGB) and DMX props, controller upload, and live hardware playback.

A phase is complete only when its issue acceptance criteria, automated checks, required owner verification, PR merge, and explicit approval are all satisfied. See [PLAN.md](PLAN.md) for the full scope and progress log.
