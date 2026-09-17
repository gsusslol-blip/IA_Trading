"""Visual summary of the finished remix: arrangement, section loudness and the sung melody.

Run: python preview.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pyloudnorm as pyln
import soundfile as sf

import hardtech_arrangement as arr
import vocal_lines as vl

HERE = Path(__file__).resolve().parent
BG = "#0b0b0b"
RED = "#ff5f4f"
CYAN = "#4fd6ff"
GOLD = "#ffcc4f"
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def section_spans() -> list[tuple[str, float, float]]:
    spans: list[tuple[str, float, float]] = []
    start = 0
    for bar in range(1, arr.BARS + 1):
        if bar == arr.BARS or arr.section_of(bar) != arr.section_of(start):
            spans.append((arr.SECTION_NAMES[arr.section_of(start)], start * arr.BAR, bar * arr.BAR))
            start = bar
    return spans


def style(ax: plt.Axes) -> None:
    ax.set_facecolor(BG)
    ax.tick_params(colors="white", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#333333")


def main() -> None:
    wav = HERE / f"hardtech_remix_{arr.BPM:.0f}bpm.wav"
    audio, sr = sf.read(wav, always_2d=True)
    mono = audio.mean(axis=1)
    meter = pyln.Meter(sr)
    spans = section_spans()

    fig = plt.figure(figsize=(15, 10), facecolor=BG)
    grid = fig.add_gridspec(3, 2, height_ratios=[1.15, 0.9, 1.1], hspace=0.42, wspace=0.18)

    # ---- arrangement with vocal entries
    ax = fig.add_subplot(grid[0, :])
    style(ax)
    times = np.arange(len(mono)) / sr
    ax.plot(times, mono, color=RED, linewidth=0.25)
    for name, start, end in spans:
        ax.axvline(start, color=CYAN, linewidth=0.9, alpha=0.85)
        ax.text(start + 0.7, 0.88, name, color="#9fe6ff", fontsize=8)
    for bar, line in vl.PLACEMENTS:
        length = 4 if line != "chop" else 2
        start = bar * arr.BAR
        ax.axvspan(start, start + length * arr.BAR, color=GOLD, alpha=0.16)
        ax.text(start + 0.4, -0.95, line, color=GOLD, fontsize=6.5)
    loudness = meter.integrated_loudness(audio)
    peak = 20 * np.log10(float(np.abs(audio).max()))
    ax.set_title(
        f"Remix hardtech — {arr.BPM:.0f} BPM, La menor, {len(mono) / sr / 60:.0f}:{len(mono) / sr % 60:02.0f}"
        f"  |  {loudness:.1f} LUFS, pico {peak:.2f} dBFS  |  bloques dorados = voz",
        color="white",
        fontsize=11,
    )
    ax.set_xlim(0, times[-1])
    ax.set_ylim(-1.05, 1.05)
    ax.set_ylabel("amplitud", color="white", fontsize=9)

    # ---- per-section loudness
    ax = fig.add_subplot(grid[1, 0])
    style(ax)
    names = [name for name, _, _ in spans]
    values = [meter.integrated_loudness(audio[int(s * sr) : int(e * sr)]) for _, s, e in spans]
    colors = [GOLD if v > -8.0 else CYAN for v in values]
    bars = ax.barh(range(len(names)), [v + 20 for v in values], color=colors, height=0.6)
    ax.set_yticks(range(len(names)), names, color="white")
    ax.invert_yaxis()
    ax.set_xlim(0, 15)
    ax.set_xticks(range(0, 16, 3), [f"{v - 20}" for v in range(0, 16, 3)])
    ax.set_xlabel("LUFS por sección", color="white", fontsize=9)
    for rect, value in zip(bars, values):
        ax.text(rect.get_width() + 0.2, rect.get_y() + 0.32, f"{value:.1f}", color="white", fontsize=7.5)
    ax.set_title("dinámica: drops fuertes, breakdown que respira", color="white", fontsize=10)

    # ---- band balance
    ax = fig.add_subplot(grid[1, 1])
    style(ax)
    from dsp import bandpass, filt

    bands = (("sub\n20-60", 20, 60), ("bajo\n60-200", 60, 200), ("medio-bajo\n200-800", 200, 800), ("medio\n0.8-3k", 800, 3000), ("agudo\n3-16k", 3000, 16000))
    total = float(np.sqrt(np.mean(mono**2)))
    levels = []
    for _, low, high in bands:
        band = filt(mono, "low", high, order=2) if low <= 20 else bandpass(mono, low, high, order=2)
        levels.append(20 * np.log10(float(np.sqrt(np.mean(band**2))) / total))
    ax.bar(range(len(bands)), [v + 16 for v in levels], color=RED, width=0.6)
    ax.set_xticks(range(len(bands)), [name for name, _, _ in bands], color="white", fontsize=7.5)
    ax.set_yticks(range(0, 17, 4), [f"{v - 16}" for v in range(0, 17, 4)])
    ax.set_ylim(0, 16)
    ax.set_ylabel("dB vs total", color="white", fontsize=9)
    ax.set_title("balance de bandas", color="white", fontsize=10)
    for i, value in enumerate(levels):
        ax.text(i, value + 16.3, f"{value:.1f}", color="white", fontsize=7.5, ha="center")

    # ---- sung melody piano roll
    ax = fig.add_subplot(grid[2, :])
    style(ax)
    lines = vl.lines(arr.ROOT)
    palette = {"hook": GOLD, "chop": RED, "break": CYAN}
    offset = 0.0
    for name in ("hook", "chop", "break"):
        _, melody = lines[name]
        for note in melody:
            ax.add_patch(
                plt.Rectangle(
                    (offset + note.beat, note.midi - 0.4),
                    note.beats * 0.94,
                    0.8,
                    color=palette[name],
                    alpha=0.85,
                )
            )
            ax.text(offset + note.beat + 0.06, note.midi + 0.55, note.text, color="white", fontsize=6.5)
        span = melody[-1].beat + melody[-1].beats
        ax.text(offset + 0.2, 63.2, name, color=palette[name], fontsize=9, weight="bold")
        offset += span + 2.0
    ax.set_xlim(0, offset)
    ax.set_ylim(50, 64)
    pitches = sorted({n.midi for _, melody in lines.values() for n in melody})
    ax.set_yticks(pitches, [note_name(p) for p in pitches], color="white")
    ax.set_xlabel("pulsos", color="white", fontsize=9)
    ax.set_title(
        'melodía cantada con Piper — "espera un poco, un poquito más" (error medio 7-11 cents)',
        color="white",
        fontsize=10,
    )

    out = HERE / "remix_preview.png"
    fig.savefig(out, dpi=110, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out.name}")


if __name__ == "__main__":
    main()
