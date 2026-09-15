"""Hard techno structure at 152 BPM: harmony, sequences and per-part event lists."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from surge_synth import Note

BPM = 152.0
BEAT = 60.0 / BPM
BAR = BEAT * 4.0
BARS = 144
TOTAL_SECONDS = BAR * BARS + 6.0
ROOT = 33  # A1, retuned by the remix script when a vocal sets the key

INTRO, BUILD_A, DROP_A, BREAK, BUILD_B, DROP_B, OUTRO = range(7)
SECTION_NAMES = ("intro", "build A", "drop A", "breakdown", "build B", "drop B", "outro")

# natural minor scale degrees used by the acid line
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)
# two-bar harmonic cycle: i - VI - VII - i, typical dark techno movement
CHORD_ROOTS = (0, 8, 10, 0)
CHORD_SHAPE = (0, 3, 7, 10)

ACID_PATTERN = (0, 0, 12, 0, 3, 0, 7, 10, 0, 12, 3, 0, 7, 0, 10, 7)
ACID_ACCENTS = (1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0)

OPENNESS = {INTRO: 0.22, BUILD_A: 0.45, DROP_A: 1.0, BREAK: 0.5, BUILD_B: 0.5, DROP_B: 1.0, OUTRO: 0.55}
SECTION_TRIM_DB = {INTRO: -4.5, BUILD_A: -2.0, DROP_A: 0.0, BREAK: -4.0, BUILD_B: -1.5, DROP_B: 0.0, OUTRO: -3.0}


@dataclass(slots=True)
class Hit:
    start: float
    kind: str
    gain: float = 1.0
    pan: float = 0.0


def section_of(bar: int) -> int:
    if bar < 16:
        return INTRO
    if bar < 32:
        return BUILD_A
    if bar < 64:
        return DROP_A
    if bar < 80:
        return BREAK
    if bar < 96:
        return BUILD_B
    if bar < 128:
        return DROP_B
    return OUTRO


def chord_root_at(bar: int) -> int:
    return CHORD_ROOTS[(bar // 2) % len(CHORD_ROOTS)]


def openness_per_bar() -> list[float]:
    values: list[float] = []
    for bar in range(BARS):
        sec = section_of(bar)
        base = OPENNESS[sec]
        span = [b for b in range(BARS) if section_of(b) == sec]
        progress = (bar - span[0]) / max(len(span) - 1, 1)
        if sec in (BUILD_A, BUILD_B):
            base = base + (1.0 - base) * progress**1.4
        elif sec == OUTRO:
            base = base * (1.0 - 0.6 * progress)
        values.append(float(base))
    return values


def trim_per_bar() -> list[float]:
    return [SECTION_TRIM_DB[section_of(bar)] for bar in range(BARS)]


def build() -> tuple[dict[str, list[Note]], list[Hit]]:
    rng = np.random.default_rng(152)
    notes: dict[str, list[Note]] = {"hard_bass": [], "acid": [], "hoover": [], "screech": [], "dark_pad": []}
    hits: list[Hit] = []

    for bar in range(BARS):
        sec = section_of(bar)
        bar_t = bar * BAR
        chord = chord_root_at(bar)

        # ---- dark pads: sustained two-bar beds in intro, breakdown and outro
        if bar % 2 == 0 and sec in (INTRO, BREAK, BUILD_B, OUTRO):
            length = BAR * 2.0 - 0.05
            vel = 88 if sec == BREAK else 74
            for i, interval in enumerate(CHORD_SHAPE):
                notes["dark_pad"].append(Note(bar_t, ROOT + 24 + chord + interval, length, vel - i * 4))

        # ---- hoover chord stabs drive the drops
        if sec in (DROP_A, DROP_B):
            for offset in (0.0, 2.5):
                start = bar_t + offset * BEAT
                for i, interval in enumerate(CHORD_SHAPE):
                    notes["hoover"].append(Note(start, ROOT + 24 + chord + interval, BEAT * 0.85, 96 - i * 5))
        if sec == BUILD_A and bar >= 28:
            for i, interval in enumerate(CHORD_SHAPE):
                notes["hoover"].append(Note(bar_t, ROOT + 24 + chord + interval, BEAT * 1.5, 76 - i * 5))

        # ---- screech stabs in the second drop
        if sec == DROP_B and bar % 4 in (2, 3):
            for step in (0.0, 1.5, 3.0):
                midi = ROOT + 36 + chord + MINOR_SCALE[int(rng.integers(0, len(MINOR_SCALE)))]
                notes["screech"].append(Note(bar_t + step * BEAT, midi, BEAT * 0.4, 92))

        for beat in range(4):
            t0 = bar_t + beat * BEAT

            # ---- kick: the hardtech engine
            kick_on = True
            if sec == INTRO:
                kick_on = bar >= 4
            elif sec == BREAK:
                kick_on = False
            elif sec == BUILD_B:
                kick_on = bar >= 88
            elif sec == OUTRO and bar >= 138:
                kick_on = beat % 2 == 0
            if kick_on:
                gain = 0.75 if sec == INTRO else 1.0
                hits.append(Hit(t0, "hard_kick", gain))

            # ---- percussion
            perc_on = sec not in (INTRO, BREAK) or (sec == INTRO and bar >= 8)
            if sec == BUILD_B and bar < 84:
                perc_on = False
            if perc_on:
                hits.append(Hit(t0 + BEAT * 0.5, "hat", 0.85, 0.14 if beat % 2 else -0.14))
                if sec in (DROP_A, DROP_B, BUILD_A):
                    for s in (1, 3):
                        if rng.random() < 0.45:
                            hits.append(Hit(t0 + s * BEAT / 4, "hat", 0.3, float(rng.uniform(-0.6, 0.6))))
                if beat in (1, 3) and sec in (DROP_A, DROP_B):
                    hits.append(Hit(t0, "clap", 0.75))
                if beat == 3:
                    hits.append(Hit(t0 + BEAT * 0.5, "open_hat", 0.8, 0.22))
                if sec in (DROP_A, DROP_B) and rng.random() < 0.5:
                    hits.append(Hit(t0 + BEAT * 0.75, "zap", 0.55, float(rng.uniform(-0.7, 0.7))))
                if sec == DROP_B and bar >= 112:
                    hits.append(Hit(t0 + BEAT * 0.5, "ride", 0.45, -0.3))

            # ---- rolling offbeat bass
            bass_on = sec in (DROP_A, DROP_B) or (sec == BUILD_A and bar >= 24) or (sec == OUTRO and bar < 138)
            if sec == BUILD_B and bar >= 88:
                bass_on = True
            if bass_on:
                root = ROOT + chord
                hits_16 = sec == DROP_B and bar % 8 == 7
                if hits_16:
                    for s in range(4):
                        notes["hard_bass"].append(Note(t0 + s * BEAT / 4, root, BEAT * 0.2, 100))
                else:
                    notes["hard_bass"].append(Note(t0 + BEAT * 0.5, root, BEAT * 0.42, 106))
                    if sec in (DROP_A, DROP_B) and beat % 2 == 1:
                        notes["hard_bass"].append(Note(t0 + BEAT * 0.25, root + 12, BEAT * 0.2, 84))

            # ---- acid line, 16ths with accents
            acid_on = sec in (DROP_A, DROP_B) or (sec == BUILD_A and bar >= 20) or (sec == BUILD_B and bar >= 84)
            if acid_on:
                for s in range(4):
                    index = (bar * 16 + beat * 4 + s) % len(ACID_PATTERN)
                    midi = ROOT + 12 + chord + ACID_PATTERN[index]
                    vel = 108 if ACID_ACCENTS[index] else 78
                    notes["acid"].append(Note(t0 + s * BEAT / 4, midi, BEAT * 0.20, vel))

        # ---- snare rolls in the builds
        if sec in (BUILD_A, BUILD_B) and bar % 8 >= 6:
            divisions = 8 if bar % 8 == 6 else 16
            for s in range(divisions):
                gain = 0.35 + 0.55 * (s / divisions)
                hits.append(Hit(bar_t + s * BAR / divisions, "hard_snare", gain, float(rng.uniform(-0.25, 0.25))))

        # ---- rumble glue under the kicks
        if sec in (DROP_A, DROP_B, BUILD_A) and bar % 4 == 0:
            hits.append(Hit(bar_t, "rumble", 0.8))

        # ---- transitions
        if bar in (31, 95):
            hits.append(Hit(bar_t, "riser", 1.0))
        if bar in (30, 62, 94):
            hits.append(Hit(bar_t + BAR * 0.5, "reverse_cymbal", 0.9))
        if bar in (32, 64, 96, 128):
            hits.append(Hit(bar_t, "impact", 1.0))
        if bar in (64, 128):
            hits.append(Hit(bar_t, "downlifter", 0.9))
            hits.append(Hit(bar_t, "sub_drop", 0.75))
        if bar in (48, 112):
            hits.append(Hit(bar_t, "siren", 0.6))

    for part in notes.values():
        part.sort(key=lambda note: (note.start, note.midi))
    hits.sort(key=lambda hit: hit.start)
    return notes, hits


def summary() -> str:
    notes, hits = build()
    lines = [f"{BARS} bars @ {BPM:.0f} BPM = {BAR * BARS:.1f}s ({BAR * BARS / 60:.1f} min)"]
    for name, part in notes.items():
        lines.append(f"  {name}: {len(part)} notes")
    kinds: dict[str, int] = {}
    for hit in hits:
        kinds[hit.kind] = kinds.get(hit.kind, 0) + 1
    lines.append("  hits: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
