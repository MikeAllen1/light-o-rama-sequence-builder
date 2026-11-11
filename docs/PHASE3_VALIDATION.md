# Phase 3: one-download S6 validation

This is the quick human check for the Phase 3 walking-skeleton output.

## Download and run

1. Open the repository's [Phase 3 Validation Package workflow](../../actions/workflows/phase3-validation-package.yml).
2. Open the latest successful run and download the `Phase3-S6-Validation` artifact.
3. Extract the ZIP and double-click `Phase3-Test.loredit`.
4. In Light-O-Rama S6, press Play and watch the sequence preview.

That's the entire test. You do not need Python, uv, PowerShell, the CLI, or the Timeline JSON.

## What should happen

The generated native S6 v15 sequence should open, and its supported sample props should pulse at a steady 60 BPM. The ZIP also contains `Phase3-Test.timeline.json` for engineering diagnostics; it is not needed for the playback check.

## Important limitation

The committed preview/template pair is fictional and synthetic. This test validates that the generated native file opens in S6 and that its sequence preview animates. It does **not** validate or activate physical controllers, lights, or channel assignments. Hardware validation requires a separate owner-run test with the matching display configuration; keep real display files local and out of the repository.

## If something fails

Reply with which step failed and attach a screenshot of any S6 error. Keep the ZIP unchanged so the failure can be reproduced.
