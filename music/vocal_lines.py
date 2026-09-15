"""Sung lines for the remix: lyrics split into syllables and pinned to a melody in A minor.

Melody notes are offsets from the track root, so retuning the arrangement moves the vocal too.
"""

from __future__ import annotations

from sing import SungNote

DEFAULT_TEXT = "espera un poco, un poquito mas"

# (word, syllable count) in singing order
WORDS_HOOK: list[tuple[str, int]] = [
    ("Espera", 3),
    ("un", 1),
    ("poco", 2),
    ("un", 1),
    ("poquito", 3),
    ("más", 1),
    ("para", 2),
    ("llevarte", 3),
    ("mi", 1),
    ("felicidad", 4),
]

WORDS_CHOP: list[tuple[str, int]] = [("un", 1), ("poquito", 3), ("más", 1)] * 2

WORDS_BREAK: list[tuple[str, int]] = [
    ("Me", 1),
    ("moriría", 4),
    ("si", 1),
    ("te", 1),
    ("vas", 1),
    ("espera", 3),
]

# (beat, semitones above root, length in beats, syllable)
HOOK_STEPS: list[tuple[float, int, float, str]] = [
    (0.0, 24, 0.5, "Es"),
    (0.5, 24, 0.5, "pe"),
    (1.0, 24, 0.5, "ra"),
    (1.5, 26, 0.5, "un"),
    (2.0, 24, 1.0, "po"),
    (3.0, 19, 1.0, "co"),
    (4.0, 22, 0.5, "un"),
    (4.5, 24, 0.5, "po"),
    (5.0, 26, 0.5, "qui"),
    (5.5, 27, 0.5, "to"),
    (6.0, 26, 2.0, "más"),
    (8.0, 22, 0.5, "pa"),
    (8.5, 22, 0.5, "ra"),
    (9.0, 24, 0.5, "lle"),
    (9.5, 27, 0.5, "var"),
    (10.0, 24, 1.0, "te"),
    (11.0, 22, 1.0, "mi"),
    (12.0, 20, 0.5, "fe"),
    (12.5, 22, 0.5, "li"),
    (13.0, 24, 0.5, "ci"),
    (13.5, 24, 2.5, "dad"),
]

CHOP_STEPS: list[tuple[float, int, float, str]] = [
    (0.0, 22, 0.5, "un"),
    (0.5, 24, 0.5, "po"),
    (1.0, 26, 0.5, "qui"),
    (1.5, 29, 0.5, "to"),
    (2.0, 26, 1.5, "más"),
    (4.0, 22, 0.5, "un"),
    (4.5, 24, 0.5, "po"),
    (5.0, 26, 0.5, "qui"),
    (5.5, 29, 0.5, "to"),
    (6.0, 29, 1.5, "más"),
]

BREAK_STEPS: list[tuple[float, int, float, str]] = [
    (0.0, 19, 0.5, "Me"),
    (0.5, 22, 0.5, "mo"),
    (1.0, 24, 0.5, "ri"),
    (1.5, 27, 1.0, "rí"),
    (2.5, 26, 1.0, "a"),
    (4.0, 24, 0.5, "si"),
    (4.5, 22, 0.5, "te"),
    (5.0, 24, 2.5, "vas"),
    (8.0, 24, 1.0, "Es"),
    (9.0, 22, 1.0, "pe"),
    (10.0, 20, 3.0, "ra"),
]


def melody(steps: list[tuple[float, int, float, str]], root: int) -> list[SungNote]:
    return [SungNote(beat, root + offset, beats, text) for beat, offset, beats, text in steps]


def lines(root: int) -> dict[str, tuple[list[tuple[str, int]], list[SungNote]]]:
    return {
        "hook": (WORDS_HOOK, melody(HOOK_STEPS, root)),
        "chop": (WORDS_CHOP, melody(CHOP_STEPS, root)),
        "break": (WORDS_BREAK, melody(BREAK_STEPS, root)),
    }


# (bar, line name) placements across the arrangement
PLACEMENTS: list[tuple[int, str]] = [
    (8, "hook"),
    (24, "hook"),
    (36, "chop"),
    (44, "chop"),
    (52, "chop"),
    (60, "chop"),
    (64, "break"),
    (72, "hook"),
    (100, "chop"),
    (108, "chop"),
    (116, "chop"),
    (124, "chop"),
    (128, "hook"),
]
