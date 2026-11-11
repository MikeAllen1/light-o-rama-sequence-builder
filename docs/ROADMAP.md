# Development Roadmap

This roadmap follows the authoritative phase order and acceptance gates in [PLAN.md](PLAN.md). It is intentionally aligned to the implementation plan rather than the earlier, superseded feature roadmap.

- [x] Phase 0 — Repository scaffold and CI
- [x] Phase 1 — Native S6 LOREDIT v15 reader/writer; owner confirmed the round-trip file opens in S6
- [x] Phase 2 — Standalone/embedded LORPREV parser, prop groups, channel-address provenance, and hardening; merged in PR #6
- [x] Phase 3 — Fixed-tempo Timeline walking skeleton; merged; owner confirmed the generated sequence opens and renders in S6
- [x] Phase 4: audio analysis; librosa rework accepted for songs in 4; swing and rubato are a known limitation
- [x] Phase 4b: scratch-built native sequence writer (no template required); owner S6 open-test passed
- [x] Phase 5: prop classifier and `analyze-preview` (preview is the only input); owner confirmed on a real display
- [x] Phase 6 — Rules engine and user-profile layering
- [ ] Phase 6b — Optional "any specific requirements?" step, remembered per display
- [ ] Phase 7 — Section-aware choreography planner v1; owner playback gate
- [ ] Phase 8 — Vocal separation, syllable timing, and singing-face choreography; owner playback gate
- [ ] Phase 9 — Planner v2 (motifs, call-and-response, signature moments, dynamics)
- [ ] Phase 10 — Reporting, packaging, documentation, and installation polish

A phase is complete only when its issue acceptance criteria, automated checks, required owner verification, PR merge, and explicit approval are all satisfied. See [PLAN.md](PLAN.md) for the full scope and handoff log.
