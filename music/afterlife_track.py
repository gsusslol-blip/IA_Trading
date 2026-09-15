"""Original melodic / hypnotic techno in the Afterlife vein (mood reference only, not a cover).

Synths: Surge XT VST3 driven by scripted patches. Drums and FX: local numpy synthesis.
Mixing: pedalboard buses, sidechain from the real kick envelope, RMS staging, LUFS target.

Run: python afterlife_track.py
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from pedalboard import (
    BrickwallLimiter,
    Chorus,
    Compressor,
    Distortion,
    Gain,
    HighShelfFilter,
    HighpassFilter,
    LowpassFilter,
    Pedalboard,
    PeakFilter,
    Phaser,
    Reverb,
)

import drums
from arrangement import (
    BAR,
    BARS,
    BEAT,
    BPM,
    ROOT,
    SECTION_NAMES,
    TOTAL_SECONDS,
    build,
    openness_per_bar,
    section_of,
    summary,
    trim_per_bar,
)
from dsp import (
    SR,
    crossfade_lowpass,
    envelope_follower,
    fit_level,
    haas_stereo,
    midi_hz,
    mono_bass,
    pan_stereo,
    rms_db,
    smooth,
    widen,
)
from surge_synth import PATCHES, SurgeSynth

N = int(round(TOTAL_SECONDS * SR))
TARGET_LUFS = -9.0
CEILING_DB = -1.0

BUS_TARGETS_DB = {
    "kick": -19.5,
    "bass": -20.5,
    "pads": -22.0,
    "perc": -24.5,
    "arps": -26.0,
    "lead": -25.0,
    "vox": -30.0,
    "fx": -31.0,
    "atmos": -38.0,
}

PEAK_HEADROOM_DB = {
    "kick": 12.0,
    "bass": 12.0,
    "perc": 15.0,
    "pads": 13.0,
    "arps": 16.0,
    "lead": 15.0,
    "vox": 14.0,
    "fx": 20.0,
    "atmos": 18.0,
}

ONE_SHOT_BUS = {
    "kick": "kick",
    "hat": "perc",
    "open_hat": "perc",
    "clap": "perc",
    "shaker": "perc",
    "rim": "perc",
    "ride": "perc",
    "riser": "fx",
    "reverse_cymbal": "fx",
    "impact": "fx",
    "downlifter": "fx",
    "sub_drop": "fx",
}


def place(buf: np.ndarray, start_sec: float, sig: np.ndarray, gain: float = 1.0) -> None:
    start = int(round(start_sec * SR))
    total = buf.shape[-1]
    if start >= total:
        return
    if start < 0:
        sig = sig[..., -start:]
        start = 0
    span = min(total - start, sig.shape[-1])
    if span <= 0:
        return
    buf[:, start : start + span] += sig[:, :span] * gain


def render_drum_buses() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(7)
    _, hits = build()
    buses = {name: np.zeros((2, N), dtype=np.float32) for name in ("kick", "perc", "fx", "atmos")}

    kick_hit = pan_stereo(drums.kick(rng), 0.0)  # dead centre: no low-end side energy
    hat_variants = [drums.hat(rng) for _ in range(4)]
    open_hat = drums.hat(rng, True)
    clap_variants = [drums.clap(rng) for _ in range(2)]
    shaker_variants = [drums.shaker(rng) for _ in range(3)]
    rim_hit = drums.rim(rng)
    ride_hit = drums.ride(rng)

    place(buses["atmos"], 0.0, haas_stereo(drums.atmosphere(TOTAL_SECONDS, rng, midi_hz(ROOT + 24)), 0.5, 19.0))

    for index, hit in enumerate(hits):
        bus = buses[ONE_SHOT_BUS[hit.kind]]
        if hit.kind == "kick":
            place(bus, hit.start, kick_hit, hit.gain)
        elif hit.kind == "hat":
            place(bus, hit.start, pan_stereo(hat_variants[index % 4], hit.pan), hit.gain)
        elif hit.kind == "open_hat":
            place(bus, hit.start, pan_stereo(open_hat, hit.pan), hit.gain)
        elif hit.kind == "clap":
            place(bus, hit.start, haas_stereo(clap_variants[index % 2], 0.3, 12.0), hit.gain)
        elif hit.kind == "shaker":
            place(bus, hit.start, pan_stereo(shaker_variants[index % 3], hit.pan), hit.gain)
        elif hit.kind == "rim":
            place(bus, hit.start, pan_stereo(rim_hit, hit.pan), hit.gain)
        elif hit.kind == "ride":
            place(bus, hit.start, pan_stereo(ride_hit, hit.pan), hit.gain)
        elif hit.kind == "riser":
            place(bus, hit.start, haas_stereo(drums.riser(BAR, rng), 0.35, 16.0), hit.gain)
        elif hit.kind == "reverse_cymbal":
            place(bus, hit.start, haas_stereo(drums.reverse_cymbal(BAR * 0.5, rng), 0.4, 18.0), hit.gain)
        elif hit.kind == "impact":
            place(bus, hit.start, haas_stereo(drums.impact(rng), 0.25, 13.0), hit.gain)
        elif hit.kind == "downlifter":
            place(bus, hit.start, haas_stereo(drums.downlifter(BAR, rng), 0.3, 15.0), hit.gain)
        elif hit.kind == "sub_drop":
            place(bus, hit.start, haas_stereo(drums.sub_drop(rng), 0.0, 4.0), hit.gain)
    return buses


def render_synth_buses() -> dict[str, np.ndarray]:
    notes, _ = build()
    synth = SurgeSynth(SR)
    out: dict[str, np.ndarray] = {}
    for part in ("pads", "bass", "arps", "lead", "vox"):
        start = time.time()
        audio = synth.render(PATCHES[part], notes[part], TOTAL_SECONDS)
        if audio.shape[1] < N:
            audio = np.pad(audio, ((0, 0), (0, N - audio.shape[1])))
        out[part] = audio[:, :N].astype(np.float32)
        print(f"  surge {part}: {len(notes[part])} notes, rms {rms_db(out[part]):.1f} dB, {time.time() - start:.1f}s")
    return out


def process(board: Pedalboard, audio: np.ndarray) -> np.ndarray:
    return np.asarray(board(np.ascontiguousarray(audio, dtype=np.float32), SR), dtype=np.float32)


def duck(audio: np.ndarray, gate: np.ndarray, amount: float) -> np.ndarray:
    return (audio * (1.0 - amount * gate)).astype(np.float32)


def ping_pong(stereo: np.ndarray, delay_s: float, feedback: float = 0.32, mix: float = 0.3, taps: int = 7) -> np.ndarray:
    d = int(round(delay_s * SR))
    if d <= 0:
        return stereo
    wet = np.zeros_like(stereo)
    for i in range(1, taps + 1):
        shift = i * d
        if shift >= stereo.shape[1]:
            break
        tap = np.zeros_like(stereo)
        tap[:, shift:] = stereo[:, :-shift]
        if i % 2 == 1:
            tap = tap[::-1].copy()
        wet += tap * (feedback**i)
    return stereo * (1.0 - mix) + wet * mix


def automation_curves() -> tuple[np.ndarray, np.ndarray]:
    bar_len = int(round(BAR * SR))
    openness = np.repeat(np.array(openness_per_bar()), bar_len)
    trim = np.repeat(np.array(trim_per_bar()), bar_len)
    openness = np.pad(openness, (0, max(N - len(openness), 0)), mode="edge")[:N]
    trim = np.pad(trim, (0, max(N - len(trim), 0)), mode="edge")[:N]
    return smooth(openness, 0.28), 10.0 ** (smooth(trim, 0.35) / 20.0)


def mix(stems: dict[str, np.ndarray], stem_dir: Path | None = None) -> np.ndarray:
    openness, trim = automation_curves()

    kick_bus = process(
        Pedalboard(
            [
                Compressor(threshold_db=-11.0, ratio=3.0, attack_ms=6.0, release_ms=90.0),
                PeakFilter(cutoff_frequency_hz=62.0, gain_db=2.0, q=0.9),
                PeakFilter(cutoff_frequency_hz=3200.0, gain_db=1.6, q=0.8),
                Gain(gain_db=0.0),
            ]
        ),
        stems.pop("kick"),
    )
    gate = np.clip(smooth(envelope_follower(np.abs(kick_bus).mean(axis=0), 0.005, 0.10), 0.012), 0.0, 1.0)
    buses: dict[str, np.ndarray] = {"kick": kick_bus}

    buses["perc"] = process(
        Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=320.0),
                Compressor(threshold_db=-16.0, ratio=2.6, attack_ms=4.0, release_ms=70.0),
                Reverb(room_size=0.35, damping=0.6, wet_level=0.11, dry_level=0.89, width=1.0),
                HighShelfFilter(cutoff_frequency_hz=9000.0, gain_db=1.5),
            ]
        ),
        duck(stems.pop("perc"), gate, 0.26),
    )

    buses["bass"] = mono_bass(
        process(
            Pedalboard(
                [
                    HighpassFilter(cutoff_frequency_hz=34.0),
                    Distortion(drive_db=5.0),
                    LowpassFilter(cutoff_frequency_hz=2400.0),
                    Compressor(threshold_db=-18.0, ratio=4.0, attack_ms=10.0, release_ms=80.0),
                ]
            ),
            duck(stems.pop("bass"), gate, 0.60),
        ),
        crossover=120.0,
    )

    buses["pads"] = process(
        Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=190.0),
                Chorus(rate_hz=0.16, depth=0.4, centre_delay_ms=14.0, feedback=0.1, mix=0.3),
                Phaser(rate_hz=0.08, depth=0.22, feedback=0.12, mix=0.16),
                Reverb(room_size=0.9, damping=0.3, wet_level=0.46, dry_level=0.56, width=1.0),
                LowpassFilter(cutoff_frequency_hz=7400.0),
                Compressor(threshold_db=-22.0, ratio=2.2, attack_ms=40.0, release_ms=240.0),
            ]
        ),
        duck(stems.pop("pads"), gate, 0.32),
    )

    buses["arps"] = process(
        Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=250.0),
                Reverb(room_size=0.62, damping=0.45, wet_level=0.24, dry_level=0.76, width=1.0),
                PeakFilter(cutoff_frequency_hz=2400.0, gain_db=1.6, q=0.7),
                Compressor(threshold_db=-20.0, ratio=2.8, attack_ms=8.0, release_ms=110.0),
            ]
        ),
        ping_pong(duck(stems.pop("arps"), gate, 0.42), BEAT * 0.75, feedback=0.3, mix=0.28),
    )

    buses["lead"] = process(
        Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=170.0),
                Chorus(rate_hz=0.3, depth=0.2, centre_delay_ms=9.0, feedback=0.07, mix=0.2),
                Reverb(room_size=0.8, damping=0.34, wet_level=0.34, dry_level=0.72, width=1.0),
                Compressor(threshold_db=-20.0, ratio=2.5, attack_ms=14.0, release_ms=160.0),
            ]
        ),
        ping_pong(duck(stems.pop("lead"), gate, 0.28), BEAT, feedback=0.26, mix=0.24),
    )

    buses["vox"] = process(
        Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=220.0),
                Chorus(rate_hz=0.22, depth=0.3, centre_delay_ms=18.0, feedback=0.1, mix=0.28),
                Reverb(room_size=0.94, damping=0.28, wet_level=0.55, dry_level=0.5, width=1.0),
                LowpassFilter(cutoff_frequency_hz=6000.0),
            ]
        ),
        duck(stems.pop("vox"), gate, 0.22),
    )

    buses["fx"] = process(
        Pedalboard(
            [
                Reverb(room_size=0.92, damping=0.3, wet_level=0.48, dry_level=0.62, width=1.0),
                HighpassFilter(cutoff_frequency_hz=30.0),
            ]
        ),
        stems.pop("fx"),
    )

    buses["atmos"] = process(
        Pedalboard(
            [
                Reverb(room_size=0.95, damping=0.25, wet_level=0.6, dry_level=0.4, width=1.0),
                LowpassFilter(cutoff_frequency_hz=5000.0),
            ]
        ),
        duck(stems.pop("atmos"), gate, 0.2),
    )

    buses["pads"] = crossfade_lowpass(buses["pads"], openness, 620.0)
    buses["arps"] = crossfade_lowpass(buses["arps"], openness, 850.0)
    buses["lead"] = crossfade_lowpass(buses["lead"], 0.45 + 0.55 * openness, 950.0)
    buses["vox"] = crossfade_lowpass(buses["vox"], 0.5 + 0.5 * openness, 900.0)

    print("  bus staging (rms dB before -> target, peak after):")
    for name in list(buses):
        before = rms_db(buses[name])
        ceiling_db = BUS_TARGETS_DB[name] + PEAK_HEADROOM_DB[name]
        staged = fit_level(buses[name] * trim.astype(np.float32), BUS_TARGETS_DB[name])
        tamed = process(Pedalboard([BrickwallLimiter(ceiling_db=ceiling_db, release_ms=60.0)]), staged)
        leveled = fit_level(tamed, BUS_TARGETS_DB[name])
        peak_now = float(np.abs(leveled).max())
        ceiling_lin = 10.0 ** (ceiling_db / 20.0)
        if peak_now > ceiling_lin:
            leveled = (leveled * (ceiling_lin / peak_now)).astype(np.float32)
        buses[name] = leveled
        peak = 20.0 * np.log10(max(float(np.abs(buses[name]).max()), 1e-12))
        print(f"    {name:<6} {before:6.1f} -> {rms_db(buses[name]):6.1f}  peak {peak:6.1f}")

    if stem_dir is not None:
        stem_dir.mkdir(parents=True, exist_ok=True)
        for name, audio in buses.items():
            sf.write(stem_dir / f"{name}.wav", audio.T, SR, subtype="PCM_24")

    bus_sum = np.zeros((2, N), dtype=np.float32)
    for name in list(buses):
        bus_sum += buses.pop(name)

    glued = process(
        Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=26.0),
                Compressor(threshold_db=-16.0, ratio=1.8, attack_ms=24.0, release_ms=160.0),
                PeakFilter(cutoff_frequency_hz=95.0, gain_db=1.2, q=0.8),
                PeakFilter(cutoff_frequency_hz=430.0, gain_db=-1.5, q=0.9),
                PeakFilter(cutoff_frequency_hz=1800.0, gain_db=1.0, q=0.6),
                HighShelfFilter(cutoff_frequency_hz=8500.0, gain_db=1.6),
            ]
        ),
        bus_sum,
    )
    glued = mono_bass(widen(glued, amount=1.22, above_hz=260.0), crossover=110.0)
    return master(glued)


def master(audio: np.ndarray) -> np.ndarray:
    """Loudness-target the mix, soft-clip, then verify; iterate to land on TARGET_LUFS."""
    meter = pyln.Meter(SR)
    ceiling = 10.0 ** (CEILING_DB / 20.0)
    working = audio.astype(np.float64)
    loudness = meter.integrated_loudness(working.T)
    print(f"  pre-master: {loudness:.1f} LUFS")
    trim_db = 0.0
    result = working
    for _ in range(4):
        scaled = pyln.normalize.loudness(working.T, loudness, TARGET_LUFS + trim_db).T
        result = np.tanh(scaled / ceiling * 1.02) * ceiling
        measured = meter.integrated_loudness(result.T)
        error = TARGET_LUFS - measured
        if abs(error) < 0.25:
            break
        trim_db += error
    peak = float(np.max(np.abs(result)))
    if peak > ceiling:
        result *= ceiling / peak
    crest = 20.0 * np.log10(peak / max(float(np.sqrt((result**2).mean())), 1e-12))
    print(
        f"  master: {meter.integrated_loudness(result.T):.1f} LUFS, "
        f"peak {20 * np.log10(max(peak, 1e-12)):.2f} dBFS, crest {crest:.1f} dB"
    )
    return result.astype(np.float32)


def plot_overview(audio: np.ndarray, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mono = audio.mean(axis=0)
    times = np.arange(len(mono)) / SR
    fig, (ax_wave, ax_spec) = plt.subplots(2, 1, figsize=(14, 6.5), facecolor="#0b0b0b")
    ax_wave.plot(times, mono, color="#4fd6ff", linewidth=0.3)
    for bar in [b for b in range(BARS) if b == 0 or section_of(b) != section_of(b - 1)]:
        x = bar * BAR
        ax_wave.axvline(x, color="#ff5f9e", linewidth=0.8, alpha=0.8)
        ax_wave.text(x + 0.6, 0.86, SECTION_NAMES[section_of(bar)], color="#ff9ec4", fontsize=8)
    ax_wave.set_xlim(0, times[-1])
    ax_wave.set_ylim(-1.05, 1.05)
    ax_wave.set_ylabel("amplitude", color="white")
    ax_wave.set_title(f"Afterlife-style melodic techno — {BPM:.0f} BPM, F# minor, Surge XT", color="white")
    ax_spec.specgram(mono, NFFT=2048, Fs=SR, noverlap=1024, cmap="magma", vmin=-120, vmax=-20)
    ax_spec.set_ylim(0, 16000)
    ax_spec.set_xlabel("time (s)", color="white")
    ax_spec.set_ylabel("Hz", color="white")
    for ax in (ax_wave, ax_spec):
        ax.set_facecolor("#0b0b0b")
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_color("#333333")
    fig.tight_layout()
    fig.savefig(path, dpi=110, facecolor="#0b0b0b")
    plt.close(fig)


def main() -> None:
    here = Path(__file__).resolve().parent
    print(summary())
    print("rendering drums and fx...")
    stems = render_drum_buses()
    print("rendering Surge XT parts (this loads the VST3, takes a moment)...")
    stems.update(render_synth_buses())
    print("mixing and mastering...")
    audio = mix(stems, stem_dir=here / "stems")
    out_wav = here / "afterlife_126bpm.wav"
    sf.write(out_wav, audio.T, SR, subtype="PCM_24")
    plot_overview(audio, here / "afterlife_overview.png")
    print(f"wrote {out_wav.name} ({audio.shape[1] / SR:.1f}s, {BPM:.0f} BPM, 24-bit) + stems/ + overview PNG")


if __name__ == "__main__":
    main()
