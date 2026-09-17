"""Melodic techno structure at 126 BPM: harmony, melody and per-part event lists."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from surge_synth import Note

BPM = 126.0
BEAT = 60.0 / BPM
BAR = BEAT * 4.0
BARS = 96
TOTAL_SECONDS = BAR * BARS + 6.0
ROOT = 42  # F#2

INTRO, BUILD_A, DROP_A, BREAK, BUILD_B, DROP_B, OUTRO = range(7)
SECTION_NAMES = ("intro", "build A", "drop A", "breakdown", "build B", "drop B", "outro")

# i - VI - III - VII in F# minor, two bars per chord
CHORDS: list[tuple[int, list[int]]] = [
    (42, [0, 3, 7, 14]),  # F#m9
    (38, [0, 4, 7, 11]),  # Dmaj7
    (45, [0, 4, 7, 11]),  # Amaj7
    (40, [0, 4, 7, 14]),  # E add9
]

MELODY_A: list[tuple[float, int, float]] = [
    (0.0, 73, 1.5),
    (1.5, 71, 0.5),
    (2.0, 69, 1.0),
    (3.0, 66, 1.0),
    (4.0, 69, 2.0),
    (6.0, 71, 1.0),
    (7.0, 73, 1.0),
    (8.0, 74, 1.5),
    (9.5, 73, 0.5),
    (10.0, 71, 1.0),
    (11.0, 69, 1.0),
    (12.0, 66, 2.0),
    (14.0, 69, 1.75),
]
MELODY_B: list[tuple[float, int, float]] = [
    (0.0, 78, 1.5),
    (1.5, 76, 0.5),
    (2.0, 73, 1.0),
    (3.0, 71, 1.0),
    (4.0, 73, 2.0),
    (6.0, 74, 1.0),
    (7.0, 76, 1.0),
    (8.0, 81, 2.0),
    (10.0, 78, 1.0),
    (11.0, 76, 1.0),
    (12.0, 73, 2.0),
    (14.0, 71, 1.75),
]

OPENNESS = {INTRO: 0.18, BUILD_A: 0.40, DROP_A: 1.0, BREAK: 0.55, BUILD_B: 0.45, DROP_B: 1.0, OUTRO: 0.6}
SECTION_TRIM_DB = {INTRO: -4.0, BUILD_A: -2.0, DROP_A: 0.0, BREAK: -5.0, BUILD_B: -1.5, DROP_B: 0.0, OUTRO: -2.5}


@dataclass(slots=True)
class Hit:
    start: float
    kind: str
    gain: float = 1.0
    pan: float = 0.0


def section_of(bar: int) -> int:
    if bar < 8:
        return INTRO
    if bar < 16:
        return BUILD_A
    if bar < 32:
        return DROP_A
    if bar < 40:
        return BREAK
    if bar < 48:
        return BUILD_B
    if bar < 80:
        return DROP_B
    return OUTRO


def chord_at(bar: int) -> tuple[int, list[int]]:
    return CHORDS[(bar // 2) % len(CHORDS)]


def openness_per_bar() -> list[float]:
    """Per-bar filter automation: builds ramp toward the next drop instead of sitting flat."""
    values: list[float] = []
    for bar in range(BARS):
        sec = section_of(bar)
        base = OPENNESS[sec]
        span = [b for b in range(BARS) if section_of(b) == sec]
        progress = (bar - span[0]) / max(len(span) - 1, 1)
        if sec in (BUILD_A, BUILD_B):
            base = base + (1.0 - base) * progress**1.5
        elif sec == OUTRO:
            base = base * (1.0 - 0.55 * progress)
        values.append(float(base))
    return values


def trim_per_bar() -> list[float]:
    return [SECTION_TRIM_DB[section_of(bar)] for bar in range(BARS)]


def build() -> tuple[dict[str, list[Note]], list[Hit]]:
    rng = np.random.default_rng(2026)
    notes: dict[str, list[Note]] = {"pads": [], "bass": [], "arps": [], "lead": [], "vox": []}
    hits: list[Hit] = []

    for bar in range(BARS):
        sec = section_of(bar)
        bar_t = bar * BAR
        root, intervals = chord_at(bar)

        if bar % 2 == 0 and (sec != OUTRO or bar < 94):
            length = BAR * 2.0 - 0.05
            vel = {INTRO: 74, BUILD_A: 82, DROP_A: 92, BREAK: 88, BUILD_B: 88, DROP_B: 96, OUTRO: 76}[sec]
            for i, interval in enumerate(intervals):
                notes["pads"].append(Note(bar_t, root + 12 + interval, length, vel - i * 3))
            if sec in (DROP_A, DROP_B):
                notes["pads"].append(Note(bar_t, root + 24 + intervals[1], length, vel - 16))

        for beat in range(4):
            t0 = bar_t + beat * BEAT

            kick_on = True
            if sec == INTRO:
                kick_on = (bar >= 4 and beat == 0) if bar < 6 else True
            elif sec == BREAK:
                kick_on = False
            elif sec == BUILD_B:
                kick_on = bar >= 44
            elif sec == OUTRO and bar >= 92:
                kick_on = beat % 2 == 0
            if kick_on:
                hits.append(Hit(t0, "kick", 0.72 if sec == INTRO else 1.0))

            if sec not in (INTRO, BREAK) and not (sec == BUILD_B and bar < 42):
                hits.append(Hit(t0 + BEAT * 0.5, "hat", 0.9, 0.12 if beat % 2 else -0.12))
                if beat in (1, 3):
                    hits.append(Hit(t0, "clap", 0.8))
                if beat == 3:
                    hits.append(Hit(t0 + BEAT * 0.5, "open_hat", 0.8, 0.2))
                if sec in (DROP_A, DROP_B):
                    for s in range(4):
                        if rng.random() < 0.28:
                            jitter = float(rng.normal(0.0, 0.0012))
                            hits.append(Hit(t0 + s * BEAT / 4 + jitter, "hat", 0.3, float(rng.uniform(-0.55, 0.55))))
                    for s in range(2):
                        if rng.random() < 0.42:
                            hits.append(Hit(t0 + BEAT * (0.25 + 0.5 * s), "shaker", 0.6, float(rng.uniform(-0.6, 0.6))))
                if sec == DROP_B and bar % 4 == 2 and beat in (0, 2):
                    hits.append(Hit(t0 + BEAT * 0.75, "rim", 0.7, 0.35))
                if sec == DROP_B and bar >= 64:
                    hits.append(Hit(t0 + BEAT * 0.5, "ride", 0.5, -0.3))

            bass_on = sec in (BUILD_A, DROP_A, DROP_B, OUTRO)
            if sec == BUILD_A and bar < 12:
                bass_on = False
            if sec == BUILD_B and bar >= 44:
                bass_on = True
            if sec == OUTRO and bar >= 88:
                bass_on = False
            if bass_on:
                midi = root + (7 if (beat == 3 and bar % 4 == 3) else 0)
                notes["bass"].append(Note(t0 + BEAT * 0.5, midi, BEAT * 0.46, 104 if beat % 2 == 0 else 92))
                if sec in (DROP_A, DROP_B) and beat % 2 == 0:
                    notes["bass"].append(Note(t0, root - 12, BEAT * 0.3, 78))

            arp_on = sec in (DROP_A, DROP_B) or (sec == BUILD_A and bar >= 10) or (sec == BUILD_B and bar >= 40)
            if sec == OUTRO and bar < 88:
                arp_on = True
            if arp_on:
                octave = 12 if sec in (BUILD_A, DROP_A) else 24
                ladder = intervals + [intervals[1] + 12, intervals[2] + 12]
                for s in range(4):
                    step = (bar * 16 + beat * 4 + s) % len(ladder)
                    vel = 96 if s == 0 else 74 + int(rng.integers(-6, 7))
                    notes["arps"].append(Note(t0 + s * BEAT / 4, root + octave + ladder[step], BEAT * 0.22, vel))

        if bar % 4 == 0:
            phrase: list[tuple[float, int, float]] | None = None
            transpose = 0
            vel = 100
            if sec == DROP_A and bar >= 20:
                phrase, vel = MELODY_A, 96
            elif sec == DROP_B:
                phrase = MELODY_B if bar >= 64 else MELODY_A
                vel = 104
            elif sec == BREAK:
                phrase, transpose, vel = MELODY_A, -12, 80
            if phrase:
                for start_beat, midi, length in phrase:
                    notes["lead"].append(Note(bar_t + start_beat * BEAT, midi + transpose, length * BEAT * 0.94, vel))

        if sec == BREAK and bar % 2 == 0:
            top = root + 24 + (0 if bar % 4 == 0 else 3)
            notes["vox"].append(Note(bar_t, top, BAR * 1.85, 92))
            notes["vox"].append(Note(bar_t, top - 5, BAR * 1.85, 78))

        if bar in (15, 47):
            hits.append(Hit(bar_t, "riser", 1.0))
        if bar in (14, 38, 46):
            hits.append(Hit(bar_t + BAR * 0.5, "reverse_cymbal", 0.9))
        if bar in (16, 32, 48, 80):
            hits.append(Hit(bar_t, "impact", 1.0))
        if bar in (32, 80):
            hits.append(Hit(bar_t, "downlifter", 0.9))
            hits.append(Hit(bar_t, "sub_drop", 0.7))

    for part in notes.values():
        part.sort(key=lambda note: (note.start, note.midi))
    hits.sort(key=lambda hit: hit.start)
    return notes, hits


def summary() -> str:
    notes, hits = build()
    lines = [f"{BARS} bars @ {BPM:.0f} BPM = {BAR * BARS:.1f}s"]
    for name, part in notes.items():
        lines.append(f"  {name}: {len(part)} notes")
    kinds: dict[str, int] = {}
    for hit in hits:
        kinds[hit.kind] = kinds.get(hit.kind, 0) + 1
    lines.append("  hits: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
