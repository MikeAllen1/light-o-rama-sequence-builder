"""One readable report for a generated show.

Written next to the sequence as ``<show>.report.html``: a single page with no
scripts and no outside links that any browser opens. It answers what a person
asks after generating a show:

- What did it use, what did it leave dark, and why?
- Which of my props can it not sequence at all?
- Which of my requirements did it follow?
- Did every rule pass?
- How is the song laid out, and where are the big moments?
- How does the show measure up, and what was fixed?
- What should I check in the yard, because a program cannot see the lights?
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from html import escape

from lor_sequence_builder.classifier import PropClassification
from lor_sequence_builder.planner import LEVEL_NAMES, Plan
from lor_sequence_builder.rules import RuleReport, describe_requirement
from lor_sequence_builder.rules.engine import Display

_ROLE_WORDS = {
    "arch": ("arch", "arches"), "mini_tree": ("mini tree", "mini trees"),
    "mega_tree": ("mega tree", "mega trees"), "snowflake": ("snowflake", "snowflakes"),
    "star": ("star", "stars"), "outline": ("outline", "outlines"),
    "icicles": ("icicle line", "icicle lines"),
    "singing_face": ("singing face part", "singing face parts"),
    "decor": ("decoration", "decorations"), "unknown": ("other prop", "other props"),
}


def _kind(role: str, count: int = 1) -> str:
    singular, plural = _ROLE_WORDS.get(role, (role, role))
    return singular if count == 1 else plural


def _names(names: list[str], limit: int = 10) -> str:
    shown = ", ".join(escape(n) for n in names[:limit])
    return shown + (f", and {len(names) - limit} more" if len(names) > limit else "")


_MOMENT_WORDS = {
    "crash": "Crash flash", "return": "Back from a stop", "build": "Build-up",
    "repeat": "A part returns", "call_and_response": "Call and response",
    "lift": "Louder part begins", "drop": "Dark beat before a louder part",
    "variation": "A part returns, moving a new way", "finale_hits": "Closing hits",
    "departure": "Unexpected chord", "lyric_cue": "Lyric cue",
    "calm_base": "Dark stretch given a calm base",
}

_CHECK_WORDS = {
    "too_much_at_once": "Too much at once", "dead_air": "Dead air",
    "lockstep": "Look-alikes in lockstep", "flat_energy": "Loud vs quiet",
    "repetition": "Same look over and over", "on_the_music": "On the music",
}
_STATUS_WORDS = {"good": "Good", "fixed": "Fixed", "note": "Look at this"}


@dataclass(frozen=True, slots=True)
class ReportInputs:
    title: str
    music_filename: str
    display: Display
    classifications: tuple[PropClassification, ...]
    plan: Plan
    report: RuleReport
    duration_centiseconds: int
    files: dict[str, str]


def _time(centiseconds: int) -> str:
    seconds = centiseconds // 100
    return f"{seconds // 60}:{seconds % 60:02d}"


def _used_ids(inputs: ReportInputs) -> set[str]:
    names = set(inputs.plan.used_props)
    return {p.prop_id for p in inputs.display.props.values() if p.name in names}


def yard_checks(inputs: ReportInputs) -> list[str]:
    """Things to look at in the yard: what a program cannot know from the files."""
    display = inputs.display
    used = _used_ids(inputs)
    checks = [
        (f"In the Sequencer, confirm the sequence plays {escape(inputs.music_filename)}: the "
         "audio file name must match one in its audio folder."),
    ]
    unknown = sorted(c.name for c in inputs.classifications if c.status == "unknown")
    review = sorted(c.name for c in inputs.classifications if c.status == "needs_review")
    if unknown:
        checks.append("The program could not tell what these are, so they only get simple "
                      "pulses: " + _names(unknown) + ". Giving each a specific shape in the S6 "
                      "Preview Editor (Arch, Tree, Star...) lets it do more with them.")
    if review:
        checks.append(f"{len(review)} prop(s) were identified from their name or layout rather "
                      "than a specific S6 shape (" + _names(review, 6) + "); watch that each "
                      "behaves like what it is. analyze-preview lists the evidence for each.")
    segmented = sorted(p.name for p in display.props.values()
                       if p.prop_id in used and p.channel_count >= 3
                       and p.color_kind != "color_per_channel")
    if segmented:
        checks.append("Multi-segment props should spin or wipe in the direction they are drawn: "
                      + ", ".join(escape(n) for n in segmented)
                      + ". If one runs backwards, check its start location in the preview.")
    colored = sorted(p.name for p in display.props.values()
                     if p.prop_id in used and p.color_kind == "color_per_channel")
    if colored:
        checks.append("Props with one color per channel should show the colors the preview "
                      "names: " + ", ".join(escape(n) for n in colored) + ".")
    faces = [p for p in display.props.values()
             if p.role == "singing_face" and p.prop_id in used]
    if faces:
        checks.append("Watch the singing faces: mouths should open on sung syllables and close "
                      "in the gaps, with no two mouth shapes lit at once.")
    rows = {p.row_id for p in display.props.values() if p.row_id and p.prop_id in used}
    if rows:
        checks.append("Chases should run along each row in order from one end to the other, "
                      "with no prop skipped or out of place.")
    limited = [r for r in inputs.report.rule_set.requirements if r.type == "max_intensity"]
    if limited:
        checks.append("Brightness limits from your requirements should look right at night.")
    checks.append("Check from the street that the busiest parts are not too much and the "
                  "quiet parts are not too dark; tell the program what to change with "
                  "requirements, or fine-tune the sequence in the Sequencer.")
    return checks


def render_report(inputs: ReportInputs) -> str:
    plan = inputs.plan
    display = inputs.display
    report = inputs.report
    used = _used_ids(inputs)
    by_name = {p.name: p for p in display.props.values()}
    used_roles = Counter(display.props[pid].role for pid in used if pid in display.props)
    status = ("Every rule passed." if report.ok and not report.warnings else
              f"Every rule passed, with {len(report.warnings)} warning(s)." if report.ok else
              f"{len(report.errors)} rule error(s): this sequence was not written.")

    def table(headers: list[str], rows: list[list[str]]) -> str:
        head = "".join(f"<th>{escape(h)}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
                       for row in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    parts: list[str] = []
    parts.append(f"<h1>{escape(inputs.title)}</h1>")
    summary = ", ".join(f"{count} {_kind(role, count)}"
                        for role, count in sorted(used_roles.items()))
    parts.append(
        f'<p class="lead">{escape(status)} {len(used)} props lit over {_time(inputs.duration_centiseconds)}'
        f" ({escape(summary)}). Audio: {escape(inputs.music_filename)}.</p>")

    parts.append("<h2>Check in the yard</h2><ol>"
                 + "".join(f"<li>{item}</li>" for item in yard_checks(inputs)) + "</ol>")

    parts.append("<h2>The song</h2>")
    parts.append(table(["Part", "Energy", "From", "To"], [
        [escape(s.label), LEVEL_NAMES[s.level], _time(s.start_centisecond), _time(s.end_centisecond)]
        for s in plan.sections]))
    if plan.moments:
        counts = Counter(kind for kind, _ in plan.moments)
        first: dict[str, list[str]] = {}
        for kind, time in plan.moments:
            first.setdefault(kind, []).append(_time(time))
        parts.append("<h3>Big moments</h3>" + table(["Moment", "Times", "When"], [
            [escape(_MOMENT_WORDS.get(kind, kind)), str(counts[kind]),
             escape(", ".join(first[kind][:8]) + (" …" if len(first[kind]) > 8 else ""))]
            for kind in sorted(counts)]))

    if plan.quality is not None:
        parts.append(f"<h2>Quality check: {plan.quality.score}/100</h2>")
        parts.append(table(["Check", "Result", "What we found", "Where"], [
            [escape(_CHECK_WORDS.get(f.check, f.check)), _STATUS_WORDS.get(f.status, f.status),
             escape(f.message), escape(", ".join(_time(t) for t in f.at[:6])
                                       + (" …" if len(f.at) > 6 else ""))]
            for f in plan.quality.findings]))

    parts.append("<h2>Your props</h2>")
    rows = []
    skipped = {s.name: s.reason for s in plan.skipped_props}
    for prop in sorted(display.props.values(), key=lambda p: (p.role, p.name)):
        if prop.prop_id in used:
            state, why = "Used", ""
        elif not prop.sequenceable:
            state = "Not sequenced"
            why = (prop.layout_problem or
                   (f"follows {display.props[prop.linked_to].name}"
                    if prop.linked_to in display.props else ""))
        else:
            state, why = "Left dark", skipped.get(prop.name, "not chosen by the plan")
        rows.append([escape(prop.name), escape(_kind(prop.role)),
                     str(prop.channel_count), state, escape(why)])
    parts.append(table(["Prop", "Kind", "Channels", "In this show", "Why"], rows))
    unused_names = [n for n in by_name if by_name[n].prop_id not in used]
    if unused_names:
        parts.append(f"<p>{len(unused_names)} prop(s) stay dark in this show. Props that "
                     "cannot be sequenced (for example pixel or DMX props, or props driven "
                     "by another prop) are listed with the reason.</p>")

    parts.append("<h2>Your requirements</h2>")
    requirements = report.rule_set.requirements
    if requirements:
        parts.append("<ul>" + "".join(f"<li>{escape(describe_requirement(r))}</li>"
                                      for r in requirements) + "</ul>")
    else:
        parts.append("<p>None: the planner decided everything. Add requirements to keep a "
                     "prop on, never use one, keep props dark in parts of the song, or limit "
                     "brightness.</p>")

    parts.append("<h2>Rules</h2>")
    parts.append(table(["Rule", "Result", "Details"], [
        [escape(r.title), escape(r.status.replace("_", " ")),
         escape("; ".join(f.describe() for f in r.findings[:3]) or r.reason)]
        for r in report.results]))

    if plan.notes:
        parts.append("<h2>Notes from the planner</h2><ul>"
                     + "".join(f"<li>{escape(note)}</li>" for note in plan.notes) + "</ul>")
    if inputs.files:
        parts.append("<h2>Files</h2><ul>" + "".join(
            f"<li><b>{escape(label)}:</b> {escape(name)}</li>"
            for label, name in inputs.files.items()) + "</ul>")
    body = "\n".join(parts)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>{escape(inputs.title)}: show report</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 0 auto; max-width: 980px;
  padding: 28px 20px 60px; color: #1d2733; background: #fbfcfd; line-height: 1.5; }}
h1 {{ font-size: 26px; margin: 0 0 6px; }}
h2 {{ font-size: 18px; margin: 30px 0 8px; border-bottom: 1px solid #dde3ea; padding-bottom: 4px; }}
h3 {{ font-size: 15px; margin: 18px 0 6px; }}
.lead {{ font-size: 15px; color: #39495a; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ text-align: left; padding: 5px 8px; border-bottom: 1px solid #e6ebf0; vertical-align: top; }}
th {{ background: #eef2f6; font-weight: 600; }}
li {{ margin: 4px 0; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #11171d; color: #e3e9ef; }}
  .lead {{ color: #b9c6d2; }}
  th {{ background: #1c2630; }} th, td {{ border-color: #26323d; }}
  h2 {{ border-color: #26323d; }}
}}
</style></head><body>
{body}
</body></html>
"""

