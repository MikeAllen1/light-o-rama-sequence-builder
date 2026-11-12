from __future__ import annotations

import json
import math
import struct
import tempfile
import threading
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from lor_sequence_builder.ui_server import SequencerRequestHandler

playwright_api = pytest.importorskip("playwright.sync_api")


def _sequence_xml() -> str:
    effects = [
        '<effect startCentisecond="100" endCentisecond="300" settings="INTENSITY" intensity="80" />'
    ]
    effects.extend(
        f'<effect startCentisecond="{index % 9900}" endCentisecond="{index % 9900 + 1}" settings="INTENSITY" intensity="80" />'
        for index in range(1, 40000)
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<sequence saveFileVersion="15" totalCentiseconds="10000" musicTitle="Browser Acceptance" musicFilename="expected-song.wav">
  <PreviewClass id="preview">
    <PropGroup id="group-front" Name="Front Yard">
      <member id="prop-tree" />
    </PropGroup>
  </PreviewClass>
  <SequenceProps>
    <SeqProp id="prop-tree" name="Tree">
      <channel row="0" col="0" color="0">
        {''.join(effects)}
      </channel>
    </SeqProp>
  </SequenceProps>
  <TimingGrids>
    <TimingGridFree name="Beats">
      <timing centisecond="0" />
      <timing centisecond="50" />
      <timing centisecond="100" />
    </TimingGridFree>
  </TimingGrids>
</sequence>"""


def _write_test_audio(path: Path) -> None:
    sample_rate = 44100
    frame_count = sample_rate * 3
    frames = b"".join(
        struct.pack("<h", int(9000 * math.sin(2 * math.pi * 440 * index / sample_rate)))
        for index in range(frame_count)
    )
    with wave.open(str(path), "wb") as audio_file:
        audio_file.setnchannels(1)
        audio_file.setsampwidth(2)
        audio_file.setframerate(sample_rate)
        audio_file.writeframes(frames)


def test_browser_workspace_parses_renders_and_aligns_audio_lanes() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SequencerRequestHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:" + str(server.server_address[1]) + "/"
    try:
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "test-tone.wav"
            _write_test_audio(audio_path)
            with playwright_api.sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.route(
                    "**/api/analyze*",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "report": {
                                    "audio": {"duration_seconds": 3.0},
                                    "analysis": {
                                        "method": "browser-test",
                                        "provenance": "synthetic browser test fixture",
                                        "limitations": [],
                                        "tempo": {
                                            "bpm": 120,
                                            "confidence": 0.8,
                                            "method": "test fixture",
                                        },
                                        "beats": [{"time": 0.5, "confidence": 0.8}],
                                        "downbeats": [{"time": 0.0, "confidence": 0.9}],
                                        "onsets": [{"time": 0.5, "strength": 0.8}],
                                        "energy": [{"time": 0.0, "rms": 0.2}],
                                        "phrase_boundaries": [],
                                        "section_candidates": [],
                                        "hard_stops": [],
                                        "tempo_curve": [
                                            {"time": 0.0, "bpm": 120},
                                            {"time": 1.0, "bpm": 112},
                                            {"time": 2.0, "bpm": 121},
                                        ],
                                        "high_hits": [{"time": 0.25, "confidence": 0.7}],
                                        "crashes": [{"time": 1.0, "confidence": 0.8}],
                                    },
                                },
                                "warning": None,
                            }
                        ),
                    ),
                )
                try:
                    page.goto(url, wait_until="networkidle")
                    page.evaluate("""() => {
                      const original = AudioContext.prototype.decodeAudioData;
                      window.__slowNextDecode = false;
                      AudioContext.prototype.decodeAudioData = function (...args) {
                        if (!window.__slowNextDecode) return original.apply(this, args);
                        window.__slowNextDecode = false;
                        return new Promise((resolve, reject) => setTimeout(
                          () => original.apply(this, args).then(resolve, reject), 1200
                        ));
                      };
                    }""")
                    page.locator("#sequenceFile").set_input_files(
                        {
                            "name": "browser-acceptance.loredit",
                            "mimeType": "text/xml",
                            "buffer": _sequence_xml().encode("utf-8"),
                        }
                    )
                    page.locator("#editor").wait_for(state="visible")
                    assert page.locator("#sequenceTitle").inner_text() == "Browser Acceptance"
                    assert page.locator("#propStat").inner_text() == "1"
                    assert page.locator("#channelStat").inner_text() == "1"
                    assert page.locator("#effectStat").inner_text() == "40,000"
                    assert "Front Yard" in page.locator("#trackLabels").inner_text()
                    assert "Beats" in page.locator("#markerLabels").inner_text()

                    page.locator("#tracksCanvas").click(position={"x": 44, "y": 55})
                    inspector = page.locator("#inspectorContent").inner_text()
                    assert "Tree" in inspector
                    assert "INTENSITY" in inspector
                    page.locator("#editApply").click()
                    assert page.locator("#undoButton").is_disabled()
                    assert "unsaved sequence" not in page.locator("#editStatus").inner_text().lower()

                    # Undoing back to the exact loaded channel arrays must clear the
                    # unsaved indicator; an undone edit is not still pending work.
                    page.locator("#deleteButton").click()
                    assert page.locator("#effectStat").inner_text() == "39,999"
                    page.locator("#undoButton").click()
                    assert page.locator("#effectStat").inner_text() == "40,000"
                    assert page.locator("#editStatus").inner_text() == "No edits"

                    # Changing a property on an effect with a pre-existing timing
                    # overlap is valid; only newly introduced overlaps are rejected.
                    page.locator("#editIntensity").fill("70")
                    page.locator("#editApply").click()
                    assert page.locator("#editStatus").inner_text() != "No edits"
                    assert "effects would overlap" not in page.locator("#analysisMessage").inner_text()

                    initial_width = page.locator("#canvasContent").evaluate(
                        "(element) => element.clientWidth"
                    )
                    page.locator("#zoomSlider").evaluate(
                        """(element) => {
                          element.value = "44";
                          element.dispatchEvent(new Event("input", { bubbles: true }));
                        }"""
                    )
                    zoomed_width = page.locator("#canvasContent").evaluate(
                        "(element) => element.clientWidth"
                    )
                    assert zoomed_width > initial_width

                    page.locator("#audioFile").set_input_files(str(audio_path))
                    # Poll from the test side: the page's script-src 'self' policy
                    # blocks the string predicates that wait_for_function evaluates.
                    page.locator("#analysisMessage").filter(
                        has_text="Audio analysis complete"
                    ).wait_for(timeout=15000)
                    assert "expects the audio file expected-song.wav" in page.locator("#analysisMessage").inner_text()
                    assert not page.locator("#playButton").is_disabled()
                    assert "Beat candidates" in page.locator("#markerLabels").inner_text()
                    assert "RMS energy envelope" in page.locator("#markerLabels").inner_text()
                    assert page.locator("#waveformCanvas").evaluate(
                        "(canvas) => canvas.width > 0 && canvas.height > 0"
                    )

                    # Failed replacement decoding must preserve the active playback,
                    # waveform and analysis rather than blanking the workspace.
                    rejected_audio = Path(directory) / "rejected.wav"
                    rejected_audio.write_bytes(b"not a wave file")
                    page.locator("#audioFile").set_input_files(str(rejected_audio))
                    page.locator("#analysisMessage").filter(
                        has_text="That song could not be played here"
                    ).wait_for(timeout=10000)
                    assert not page.locator("#playButton").is_disabled()
                    assert "Beat candidates" in page.locator("#markerLabels").inner_text()
                    assert page.locator("#waveformCanvas").evaluate(
                        "(canvas) => canvas.width > 0 && canvas.height > 0"
                    )
                    assert page.locator("#audioPlayer").evaluate("(player) => Boolean(player.src)")

                    # A sequence chosen while replacement audio is decoding must not
                    # replace the current workspace or invalidate the audio request.
                    page.evaluate(
                        """() => {
                          const original = AudioContext.prototype.decodeAudioData;
                          AudioContext.prototype.decodeAudioData = function (data) {
                            return new Promise((resolve, reject) => {
                              setTimeout(() => original.call(this, data).then(resolve, reject), 900);
                            });
                          };
                        }"""
                    )
                    page.locator("#audioFile").set_input_files(str(audio_path))
                    page.locator("#sequenceFile").set_input_files(
                        {
                            "name": "should-not-replace.loredit",
                            "mimeType": "text/xml",
                            "buffer": _sequence_xml().encode("utf-8"),
                        }
                    )
                    page.locator("#analysisMessage").filter(
                        has_text="Wait for the selected song to finish loading"
                    ).wait_for(timeout=3000)
                    assert page.locator("#sequenceTitle").inner_text() == "Browser Acceptance"
                    page.locator("#analysisMessage").filter(
                        has_text="Audio analysis complete"
                    ).wait_for(timeout=15000)

                    waveform_pixels = page.locator("#waveformCanvas").evaluate(
                        """(canvas) => {
                          const data = canvas.getContext('2d').getImageData(
                            0, 0, canvas.width, canvas.height
                          ).data;
                          let colored = 0;
                          for (let i = 0; i < data.length; i += 4) {
                            if (data[i] > 190 && data[i + 1] > 130 && data[i + 2] < 140) colored++;  // gold waveform
                          }
                          return colored;
                        }"""
                    )
                    assert waveform_pixels > 0
                    page.locator("#canvasViewport").evaluate("(element) => { element.scrollLeft = 0; }")
                    page.locator("#waveformCanvas").click(position={"x": 88, "y": 45})
                    playhead_left = page.locator("#playhead").evaluate(
                        "(element) => Number.parseFloat(element.style.left)"
                    )
                    assert abs(playhead_left - 88) < 1

                    labels = page.locator("#markerLabels").inner_text()
                    for lane in ("Tempo (local BPM)", "High-pitched hits",
                                 "Cymbal crash candidates", "Possible out-of-sync hits"):
                        assert lane in labels

                    # Auto-analysis is the clean baseline: confirming and undoing
                    # a candidate marker must not leave a phantom unsaved review.
                    page.locator("#markersCanvas").click(position={"x": 44, "y": 11})
                    page.locator("#reviewConfirm").click()
                    assert "unsaved music review" in page.locator("#editStatus").inner_text().lower()
                    page.locator("#undoButton").click()
                    assert "unsaved music review" not in page.locator("#editStatus").inner_text().lower()

                    # Import lyrics while automatic analysis is still pending.
                    # Analysis must still populate the beat lanes and leave the
                    # imported lyrics available to save.
                    previous_audio_url = page.locator("#audioPlayer").evaluate("(a) => a.src")
                    page.evaluate("""() => {
                      const nativeFetch = window.fetch.bind(window);
                      window.__delayNextAnalysis = true;
                      window.fetch = function (input, init) {
                        const url = typeof input === "string" ? input : input.url;
                        if (window.__delayNextAnalysis && url.includes("/api/analyze")) {
                          window.__delayNextAnalysis = false;
                          return new Promise((resolve, reject) => setTimeout(
                            () => nativeFetch(input, init).then(resolve, reject), 1200
                          ));
                        }
                        return nativeFetch(input, init);
                      };
                    }""")
                    page.locator("#audioFile").set_input_files(
                        {
                            "name": "lyrics-before-analysis.wav",
                            "mimeType": "audio/wav",
                            "buffer": audio_path.read_bytes(),
                        }
                    )
                    for _ in range(80):
                        current_audio_url = page.locator("#audioPlayer").evaluate("(a) => a.src")
                        if current_audio_url and current_audio_url != previous_audio_url:
                            break
                        page.wait_for_timeout(25)
                    assert current_audio_url != previous_audio_url
                    page.locator("#lyricsFile").set_input_files(
                        {
                            "name": "song.lrc",
                            "mimeType": "text/plain",
                            "buffer": b"[00:00.50]Hello lights\n[00:00.50]Harmony\n[00:01.50]Second line\n",
                        }
                    )
                    page.locator("#markerLabels").filter(has_text="Lyrics").wait_for()
                    page.locator("#analysisMessage").filter(
                        has_text="Audio analysis complete"
                    ).wait_for(timeout=15000)
                    assert "Beat candidates" in page.locator("#markerLabels").inner_text()
                    assert not page.locator("#saveReviewButton").is_disabled()
                    page.locator("#waveformCanvas").click(position={"x": 88, "y": 45})
                    seconds = page.locator("#audioPlayer").evaluate("(a) => a.currentTime")
                    pixels_per_second = 88 / seconds
                    # Lyrics sit first, right under the waveform.
                    first_lane = page.locator("#markerLabels > div").first.inner_text()
                    assert first_lane.startswith("Lyrics")
                    page.locator("#markersCanvas").click(
                        position={"x": 0.9 * pixels_per_second, "y": 11}
                    )
                    inspector = page.locator("#inspectorContent").inner_text()
                    assert "Hello lights" in inspector
                    assert "Lyric text from an imported file" in inspector
                    assert "prop(s) lit" in inspector

                    # Importing lyrics is unsaved work. After saving the review,
                    # editing and undoing must return to the saved baseline.
                    with page.expect_download():
                        page.locator("#saveReviewButton").click()

                    # A saved review is still authoritative when its meter changes;
                    # the app must preserve its corrections and mark the new meter unsaved.
                    page.locator("#meterSelect").select_option("3")
                    assert "unsaved music review" in page.locator("#editStatus").inner_text().lower()
                    page.locator("#meterSelect").select_option("4")
                    assert "unsaved music review" not in page.locator("#editStatus").inner_text().lower()

                    page.locator("#reviewText").fill("Hello lights revised")
                    page.locator("#reviewApply").click()
                    assert "unsaved music review" in page.locator("#editStatus").inner_text().lower()
                    page.locator("#sequenceFile").set_input_files(
                        {
                            "name": "browser-acceptance-reopened.loredit",
                            "mimeType": "text/xml",
                            "buffer": _sequence_xml().encode("utf-8"),
                        }
                    )
                    page.locator("#analysisMessage").filter(
                        has_text="Loaded 1 native props"
                    ).wait_for(timeout=10000)
                    assert "unsaved music review" in page.locator("#editStatus").inner_text().lower()
                    assert not page.locator("#undoButton").is_disabled()
                    page.locator("#undoButton").click()
                    assert "unsaved music review" not in page.locator("#editStatus").inner_text().lower()

                    # A review edit made while a replacement song is decoding must
                    # receive its own confirmation before the old review is discarded.
                    page.locator("#markersCanvas").click(
                        position={"x": 0.9 * pixels_per_second, "y": 11}
                    )
                    previous_audio_url = page.locator("#audioPlayer").evaluate("(a) => a.src")
                    page.evaluate("() => { window.__slowNextDecode = true; }")
                    page.on("dialog", lambda dialog: dialog.dismiss())
                    page.locator("#audioFile").set_input_files(
                        {
                            "name": "replacement.wav",
                            "mimeType": "audio/wav",
                            "buffer": audio_path.read_bytes(),
                        }
                    )
                    page.wait_for_timeout(150)
                    page.locator("#reviewText").fill("Changed while replacement decoded")
                    page.locator("#reviewApply").click()
                    page.locator("#analysisMessage").filter(
                        has_text="Audio was not replaced"
                    ).wait_for(timeout=10000)
                    assert page.locator("#audioPlayer").evaluate("(a) => a.src") == previous_audio_url
                    assert "unsaved music review" in page.locator("#editStatus").inner_text().lower()

                    # Saving the review keeps its undo command available until a
                    # successful audio replacement makes that history obsolete.
                    with page.expect_download():
                        page.locator("#saveReviewButton").click()
                    assert not page.locator("#undoButton").is_disabled()
                    previous_audio_url = page.locator("#audioPlayer").evaluate("(a) => a.src")
                    page.locator("#audioFile").set_input_files(
                        {
                            "name": "replacement-accepted.wav",
                            "mimeType": "audio/wav",
                            "buffer": audio_path.read_bytes(),
                        }
                    )
                    for _ in range(80):
                        current_audio_url = page.locator("#audioPlayer").evaluate("(a) => a.src")
                        if current_audio_url and current_audio_url != previous_audio_url:
                            break
                        page.wait_for_timeout(25)
                    assert current_audio_url != previous_audio_url
                    page.locator("#analysisMessage").filter(
                        has_text="Audio analysis complete"
                    ).wait_for(timeout=15000)
                    assert page.locator("#undoButton").is_disabled()
                    page.locator("#lyricsFile").set_input_files(
                        {
                            "name": "song.lrc",
                            "mimeType": "text/plain",
                            "buffer": b"[00:00.50]Hello lights\\n[00:00.50]Harmony\\n[00:01.50]Second line\\n",
                        }
                    )
                    page.locator("#markerLabels").filter(has_text="Lyrics").wait_for()

                    # Imported analysis, vocals and lyrics must belong to this song.
                    # A failed import must leave the existing, correct lanes untouched.
                    page.locator("#analysisFile").set_input_files(
                        {
                            "name": "wrong.analysis.json",
                            "mimeType": "application/json",
                            "buffer": json.dumps({"audio": {"duration_seconds": 20.0},
                                                  "analysis": {}}).encode("utf-8"),
                        }
                    )
                    page.locator("#analysisMessage").filter(
                        has_text="different-length recording"
                    ).wait_for()
                    assert "Beat candidates" in page.locator("#markerLabels").inner_text()

                    page.locator("#vocalsFile").set_input_files(
                        {
                            "name": "wrong.vocals.json",
                            "mimeType": "application/json",
                            "buffer": json.dumps({"duration_seconds": 20.0}).encode("utf-8"),
                        }
                    )
                    page.locator("#analysisMessage").filter(
                        has_text="different-length recording"
                    ).wait_for()
                    assert "Beat candidates" in page.locator("#markerLabels").inner_text()

                    page.locator("#lyricsFile").set_input_files(
                        {
                            "name": "wrong.lrc",
                            "mimeType": "text/plain",
                            "buffer": b"[00:10.00]Too late for this song\\n",
                        }
                    )
                    page.locator("#analysisMessage").filter(
                        has_text="extend beyond the selected song"
                    ).wait_for()
                    assert "Lyrics" in page.locator("#markerLabels").inner_text()
                finally:
                    browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
