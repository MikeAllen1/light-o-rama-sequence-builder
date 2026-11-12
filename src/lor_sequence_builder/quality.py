"""Quality check: look at a finished show the way a sequencing professional would.

Passing the rules makes a show *valid*; this asks whether it is *good*:

- **Too much at once**: most of the yard lit for a long stretch outside the finale
  and the flashes leaves nothing to build to.
- **Dead air**: the song is playing but nearly nothing is lit.
- **Lockstep**: look-alike props doing exactly the same thing look machine-made.
- **Flat energy**: loud parts should light more of the yard than quiet ones.
- **Repetition**: the same look phrase after phrase.
- **Off the music**: effects that start away from the beat, the drums and the
  song's own onsets look random.

Each check reports what it found and where; the planner fixes what it safely can
(dead air) before the show is written, and the rest is reported.
"""

from __future__ import annotations

import bisect
import itertools
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from lor_sequence_builder.choreography import Effect, Movement
from lor_sequence_builder.style import Profile

# Sampling step for "how much is lit" (centiseconds).
STEP = 10
# Most of the yard lit (this share of props in use) for at least OVERLOAD_SPAN.
OVERLOAD_SHARE = 0.85
OVERLOAD_SPAN = 600
# Nearly nothing lit (at most this share) for at least DEAD_SPAN while the song plays.
DEAD_SHARE = 0.05
DEAD_SPAN = 300
# Loud parts should light at least this much more of the yard than quiet ones.
CONTRAST = 1.15
# An effect start within this of a musical event counts as on the music.
ON_MUSIC = 4
ON_MUSIC_GOOD = 0.75
# A ripple through look-alike props: each start this soon after one on the music.
ROLL = 25
# Phrases this alike (by which props start when) count as the same look.
SAME_LOOK = 0.9
SAME_LOOK_RUN = 3


@dataclass(frozen=True, slots=True)
class Finding:
    check: str
    status: str  # "good", "fixed" or "note"
    message: str
    at: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.check, "status": self.status, "message": self.message,
                "at_centiseconds": list(self.at)}


@dataclass(frozen=True, slots=True)
class QualityReport:
    score: int
    findings: tuple[Finding, ...]
    measures: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "findings": [f.to_dict() for f in self.findings],
                "measures": {k: round(v, 3) for k, v in self.measures.items()}}

    def summary(self) -> str:
        notes = [f for f in self.findings if f.status != "good"]
        fixed = sum(1 for f in notes if f.status == "fixed")
        left = len(notes) - fixed
        parts = [f"Quality check: {self.score}/100"]
        if fixed:
            parts.append(f"{fixed} problem(s) fixed")
        if left:
            parts.append(f"{left} thing(s) to look at")
        if not notes:
            parts.append("nothing to fix")
        return "; ".join(parts) + "."


def _spans(times: Sequence[bool], step: int, minimum: int) -> list[tuple[int, int]]:
    """Runs of True at least ``minimum`` long, as (start, end) centiseconds."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate([*times, False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if (index - start) * step >= minimum:
                runs.append((start * step, index * step))
            start = None
    return runs


def lit_share(effects: Iterable[Effect], props: set[str], duration: int,
              step: int = STEP, weighted: bool = True) -> list[float]:
    """How much of ``props`` is lit at each step of the song, weighted by brightness
    (a prop at full counts 1, a prop glowing at 40% counts 0.4), or, with
    ``weighted`` off, the share of props lit at all."""
    count = duration // step + 1
    index = {pid: i for i, pid in enumerate(sorted(props))}
    level = [[0.0] * len(index) for _ in range(count)]
    for e in effects:
        i = index.get(e.prop_id)
        if i is None or max(e.start_intensity, e.end_intensity) <= 0:
            continue
        span = max(1, e.end_centisecond - e.start_centisecond)
        for t in range(e.start_centisecond // step, min(count, -(-e.end_centisecond // step))):
            at = min(max(t * step, e.start_centisecond), e.end_centisecond)
            value = (e.start_intensity + (e.end_intensity - e.start_intensity)
                     * (at - e.start_centisecond) / span) / 100 if weighted else 1.0
            level[t][i] = max(level[t][i], value)
    total = max(1, len(props))
    return [sum(row) / total for row in level]


def _near(times: list[int], value: int, tolerance: int) -> bool:
    i = bisect.bisect_left(times, value - tolerance)
    return i < len(times) and times[i] <= value + tolerance


def _visible_starts(effects: Sequence[Effect], props: set[str],
                    movements: Sequence[Movement],
                    roles: dict[str, str] | None = None) -> list[tuple[int, str]]:
    """When something visibly begins, with the kind of prop: a movement counts once, at
    its start (its steps divide the beat on purpose), and otherwise a prop counts when
    it lights up from dark. A segment stepping on while the rest of its prop is lit (a
    spinning tree) is part of a motion already under way."""
    roles = roles or {}
    starts = [(m.start_centisecond, "movement:" + m.movement_id) for m in movements
              if props.intersection(m.prop_ids)]
    lit_until: dict[str, int] = defaultdict(lambda: -1)
    for e in sorted(effects, key=lambda e: (e.start_centisecond, e.end_centisecond)):
        if e.prop_id not in props:
            continue
        if e.movement_id is None and e.start_centisecond > lit_until[e.prop_id]:
            starts.append((e.start_centisecond, roles.get(e.prop_id, e.prop_id)))
        lit_until[e.prop_id] = max(lit_until[e.prop_id], e.end_centisecond)
    return sorted(starts)


def _on_music_share(starts: list[tuple[int, str]], marks: list[int]) -> float:
    """Share of starts on the music. A quick ripple through look-alike props (each a
    few hundredths after the last) counts with the prop that started it."""
    on = 0
    last_on: dict[str, int] = {}
    for t, kind in starts:
        if _near(marks, t, ON_MUSIC) or t - last_on.get(kind, -10_000) <= ROLL:
            on += 1
            if _near(marks, t, ON_MUSIC):
                last_on[kind] = t
    return on / max(1, len(starts))


def _style_check(effects: Sequence[Effect], props: set[str], duration: int,
                 share: list[float], sections: Sequence[tuple[int, int, int]],
                 excused: Sequence[tuple[int, int]], profile: Profile, beat: int,
                 accents: int, measures: dict[str, float]) -> list[str]:
    """How the show measures against its style's profile; what it misses, in words."""
    import statistics

    used = [e for e in effects if e.prop_id in props]
    lengths = [e.end_centisecond - e.start_centisecond for e in used]
    hold = statistics.median(lengths) / beat if lengths else 0.0
    fades = sum(1 for e in used if e.kind == "fade") / max(1, len(used))
    top = max((level for _, _, level in sections), default=0)
    calm_values: list[float] = []
    loud_values: list[float] = []
    loud_at = [False] * len(share)
    for start, end, level in sections:
        values = share[start // STEP:end // STEP]
        (loud_values if level == top and top > 0 else calm_values).extend(values)
        if level == top:
            for i in range(start // STEP, min(len(share), end // STEP)):
                loud_at[i] = True
    calm = sum(calm_values) / max(1, len(calm_values))
    loud = sum(loud_values) / max(1, len(loud_values))
    full = sum(1 for i, s in enumerate(share) if s >= OVERLOAD_SHARE and not loud_at[i]
               and not any(a <= i * STEP < b for a, b in excused)) * STEP / 100
    per_minute = accents / max(1.0, duration / 6000)
    measures.update({"hold_beats": hold, "fade_share": fades, "calm_lit": calm,
                     "peak_lit": loud, "full_outside_peaks_seconds": full,
                     "accents_per_minute": per_minute})
    missed: list[str] = []
    low, high = profile.hold_beats
    if hold < low:
        missed.append(f"effects last {hold:.1f} beats, shorter than its {low:g}")
    elif hold > high:
        missed.append(f"effects last {hold:.1f} beats, longer than its {high:g}")
    low, high = profile.fade_share
    if not low <= fades <= high:
        missed.append(f"{fades:.0%} of effects fade (it aims for {low:.0%}-{high:.0%})")
    if calm > profile.calm_lit:
        missed.append(f"{calm:.0%} of the yard lit in the quieter parts (at most "
                      f"{profile.calm_lit:.0%})")
    if loud > profile.peak_lit:
        missed.append(f"{loud:.0%} lit in the loud parts leaves little contrast (at most "
                      f"{profile.peak_lit:.0%})")
    if calm and loud < profile.loud_to_quiet * calm:
        missed.append(f"loud parts light only {loud / calm:.1f}x the quieter ones (at least "
                      f"{profile.loud_to_quiet:g}x)")
    if full > profile.full_outside_peaks:
        missed.append(f"the whole yard is lit {full:.0f} s outside the peaks")
    low, high = profile.accents_per_minute
    if not low <= per_minute <= high:
        missed.append(f"{per_minute:.1f} whole-yard accents a minute (it aims for "
                      f"{low:g}-{high:g})")
    return missed


def check(
    effects: Sequence[Effect],
    duration: int,
    props: set[str],
    roles: dict[str, str],
    sections: Sequence[tuple[int, int, int]],
    music: Iterable[int],
    phrases: Sequence[tuple[int, int]],
    quiet: Sequence[tuple[int, int]] = (),
    excused: Sequence[tuple[int, int]] = (),
    fixed_dead_air: Sequence[tuple[int, int]] = (),
    movements: Sequence[Movement] = (),
    profile: Profile | None = None,
    style_name: str = "",
    beat: int = 0,
    accents: int = 0,
) -> QualityReport:
    """Check a show. ``sections`` are (start, end, level 0-2); ``music`` the times
    of beats, drum hits and onsets; ``quiet`` where the song itself is silent or
    nearly so; ``excused`` moments meant to light everything (finale, flashes)."""
    findings: list[Finding] = []
    measures: dict[str, float] = {}
    share = lit_share(effects, props, duration)
    measures["average_lit"] = sum(share) / max(1, len(share))

    def inside(spans: Sequence[tuple[int, int]], t: int) -> bool:
        return any(a <= t < b for a, b in spans)

    # Too much at once.
    over = _spans([s >= OVERLOAD_SHARE and not inside(excused, i * STEP)
                   for i, s in enumerate(share)], STEP, OVERLOAD_SPAN)
    measures["overload_seconds"] = sum(b - a for a, b in over) / 100
    if over:
        findings.append(Finding(
            "too_much_at_once", "note",
            f"Most of the yard is lit for {measures['overload_seconds']:.0f} s outside the "
            "finale and flashes; the big moments have less to build from.",
            tuple(a for a, _ in over)))
    else:
        findings.append(Finding("too_much_at_once", "good",
                                "The yard is never all lit except at the big moments."))

    # Dead air: nothing lit at all, however dim.
    any_lit = lit_share(effects, props, duration, weighted=False)
    dead = _spans([s <= DEAD_SHARE and not inside(quiet, i * STEP)
                   for i, s in enumerate(any_lit)], STEP, DEAD_SPAN)
    measures["dead_air_seconds"] = sum(b - a for a, b in dead) / 100
    if dead:
        findings.append(Finding(
            "dead_air", "note",
            f"Nearly nothing is lit for {measures['dead_air_seconds']:.0f} s while the song "
            "plays.", tuple(a for a, _ in dead)))
    elif fixed_dead_air:
        findings.append(Finding(
            "dead_air", "fixed",
            f"{len(fixed_dead_air)} dark stretch(es) while the song played now hold a calm "
            "base.", tuple(a for a, _ in fixed_dead_air)))
    else:
        findings.append(Finding("dead_air", "good", "Something is lit whenever the song plays."))

    # Lockstep.
    timelines: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for e in effects:
        if e.prop_id in props:
            timelines[e.prop_id].append((e.start_centisecond, e.end_centisecond))
    by_role: dict[str, list[str]] = defaultdict(list)
    for pid in sorted(props):
        by_role[roles.get(pid, "unknown")].append(pid)
    pairs = [(a, b) for pids in by_role.values() for a, b in itertools.combinations(pids, 2)
             if len(timelines[a]) >= 10 and timelines[a] == timelines[b]]
    measures["lockstep_pairs"] = len(pairs)
    findings.append(Finding(
        "lockstep", "note" if pairs else "good",
        f"{len(pairs)} pair(s) of look-alike props move exactly together." if pairs else
        "Look-alike props never move exactly together."))

    # Flat energy.
    by_level: dict[int, list[float]] = defaultdict(list)
    for start, end, level in sections:
        values = share[start // STEP:end // STEP]
        if values:
            by_level[level].append(sum(values) / len(values))
    if len(by_level) >= 2:
        low = min(by_level)
        high = max(by_level)
        quiet_lit = sum(by_level[low]) / len(by_level[low])
        loud_lit = sum(by_level[high]) / len(by_level[high])
        measures["loud_to_quiet"] = loud_lit / quiet_lit if quiet_lit else 0.0
        flat = quiet_lit > 0 and loud_lit < CONTRAST * quiet_lit
        findings.append(Finding(
            "flat_energy", "note" if flat else "good",
            "Loud parts light little more of the yard than quiet ones." if flat else
            f"Loud parts light {loud_lit / quiet_lit:.1f}x as much of the yard as quiet "
            "ones." if quiet_lit else "Quiet parts stay dark and loud parts light up."))

    # Repetition.
    looks = []
    for start, end in phrases:
        looks.append({(e.prop_id, (e.start_centisecond - start) // 25) for e in effects
                      if start <= e.start_centisecond < end and e.prop_id in props})
    run = longest = 1
    where = 0
    for k in range(1, len(looks)):
        a, b = looks[k - 1], looks[k]
        alike = bool(a or b) and len(a & b) / max(1, len(a | b)) >= SAME_LOOK
        run = run + 1 if alike else 1
        if run > longest:
            longest, where = run, phrases[k - run + 1][0]
    measures["longest_same_look"] = longest
    findings.append(Finding(
        "repetition", "note" if longest >= SAME_LOOK_RUN else "good",
        f"The same look runs {longest} phrases in a row." if longest >= SAME_LOOK_RUN else
        "No look repeats more than twice in a row.", (where,) if longest >= SAME_LOOK_RUN
        else ()))

    # On the music.
    marks = sorted(set(music))
    on = _on_music_share(_visible_starts(effects, props, movements, roles), marks)
    measures["on_music"] = on
    findings.append(Finding(
        "on_the_music", "good" if on >= ON_MUSIC_GOOD else "note",
        f"{on:.0%} of effects start on a beat, a drum hit or a note of the song."))

    missed: list[str] = []
    if profile is not None and beat > 0:
        missed = _style_check(effects, props, duration, share, sections, excused, profile,
                              beat, accents, measures)
        findings.append(Finding(
            "style", "note" if missed else "good",
            f"Not quite {style_name or 'the style'}: " + "; ".join(missed) + "." if missed
            else f"Measures up to {style_name or 'the style'} on every count."))

    penalty = (min(20.0, 5.0 * len(missed))
               + min(25.0, measures["overload_seconds"] * 1.5)
               + min(25.0, measures["dead_air_seconds"] * 3)
               + min(20.0, 5.0 * len(pairs))
               + (15.0 if any(f.check == "flat_energy" and f.status == "note"
                              for f in findings) else 0.0)
               + (10.0 if longest >= SAME_LOOK_RUN else 0.0)
               + max(0.0, (ON_MUSIC_GOOD - on) * 40))
    return QualityReport(max(0, round(100 - penalty)), tuple(findings), measures)
