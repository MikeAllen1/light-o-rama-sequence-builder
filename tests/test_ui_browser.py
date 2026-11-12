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
<sequence saveFileVersion="15" totalCentiseconds="10000" musicTitle="Browser Acceptance">
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
                    assert not page.locator("#playButton").is_disabled()
                    assert "Beat candidates" in page.locator("#markerLabels").inner_text()
                    assert "RMS energy envelope" in page.locator("#markerLabels").inner_text()
                    assert page.locator("#waveformCanvas").evaluate(
                        "(canvas) => canvas.width > 0 && canvas.height > 0"
                    )
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

                    page.locator("#lyricsFile").set_input_files(
                        {
                            "name": "song.lrc",
                            "mimeType": "text/plain",
                            "buffer": b"[00:00.50]Hello lights\n[00:01.50]Second line\n",
                        }
                    )
                    page.locator("#markerLabels").filter(has_text="Lyrics").wait_for()
                    # Lyrics sit first, right under the waveform.
                    first_lane = page.locator("#markerLabels > div").first.inner_text()
                    assert first_lane.startswith("Lyrics")
                    seconds = page.locator("#audioPlayer").evaluate("(a) => a.currentTime")
                    pixels_per_second = 88 / seconds
                    page.locator("#markersCanvas").click(
                        position={"x": 0.9 * pixels_per_second, "y": 11}
                    )
                    inspector = page.locator("#inspectorContent").inner_text()
                    assert "Hello lights" in inspector
                    assert "Lyric text from an imported file" in inspector
                    assert "prop(s) lit" in inspector
                finally:
                    browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
