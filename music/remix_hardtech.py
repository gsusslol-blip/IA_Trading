"""Hardtech remix engine: Surge XT synths, numpy drums, and an optional vocal from music/input/.

Without a vocal it renders the instrumental. With a legally owned file in music/input/ it
separates the vocal with Demucs, retunes it to the track key, and places phrases on the grid.

Run: python remix_hardtech.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from pedalboard import (
    BrickwallLimiter,
    Chorus,
    Compressor,
    Delay,
    Distortion,
    Gain,
    HighShelfFilter,
    HighpassFilter,
    LowpassFilter,
    Pedalboard,
    PeakFilter,
    Reverb,
)

import drums
import hardtech_arrangement as arr
import sing
import vocal_lines
import vocals
from dsp import (
    SR,
    crossfade_lowpass,
    envelope_follower,
    fit_level,
    fit_level_active,
    haas_stereo,
    midi_hz,
    mono_bass,
    pan_stereo,
    rms_db,
    smooth,
    widen,
)
from surge_synth import PATCHES, SurgeSynth

HERE = Path(__file__).resolve().parent
N = int(round(arr.TOTAL_SECONDS * SR))
TARGET_LUFS = -8.0
CEILING_DB = -1.0

SYNTH_PARTS = ("hard_bass", "acid", "hoover", "screech", "dark_pad")

BUS_TARGETS_DB = {
    "kick": -18.0,
    "hard_bass": -21.0,
    "perc": -23.0,
    "acid": -23.0,
    "hoover": -23.0,
    "screech": -30.0,
    "dark_pad": -25.5,
    "vocal": -16.5,
    "fx": -24.0,
    "atmos": -38.0,
}

# buses that only sound part of the time: level them where they play, not across the whole track
SPARSE_BUSES = ("vocal", "screech", "fx")

# generous enough to keep each bus at its RMS target; the clamp only catches real outliers
PEAK_HEADROOM_DB = {
    "kick": 11.0,
    "hard_bass": 16.0,
    "perc": 20.0,
    "acid": 18.0,
    "hoover": 17.0,
    "screech": 16.0,
    "dark_pad": 15.0,
    "vocal": 16.0,
    "fx": 18.0,
    "atmos": 20.0,
}

ONE_SHOT_BUS = {
    "hard_kick": "kick",
    "hat": "perc",
    "open_hat": "perc",
    "clap": "perc",
    "zap": "perc",
    "ride": "perc",
    "hard_snare": "perc",
    "rumble": "kick",
    "riser": "fx",
    "reverse_cymbal": "fx",
    "impact": "fx",
    "downlifter": "fx",
    "sub_drop": "fx",
    "siren": "fx",
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


def process(board: Pedalboard, audio: np.ndarray) -> np.ndarray:
    return np.asarray(board(np.ascontiguousarray(audio, dtype=np.float32), SR), dtype=np.float32)


def duck(audio: np.ndarray, gate: np.ndarray, amount: float) -> np.ndarray:
    return (audio * (1.0 - amount * gate)).astype(np.float32)


def ping_pong(stereo: np.ndarray, delay_s: float, feedback: float = 0.3, mix: float = 0.28, taps: int = 6) -> np.ndarray:
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


# ------------------------------------------------------------------ rendering


CACHE_DIR = HERE / "cache_hardtech"


def cache_load(name: str) -> np.ndarray | None:
    path = CACHE_DIR / f"{name}.wav"
    if not path.exists():
        return None
    audio, sr = sf.read(path, always_2d=True, dtype="float32")
    if sr != SR or audio.shape[0] != N:
        return None
    return audio.T.astype(np.float32)


def cache_store(name: str, audio: np.ndarray) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sf.write(CACHE_DIR / f"{name}.wav", audio.T, SR, subtype="FLOAT")


def render_drum_buses() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(11)
    _, hits = arr.build()
    buses = {name: np.zeros((2, N), dtype=np.float32) for name in ("kick", "perc", "fx", "atmos")}

    root_hz = midi_hz(arr.ROOT + 12)
    kick_hit = pan_stereo(drums.hard_kick(rng, root_hz), 0.0)
    hat_variants = [drums.hat(rng) for _ in range(4)]
    open_hat = drums.hat(rng, True)
    clap_variants = [drums.industrial_clap(rng) for _ in range(2)]
    snare_variants = [drums.hard_snare(rng) for _ in range(3)]
    zap_variants = [drums.zap(rng) for _ in range(3)]
    ride_hit = drums.ride(rng)

    place(buses["atmos"], 0.0, haas_stereo(drums.atmosphere(arr.TOTAL_SECONDS, rng, midi_hz(arr.ROOT + 24)), 0.5, 19.0))

    for index, hit in enumerate(hits):
        bus = buses[ONE_SHOT_BUS[hit.kind]]
        if hit.kind == "hard_kick":
            place(bus, hit.start, kick_hit, hit.gain)
        elif hit.kind == "rumble":
            place(bus, hit.start, haas_stereo(drums.rumble(arr.BAR * 4.0, rng, root_hz * 0.8), 0.1, 9.0), hit.gain)
        elif hit.kind == "hat":
            place(bus, hit.start, pan_stereo(hat_variants[index % 4], hit.pan), hit.gain)
        elif hit.kind == "open_hat":
            place(bus, hit.start, pan_stereo(open_hat, hit.pan), hit.gain)
        elif hit.kind == "clap":
            place(bus, hit.start, haas_stereo(clap_variants[index % 2], 0.3, 12.0), hit.gain)
        elif hit.kind == "hard_snare":
            place(bus, hit.start, pan_stereo(snare_variants[index % 3], hit.pan), hit.gain)
        elif hit.kind == "zap":
            place(bus, hit.start, pan_stereo(zap_variants[index % 3], hit.pan), hit.gain)
        elif hit.kind == "ride":
            place(bus, hit.start, pan_stereo(ride_hit, hit.pan), hit.gain)
        elif hit.kind == "riser":
            place(bus, hit.start, haas_stereo(drums.riser(arr.BAR, rng), 0.35, 16.0), hit.gain)
        elif hit.kind == "reverse_cymbal":
            place(bus, hit.start, haas_stereo(drums.reverse_cymbal(arr.BAR * 0.5, rng), 0.4, 18.0), hit.gain)
        elif hit.kind == "impact":
            place(bus, hit.start, haas_stereo(drums.impact(rng), 0.25, 13.0), hit.gain)
        elif hit.kind == "downlifter":
            place(bus, hit.start, haas_stereo(drums.downlifter(arr.BAR, rng), 0.3, 15.0), hit.gain)
        elif hit.kind == "sub_drop":
            place(bus, hit.start, haas_stereo(drums.sub_drop(rng), 0.0, 4.0), hit.gain)
        elif hit.kind == "siren":
            place(bus, hit.start, haas_stereo(drums.siren(arr.BAR * 2.0, rng), 0.4, 17.0), hit.gain)
    return buses


def render_synth_buses(use_cache: bool = True) -> dict[str, np.ndarray]:
    notes, _ = arr.build()
    out: dict[str, np.ndarray] = {}
    pending = list(SYNTH_PARTS)
    if use_cache:
        for part in SYNTH_PARTS:
            cached = cache_load(part)
            if cached is not None:
                out[part] = cached
                pending.remove(part)
                print(f"  cached {part}: rms {rms_db(cached):.1f} dB")
    if not pending:
        return out
    synth = SurgeSynth(SR)
    for part in pending:
        start = time.time()
        audio = synth.render(PATCHES[part], notes[part], arr.TOTAL_SECONDS)
        if audio.shape[1] < N:
            audio = np.pad(audio, ((0, 0), (0, N - audio.shape[1])))
        out[part] = audio[:, :N].astype(np.float32)
        cache_store(part, out[part])
        print(f"  surge {part}: {len(notes[part])} notes, rms {rms_db(out[part]):.1f} dB, {time.time() - start:.1f}s")
    return out


def vocal_plan() -> list[tuple[float, int, float]]:
    """(bar, phrase_rank, bars_long) placements used when a real recording is supplied."""
    return [
        (8, 0, 4),
        (24, 1, 4),
        (36, 0, 2),
        (44, 1, 2),
        (52, 0, 2),
        (60, 1, 2),
        (64, 0, 4),
        (72, 1, 4),
        (100, 0, 2),
        (108, 1, 2),
        (116, 0, 2),
        (124, 1, 2),
        (128, 0, 4),
    ]


def render_sung_bus(use_cache: bool = True) -> tuple[np.ndarray, str]:
    """Sing the hook with the project's own Piper voice, layered an octave up for width."""
    if use_cache:
        cached = cache_load("vocal_sung")
        if cached is not None:
            return cached, f"cached sung vocal ({vocal_lines.DEFAULT_TEXT})"
    bus = np.zeros((2, N), dtype=np.float32)
    lines = vocal_lines.lines(arr.ROOT)
    rendered = {
        name: sing.render_line(words, melody, arr.BEAT, vibrato_cents=26.0)
        for name, (words, melody) in lines.items()
    }
    for name, audio in rendered.items():
        print(f"  sung {name}: {len(audio) / SR:.1f}s, {len(lines[name][1])} notes")

    for bar, name in vocal_lines.PLACEMENTS:
        mono = rendered[name]
        lead = haas_stereo(mono, width=0.35, delay_ms=14.0)
        octave = haas_stereo(sing.pitch_to(mono, 12.0), width=0.6, delay_ms=21.0) * 0.28
        detuned = haas_stereo(sing.pitch_to(mono, -0.12), width=0.5, delay_ms=27.0) * 0.35
        span = min(lead.shape[1], octave.shape[1], detuned.shape[1])
        place(bus, bar * arr.BAR, lead[:, :span] + octave[:, :span] + detuned[:, :span], 1.0)
    cache_store("vocal_sung", bus)
    return bus, f"sung by Piper ({vocal_lines.DEFAULT_TEXT}) in {len(vocal_lines.PLACEMENTS)} slots"


def render_vocal_bus(use_cache: bool = True) -> tuple[np.ndarray, str]:
    """Use a supplied recording when present, otherwise sing the line ourselves."""
    bus = np.zeros((2, N), dtype=np.float32)
    source = vocals.find_input()
    if source is None:
        return render_sung_bus(use_cache)

    print(f"  separating {source.name} with Demucs...")
    stems = vocals.separate(source)
    vocal_stereo = vocals.load_stereo(stems["vocals"])
    vocal_mono = vocal_stereo.mean(axis=0)

    key_name, is_minor, tonic = vocals.estimate_key(vocal_mono)
    track_tonic = arr.ROOT % 12
    semitones = (track_tonic - tonic + 6) % 12 - 6
    phrases = vocals.detect_phrases(vocal_mono)
    if not phrases:
        return bus, "no vocal phrases detected above the gate"

    ranked = sorted(phrases, key=lambda p: (p.dur * 0.5 + (p.peak_db + 60) * 0.1), reverse=True)[:6]
    print(f"  vocal key {key_name}, shifting {semitones:+d} semitones, {len(phrases)} phrases found")

    for bar, rank, bars_long in vocal_plan():
        if rank >= len(ranked):
            continue
        phrase = ranked[rank]
        slice_audio = vocals.slice_phrase(vocal_stereo, phrase)
        target = arr.BAR * bars_long
        fitted = vocals.fit_to_grid(slice_audio, phrase.dur, target, semitones=semitones)
        place(bus, bar * arr.BAR, fitted, 1.0)
    return bus, f"vocal placed from {source.name} ({len(vocal_plan())} slots, {semitones:+d} st)"


# ------------------------------------------------------------------ mixing


def automation_curves() -> tuple[np.ndarray, np.ndarray]:
    bar_len = int(round(arr.BAR * SR))
    openness = np.repeat(np.array(arr.openness_per_bar()), bar_len)
    trim = np.repeat(np.array(arr.trim_per_bar()), bar_len)
    openness = np.pad(openness, (0, max(N - len(openness), 0)), mode="edge")[:N]
    trim = np.pad(trim, (0, max(N - len(trim), 0)), mode="edge")[:N]
    return smooth(openness, 0.3), 10.0 ** (smooth(trim, 0.35) / 20.0)


def mix(stems: dict[str, np.ndarray], stem_dir: Path | None = None) -> np.ndarray:
    openness, trim = automation_curves()

    kick_bus = process(
        Pedalboard(
            [
                Compressor(threshold_db=-10.0, ratio=3.4, attack_ms=5.0, release_ms=80.0),
                PeakFilter(cutoff_frequency_hz=58.0, gain_db=2.4, q=0.9),
                PeakFilter(cutoff_frequency_hz=2800.0, gain_db=2.0, q=0.8),
                Distortion(drive_db=3.0),
                HighpassFilter(cutoff_frequency_hz=30.0),
            ]
        ),
        stems.pop("kick"),
    )
    gate = np.clip(smooth(envelope_follower(np.abs(kick_bus).mean(axis=0), 0.004, 0.09), 0.010), 0.0, 1.0)
    buses: dict[str, np.ndarray] = {"kick": kick_bus}

    # second sidechain: the mid-heavy synths step back while the hook is singing
    vocal_env = envelope_follower(np.abs(stems["vocal"]).mean(axis=0), 0.02, 0.25)
    vocal_gate = np.clip(smooth(vocal_env, 0.08) / 0.35, 0.0, 1.0)

    buses["perc"] = process(
        Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=300.0),
                Compressor(threshold_db=-15.0, ratio=2.8, attack_ms=3.0, release_ms=60.0),
                Reverb(room_size=0.3, damping=0.6, wet_level=0.1, dry_level=0.9, width=1.0),
                HighShelfFilter(cutoff_frequency_hz=9000.0, gain_db=2.0),
            ]
        ),
        duck(duck(stems.pop("perc"), gate, 0.3), vocal_gate, 0.22),
    )

    buses["hard_bass"] = mono_bass(
        process(
            Pedalboard(
                [
                    HighpassFilter(cutoff_frequency_hz=38.0),
                    Distortion(drive_db=9.0),
                    LowpassFilter(cutoff_frequency_hz=2000.0),
                    Compressor(threshold_db=-16.0, ratio=5.0, attack_ms=6.0, release_ms=60.0),
                ]
            ),
            duck(stems.pop("hard_bass"), gate, 0.72),
        ),
        crossover=110.0,
    )

    buses["acid"] = process(
        Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=140.0),
                Distortion(drive_db=6.0),
                Delay(delay_seconds=arr.BEAT * 0.75, feedback=0.24, mix=0.2),
                Reverb(room_size=0.5, damping=0.5, wet_level=0.18, dry_level=0.82, width=1.0),
                Compressor(threshold_db=-18.0, ratio=3.0, attack_ms=5.0, release_ms=80.0),
            ]
        ),
        duck(duck(stems.pop("acid"), gate, 0.45), vocal_gate, 0.38),
    )

    buses["hoover"] = process(
        Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=200.0),
                Chorus(rate_hz=0.25, depth=0.3, centre_delay_ms=12.0, feedback=0.1, mix=0.25),
                Reverb(room_size=0.7, damping=0.4, wet_level=0.3, dry_level=0.74, width=1.0),
                Compressor(threshold_db=-18.0, ratio=2.6, attack_ms=10.0, release_ms=120.0),
            ]
        ),
        duck(duck(stems.pop("hoover"), gate, 0.4), vocal_gate, 0.35),
    )

    buses["screech"] = process(
        Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=350.0),
                Distortion(drive_db=5.0),
                Reverb(room_size=0.66, damping=0.4, wet_level=0.3, dry_level=0.76, width=1.0),
            ]
        ),
        ping_pong(duck(duck(stems.pop("screech"), gate, 0.35), vocal_gate, 0.45), arr.BEAT * 0.5, feedback=0.26, mix=0.24),
    )

    buses["dark_pad"] = process(
        Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=180.0),
                Chorus(rate_hz=0.12, depth=0.45, centre_delay_ms=18.0, feedback=0.12, mix=0.32),
                Reverb(room_size=0.93, damping=0.28, wet_level=0.55, dry_level=0.5, width=1.0),
                LowpassFilter(cutoff_frequency_hz=5600.0),
            ]
        ),
        duck(stems.pop("dark_pad"), gate, 0.3),
    )

    vocal_raw = stems.pop("vocal")
    buses["vocal"] = process(
        Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=110.0),
                Compressor(threshold_db=-20.0, ratio=3.2, attack_ms=8.0, release_ms=120.0),
                PeakFilter(cutoff_frequency_hz=2500.0, gain_db=3.5, q=0.8),
                PeakFilter(cutoff_frequency_hz=750.0, gain_db=-1.5, q=1.0),
                Delay(delay_seconds=arr.BEAT * 1.5, feedback=0.2, mix=0.16),
                Reverb(room_size=0.8, damping=0.35, wet_level=0.3, dry_level=0.78, width=1.0),
                HighShelfFilter(cutoff_frequency_hz=7000.0, gain_db=1.5),
            ]
        ),
        duck(vocal_raw, gate, 0.3),
    )

    buses["fx"] = process(
        Pedalboard(
            [
                Reverb(room_size=0.9, damping=0.3, wet_level=0.45, dry_level=0.65, width=1.0),
                HighpassFilter(cutoff_frequency_hz=32.0),
            ]
        ),
        stems.pop("fx"),
    )

    buses["atmos"] = process(
        Pedalboard(
            [
                Reverb(room_size=0.95, damping=0.25, wet_level=0.6, dry_level=0.4, width=1.0),
                LowpassFilter(cutoff_frequency_hz=4800.0),
            ]
        ),
        duck(stems.pop("atmos"), gate, 0.25),
    )

    buses["acid"] = crossfade_lowpass(buses["acid"], openness, 700.0)
    buses["hoover"] = crossfade_lowpass(buses["hoover"], openness, 800.0)
    buses["screech"] = crossfade_lowpass(buses["screech"], 0.4 + 0.6 * openness, 1200.0)
    buses["dark_pad"] = crossfade_lowpass(buses["dark_pad"], 0.5 + 0.5 * openness, 700.0)

    print("  bus staging (rms dB before -> target, peak after):")
    for name in list(buses):
        before = rms_db(buses[name])
        if before < -200.0:
            print(f"    {name:<10} silent, skipped")
            continue
        # sparse buses are staged on their sounding parts only, continuous ones on the whole track
        stage = fit_level_active if name in SPARSE_BUSES else fit_level
        ceiling_db = BUS_TARGETS_DB[name] + PEAK_HEADROOM_DB[name]
        limiter = Pedalboard([BrickwallLimiter(ceiling_db=ceiling_db, release_ms=50.0)])
        # limit, restore the level the limiter took away, then bound the peaks again
        staged = stage(buses[name] * trim.astype(np.float32), BUS_TARGETS_DB[name])
        leveled = stage(process(limiter, staged), BUS_TARGETS_DB[name])
        buses[name] = process(limiter, leveled)
        peak = 20.0 * np.log10(max(float(np.abs(buses[name]).max()), 1e-12))
        print(f"    {name:<10} {before:6.1f} -> {rms_db(buses[name]):6.1f}  peak {peak:6.1f}")

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
                HighpassFilter(cutoff_frequency_hz=28.0),
                Compressor(threshold_db=-15.0, ratio=1.9, attack_ms=20.0, release_ms=140.0),
                PeakFilter(cutoff_frequency_hz=90.0, gain_db=1.2, q=0.8),
                PeakFilter(cutoff_frequency_hz=400.0, gain_db=-1.0, q=0.9),
                PeakFilter(cutoff_frequency_hz=1600.0, gain_db=1.4, q=0.6),
                PeakFilter(cutoff_frequency_hz=3600.0, gain_db=1.6, q=0.7),
                HighShelfFilter(cutoff_frequency_hz=8000.0, gain_db=1.4),
            ]
        ),
        bus_sum,
    )
    glued = mono_bass(widen(glued, amount=1.2, above_hz=250.0), crossover=105.0)
    return master(glued)


def master(audio: np.ndarray) -> np.ndarray:
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
    ax_wave.plot(times, mono, color="#ff5f4f", linewidth=0.3)
    for bar in [b for b in range(arr.BARS) if b == 0 or arr.section_of(b) != arr.section_of(b - 1)]:
        x = bar * arr.BAR
        ax_wave.axvline(x, color="#4fd6ff", linewidth=0.8, alpha=0.8)
        ax_wave.text(x + 0.6, 0.86, arr.SECTION_NAMES[arr.section_of(bar)], color="#9fe6ff", fontsize=8)
    ax_wave.set_xlim(0, times[-1])
    ax_wave.set_ylim(-1.05, 1.05)
    ax_wave.set_ylabel("amplitude", color="white")
    ax_wave.set_title(f"Hardtech remix — {arr.BPM:.0f} BPM, A minor, Surge XT", color="white")
    ax_spec.specgram(mono, NFFT=2048, Fs=SR, noverlap=1024, cmap="inferno", vmin=-120, vmax=-20)
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
    fresh = "--fresh" in sys.argv
    print(arr.summary())
    print("rendering drums and fx...")
    drum_names = ("kick", "perc", "fx", "atmos")
    cached_drums = {} if fresh else {n: a for n in drum_names if (a := cache_load(n)) is not None}
    if len(cached_drums) == len(drum_names):
        stems = cached_drums
        print("  loaded from cache")
    else:
        stems = render_drum_buses()
        for name, audio in stems.items():
            cache_store(name, audio)
    print("preparing vocal...")
    vocal_bus, status = render_vocal_bus(use_cache=not fresh)
    print(f"  {status}")
    stems["vocal"] = vocal_bus
    print("rendering Surge XT parts...")
    stems.update(render_synth_buses(use_cache=not fresh))
    print("mixing and mastering...")
    audio = mix(stems, stem_dir=HERE / "stems_hardtech")
    out_wav = HERE / "hardtech_remix_152bpm.wav"
    sf.write(out_wav, audio.T, SR, subtype="PCM_24")
    plot_overview(audio, HERE / "hardtech_overview.png")
    print(f"wrote {out_wav.name} ({audio.shape[1] / SR:.1f}s, {arr.BPM:.0f} BPM, 24-bit)")


if __name__ == "__main__":
    main()
