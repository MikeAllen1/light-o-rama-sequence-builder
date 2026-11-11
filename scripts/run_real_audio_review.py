"""Run the packaged CLI against the ten owner-supplied Phase 4 review tracks.

Audio remains outside the repository. The script writes only JSON/SVG reports
and a summary into a new output directory.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

TRACKS = (
    "01. Christmas_Vacation_Intro.mp4",
    "02. Under_The_Christmas_Tree_Kelly_Clarkson.mp3",
    "03. Its_the Most_Wonderful_Time_of_the_Year.mp3",
    "04. Siberian_Sleigh_Ride.mp3",
    "05. Last Christmas.mp3",
    "06. Jingle Bells.mp3",
    "07. Christmas Time Is Here.mp4",
    "08. Deck_The_Halls.mp3",
    "09. Frosty_The_Snowman.mp3",
    "10. You_re_A_Mean_One_Mr._Grinch.mp3",
)


def _run_track(uv: str, audio: Path, output_dir: Path, index: int) -> dict[str, Any]:
    stem = f"{index:02d}"
    json_path = output_dir / f"{stem}.analysis.json"
    svg_path = output_dir / f"{stem}.analysis.svg"
    command = [
        uv,
        "run",
        "--locked",
        "--no-sync",
        "lor-sequence-builder",
        "analyze-audio",
        str(audio.resolve()),
        "--output-json",
        str(json_path),
        "--plot",
        str(svg_path),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=360,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "track": audio.name,
            "status": "cli_execution_error",
            "error": str(exc),
            "json_file": json_path.name,
            "svg_file": svg_path.name,
        }
    result: dict[str, Any] = {
        "track": audio.name,
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "json_file": json_path.name,
        "svg_file": svg_path.name,
    }
    if completed.returncode != 0:
        result["status"] = "cli_failed"
        return result
    if not json_path.is_file() or not svg_path.is_file():
        result["status"] = "missing_output"
        return result
    try:
        report = json.loads(json_path.read_text(encoding="utf-8"))
        analysis = report["analysis"]
        tempo = analysis["tempo"]
        result.update(
            {
                "status": "ok" if report.get("schema_version") == "1.3" else "unexpected_schema",
                "schema_version": report.get("schema_version"),
                "duration_seconds": report["audio"]["duration_seconds"],
                "bpm": tempo["bpm"],
                "tempo_confidence": tempo["confidence"],
                "tempo_candidates": tempo["candidates"],
                "beat_grid_status": analysis["beat_grid_status"],
                "beat_count": len(analysis["beats"]),
                "onset_count": len(analysis["onsets"]),
                "section_candidate_count": len(analysis["section_candidates"]),
                "hard_stop_count": len(analysis["hard_stops"]),
                "ffmpeg_version": report["tool_versions"]["ffmpeg"],
                "python_version": report["tool_versions"]["python"],
                "sha256": report["audio"]["sha256"],
            }
        )
    except (KeyError, TypeError, ValueError, OSError) as exc:
        result["status"] = "invalid_report"
        result["report_error"] = str(exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("dist/phase4-real-audio-cli"))
    args = parser.parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()

    missing = [name for name in TRACKS if not (input_dir / name).is_file()]
    if missing:
        parser.error("Missing required review tracks: " + ", ".join(missing))
    if output_dir.exists() and not output_dir.is_dir():
        parser.error(f"Output path is not a directory: {output_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error(f"Output directory must be new or empty: {output_dir}")
    uv = shutil.which("uv")
    if uv is None:
        parser.error("uv was not found on PATH; install/sync the locked project environment first")
    output_dir.mkdir(parents=True, exist_ok=True)

    results = [
        _run_track(uv, input_dir / name, output_dir, index)
        for index, name in enumerate(TRACKS, start=1)
    ]
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    csv_path = output_dir / "summary.csv"
    columns = (
        "track", "status", "schema_version", "duration_seconds", "bpm",
        "tempo_confidence", "beat_grid_status", "beat_count", "onset_count",
        "section_candidate_count", "hard_stop_count", "ffmpeg_version", "python_version",
    )
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    for item in results:
        print(
            f"{item['track']}: {item['status']} | BPM={item.get('bpm')} | "
            f"beat grid={item.get('beat_grid_status')} | "
            f"beats={item.get('beat_count')} | onsets={item.get('onset_count')}"
        )
    print(f"JSON summary: {summary_path}")
    print(f"CSV summary: {csv_path}")
    failures = [item for item in results if item.get("status") != "ok"]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
