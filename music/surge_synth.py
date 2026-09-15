"""Drive the installed Surge XT VST3 as a scriptable synth: patches as plain dicts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import mido
import numpy as np
from pedalboard import load_plugin

PLUGIN_PATH = "C:/Program Files/Common Files/VST3/Surge Synth Team/Surge XT.vst3/Contents/x86_64-win/Surge XT.vst3"
PARAM_CACHE = Path(__file__).resolve().parent / "surge_params.json"

Patch = dict[str, object]


@dataclass(slots=True)
class Note:
    start: float
    midi: int
    dur: float
    vel: int = 100


def _numeric(text: str) -> float | None:
    """Parse a Surge display string into a comparable number (time normalized to ms)."""
    low = text.strip().lower()
    if low in ("-inf", "off", "none"):
        return -np.inf
    if low in ("forever", "inf"):
        return np.inf
    match = re.match(r"^(-?\d+(?:\.\d+)?)", low)
    if match is None:
        return None
    value = float(match.group(1))
    if low.endswith("ms") or " ms" in low:
        return value
    if re.search(r"\d\s*s$", low) or low.endswith(" s"):
        return value * 1000.0
    return value


class SurgeSynth:
    """One plugin instance, reconfigured per part. Renders a note list to stereo audio."""

    def __init__(self, sample_rate: int = 44100) -> None:
        self.sample_rate = sample_rate
        self.plugin = load_plugin(PLUGIN_PATH)
        if not self.plugin.is_instrument:
            raise RuntimeError("Surge XT did not load as an instrument")

    def _valid_values(self, name: str) -> list[str] | None:
        param = self.plugin.parameters.get(name)
        if param is None:
            return None
        values = getattr(param, "valid_values", None)
        return None if values is None else [str(v) for v in values]

    def set_param(self, name: str, value: object) -> bool:
        """Set one parameter. Returns False when the name is not exposed for the current osc type."""
        if name not in self.plugin.parameters:
            return False
        if isinstance(value, (bool, str)):
            setattr(self.plugin, name, value)
            return True
        target = float(value)
        options = self._valid_values(name)
        if options:
            usable = [(opt, _numeric(opt)) for opt in options]
            usable = [(opt, num) for opt, num in usable if num is not None and np.isfinite(num)]
            if usable:
                setattr(self.plugin, name, min(usable, key=lambda item: abs(item[1] - target))[0])
                return True
        setattr(self.plugin, name, target)
        return True

    def apply_patch(self, patch: Patch) -> list[str]:
        """Oscillator and filter types come first: Surge exposes different params per type."""
        ordered = sorted(patch.items(), key=lambda item: 0 if item[0].endswith("_type") else 1)
        skipped = [name for name, value in ordered if not self.set_param(name, value)]
        return skipped

    @staticmethod
    def to_midi(notes: list[Note], channel: int = 0) -> list[mido.Message]:
        events: list[tuple[float, int, mido.Message]] = []
        for note in notes:
            events.append(
                (note.start, 1, mido.Message("note_on", note=int(note.midi), velocity=int(note.vel), channel=channel))
            )
            events.append((note.start + note.dur, 0, mido.Message("note_off", note=int(note.midi), channel=channel)))
        events.sort(key=lambda item: (item[0], item[1]))
        messages = []
        for time, _, message in events:
            message.time = max(time, 0.0)
            messages.append(message)
        return messages

    def render(self, patch: Patch, notes: list[Note], duration: float) -> np.ndarray:
        skipped = self.apply_patch(patch)
        if skipped:
            print(f"    params not available for this osc type: {', '.join(skipped)}")
        if not notes:
            return np.zeros((2, int(duration * self.sample_rate)), dtype=np.float32)
        audio = self.plugin(
            self.to_midi(notes),
            duration=duration,
            sample_rate=self.sample_rate,
            num_channels=2,
            buffer_size=4096,
            reset=True,
        )
        return np.asarray(audio, dtype=np.float32)


# ---------------------------------------------------------------------- patches

BASE: Patch = {
    "global_volume": 0.0,
    "scene_mode": "Single",
    "a_osc_1_mute": False,
    "a_osc_2_mute": True,
    "a_osc_3_mute": True,
    "a_noise_mute": True,
    "a_waveshaper_type": "Off",
    "a_filter_2_type": "Off",
    "a_pan": 0.0,
    "a_width": 100.0,
    "a_portamento": 0.0,
}

PAD: Patch = {
    **BASE,
    "polyphony_limit": 64.0,
    "a_play_mode": "Poly",
    "a_osc_1_type": "Classic",
    "a_osc_1_shape": -18.0,
    "a_osc_1_unison_voices": "7 voices",
    "a_osc_1_unison_detune": 17.0,
    "a_osc_1_volume": -2.0,
    "a_osc_2_mute": False,
    "a_osc_2_type": "Classic",
    "a_osc_2_octave": -1.0,
    "a_osc_2_unison_voices": "5 voices",
    "a_osc_2_unison_detune": 9.0,
    "a_osc_2_volume": -8.0,
    "a_osc_3_mute": False,
    "a_osc_3_type": "Sine",
    "a_osc_3_octave": 1.0,
    "a_osc_3_volume": -17.0,
    "a_osc_drift": 6.0,
    "a_filter_configuration": "Wide",
    "a_filter_1_type": "LP 24 dB",
    "a_filter_1_cutoff": 780.0,
    "a_filter_1_resonance": 7.0,
    "a_filter_1_feg_mod_amount": 34.0,
    "a_filter_1_keytrack": 30.0,
    "a_filter_eg_attack": 1600.0,
    "a_filter_eg_decay": 3000.0,
    "a_filter_eg_sustain": 62.0,
    "a_filter_eg_release": 2200.0,
    "a_amp_eg_attack": 650.0,
    "a_amp_eg_attack_shape": "Linear",
    "a_amp_eg_decay": 2000.0,
    "a_amp_eg_sustain": 88.0,
    "a_amp_eg_release": 1900.0,
    "a_waveshaper_type": "Soft",
    "a_waveshaper_drive": 2.0,
    "a_highpass": 110.0,
    "a_volume": -7.0,
}

BASS: Patch = {
    **BASE,
    "polyphony_limit": 8.0,
    "a_play_mode": "Mono (single trigger)",
    "a_portamento": 6.0,
    "a_osc_1_type": "Classic",
    "a_osc_1_shape": 8.0,
    "a_osc_1_sub_mix": 26.0,
    "a_osc_1_unison_voices": "3 voices",
    "a_osc_1_unison_detune": 5.0,
    "a_osc_1_volume": -1.0,
    "a_osc_2_mute": False,
    "a_osc_2_type": "Classic",
    "a_osc_2_octave": -1.0,
    "a_osc_2_unison_voices": "1 voice",
    "a_osc_2_volume": -7.0,
    "a_filter_configuration": "Serial 1",
    "a_filter_1_type": "LP 24 dB",
    "a_filter_1_cutoff": 230.0,
    "a_filter_1_resonance": 18.0,
    "a_filter_1_feg_mod_amount": 40.0,
    "a_filter_1_keytrack": 45.0,
    "a_filter_eg_attack": 0.0,
    "a_filter_eg_decay": 170.0,
    "a_filter_eg_sustain": 14.0,
    "a_filter_eg_release": 110.0,
    "a_amp_eg_attack": 2.0,
    "a_amp_eg_decay": 280.0,
    "a_amp_eg_sustain": 58.0,
    "a_amp_eg_release": 120.0,
    "a_waveshaper_type": "Soft",
    "a_waveshaper_drive": 5.0,
    "a_highpass": 28.0,
    "a_width": 35.0,
    "a_volume": -4.0,
}

ARP: Patch = {
    **BASE,
    "polyphony_limit": 24.0,
    "a_play_mode": "Poly",
    "a_osc_1_type": "Classic",
    "a_osc_1_shape": 34.0,
    "a_osc_1_unison_voices": "2 voices",
    "a_osc_1_unison_detune": 7.0,
    "a_osc_1_volume": -2.0,
    "a_osc_2_mute": False,
    "a_osc_2_type": "Sine",
    "a_osc_2_octave": 1.0,
    "a_osc_2_volume": -13.0,
    "a_filter_configuration": "Wide",
    "a_filter_1_type": "LP 24 dB",
    "a_filter_1_cutoff": 900.0,
    "a_filter_1_resonance": 24.0,
    "a_filter_1_feg_mod_amount": 44.0,
    "a_filter_1_keytrack": 55.0,
    "a_filter_eg_attack": 0.0,
    "a_filter_eg_decay": 130.0,
    "a_filter_eg_sustain": 0.0,
    "a_filter_eg_release": 90.0,
    "a_amp_eg_attack": 1.0,
    "a_amp_eg_decay": 190.0,
    "a_amp_eg_sustain": 0.0,
    "a_amp_eg_release": 130.0,
    "a_highpass": 180.0,
    "a_volume": -8.0,
}

LEAD: Patch = {
    **BASE,
    "polyphony_limit": 16.0,
    "a_play_mode": "Poly",
    "a_osc_1_type": "Classic",
    "a_osc_1_shape": -8.0,
    "a_osc_1_unison_voices": "5 voices",
    "a_osc_1_unison_detune": 11.0,
    "a_osc_1_volume": -3.0,
    "a_osc_2_mute": False,
    "a_osc_2_type": "Sine",
    "a_osc_2_octave": 0.0,
    "a_osc_2_volume": -9.0,
    "a_osc_drift": 4.0,
    "a_filter_configuration": "Wide",
    "a_filter_1_type": "LP 24 dB",
    "a_filter_1_cutoff": 1900.0,
    "a_filter_1_resonance": 12.0,
    "a_filter_1_feg_mod_amount": 22.0,
    "a_filter_1_keytrack": 40.0,
    "a_filter_eg_attack": 30.0,
    "a_filter_eg_decay": 700.0,
    "a_filter_eg_sustain": 45.0,
    "a_filter_eg_release": 600.0,
    "a_amp_eg_attack": 14.0,
    "a_amp_eg_decay": 600.0,
    "a_amp_eg_sustain": 68.0,
    "a_amp_eg_release": 750.0,
    "a_waveshaper_type": "Soft",
    "a_waveshaper_drive": 1.5,
    "a_highpass": 150.0,
    "a_volume": -7.0,
}

VOX: Patch = {
    **BASE,
    "polyphony_limit": 24.0,
    "a_play_mode": "Poly",
    "a_osc_1_type": "Window",
    "a_osc_1_unison_voices": "3 voices",
    "a_osc_1_unison_detune": 8.0,
    "a_osc_1_volume": -2.0,
    "a_osc_2_mute": False,
    "a_osc_2_type": "Classic",
    "a_osc_2_shape": -40.0,
    "a_osc_2_volume": -12.0,
    "a_filter_configuration": "Wide",
    "a_filter_1_type": "BP 12 dB",
    "a_filter_1_cutoff": 620.0,
    "a_filter_1_resonance": 30.0,
    "a_filter_1_feg_mod_amount": 18.0,
    "a_filter_1_keytrack": 60.0,
    "a_filter_eg_attack": 400.0,
    "a_filter_eg_decay": 1200.0,
    "a_filter_eg_sustain": 55.0,
    "a_filter_eg_release": 900.0,
    "a_amp_eg_attack": 260.0,
    "a_amp_eg_decay": 1200.0,
    "a_amp_eg_sustain": 78.0,
    "a_amp_eg_release": 1200.0,
    "a_highpass": 200.0,
    "a_volume": -1.0,
}

# ---------------------------------------------------------------- hard techno

HARD_BASS: Patch = {
    **BASE,
    "polyphony_limit": 8.0,
    "a_play_mode": "Mono (single trigger)",
    "a_osc_1_type": "Classic",
    "a_osc_1_shape": 0.0,
    "a_osc_1_unison_voices": "1 voice",
    "a_osc_1_volume": 0.0,
    "a_osc_2_mute": False,
    "a_osc_2_type": "Classic",
    "a_osc_2_shape": 60.0,
    "a_osc_2_octave": -1.0,
    "a_osc_2_volume": -5.0,
    "a_filter_configuration": "Serial 1",
    "a_filter_1_type": "LP 24 dB",
    "a_filter_1_cutoff": 175.0,
    "a_filter_1_resonance": 12.0,
    "a_filter_1_feg_mod_amount": 26.0,
    "a_filter_1_keytrack": 40.0,
    "a_filter_eg_attack": 0.0,
    "a_filter_eg_decay": 110.0,
    "a_filter_eg_sustain": 8.0,
    "a_filter_eg_release": 60.0,
    "a_amp_eg_attack": 1.0,
    "a_amp_eg_decay": 150.0,
    "a_amp_eg_sustain": 22.0,
    "a_amp_eg_release": 55.0,
    "a_waveshaper_type": "Hard",
    "a_waveshaper_drive": 8.0,
    "a_highpass": 34.0,
    "a_width": 20.0,
    "a_volume": -3.0,
}

ACID: Patch = {
    **BASE,
    "polyphony_limit": 6.0,
    "a_play_mode": "Mono (fingered portamento)",
    "a_portamento": 12.0,
    "a_osc_1_type": "Classic",
    "a_osc_1_shape": -60.0,
    "a_osc_1_unison_voices": "1 voice",
    "a_osc_1_volume": 0.0,
    "a_filter_configuration": "Serial 1",
    "a_filter_1_type": "LP Diode Ladder",
    "a_filter_1_cutoff": 330.0,
    "a_filter_1_resonance": 62.0,
    "a_filter_1_feg_mod_amount": 58.0,
    "a_filter_1_keytrack": 30.0,
    "a_filter_eg_attack": 0.0,
    "a_filter_eg_decay": 190.0,
    "a_filter_eg_sustain": 0.0,
    "a_filter_eg_release": 110.0,
    "a_amp_eg_attack": 1.0,
    "a_amp_eg_decay": 240.0,
    "a_amp_eg_sustain": 28.0,
    "a_amp_eg_release": 90.0,
    "a_waveshaper_type": "Soft",
    "a_waveshaper_drive": 9.0,
    "a_highpass": 80.0,
    "a_volume": -6.0,
}

HOOVER: Patch = {
    **BASE,
    "polyphony_limit": 24.0,
    "a_play_mode": "Poly",
    "a_osc_1_type": "Classic",
    "a_osc_1_shape": -35.0,
    "a_osc_1_unison_voices": "7 voices",
    "a_osc_1_unison_detune": 32.0,
    "a_osc_1_volume": -2.0,
    "a_osc_2_mute": False,
    "a_osc_2_type": "Classic",
    "a_osc_2_pitch": 7.0,
    "a_osc_2_unison_voices": "5 voices",
    "a_osc_2_unison_detune": 22.0,
    "a_osc_2_volume": -7.0,
    "a_osc_3_mute": False,
    "a_osc_3_type": "Sine",
    "a_osc_3_octave": -1.0,
    "a_osc_3_volume": -12.0,
    "a_filter_configuration": "Wide",
    "a_filter_1_type": "LP 24 dB",
    "a_filter_1_cutoff": 950.0,
    "a_filter_1_resonance": 34.0,
    "a_filter_1_feg_mod_amount": 30.0,
    "a_filter_1_keytrack": 45.0,
    "a_filter_eg_attack": 2.0,
    "a_filter_eg_decay": 350.0,
    "a_filter_eg_sustain": 25.0,
    "a_filter_eg_release": 250.0,
    "a_amp_eg_attack": 4.0,
    "a_amp_eg_decay": 420.0,
    "a_amp_eg_sustain": 45.0,
    "a_amp_eg_release": 320.0,
    "a_waveshaper_type": "Asymmetric",
    "a_waveshaper_drive": 6.0,
    "a_highpass": 160.0,
    "a_volume": -7.0,
}

SCREECH: Patch = {
    **BASE,
    "polyphony_limit": 16.0,
    "a_play_mode": "Poly",
    "a_osc_1_type": "Classic",
    "a_osc_1_shape": 72.0,
    "a_osc_1_unison_voices": "5 voices",
    "a_osc_1_unison_detune": 24.0,
    "a_osc_1_volume": 0.0,
    "a_osc_2_mute": False,
    "a_osc_2_type": "Classic",
    "a_osc_2_shape": 70.0,
    "a_osc_2_pitch": 12.0,
    "a_osc_2_volume": -9.0,
    "a_filter_configuration": "Wide",
    "a_filter_1_type": "LP 24 dB",
    "a_filter_1_cutoff": 2400.0,
    "a_filter_1_resonance": 44.0,
    "a_filter_1_feg_mod_amount": 36.0,
    "a_filter_eg_attack": 0.0,
    "a_filter_eg_decay": 260.0,
    "a_filter_eg_sustain": 12.0,
    "a_filter_eg_release": 180.0,
    "a_amp_eg_attack": 2.0,
    "a_amp_eg_decay": 300.0,
    "a_amp_eg_sustain": 30.0,
    "a_amp_eg_release": 220.0,
    "a_waveshaper_type": "Digital",
    "a_waveshaper_drive": 7.0,
    "a_highpass": 300.0,
    "a_volume": -9.0,
}

DARK_PAD: Patch = {
    **PAD,
    "a_osc_1_unison_detune": 24.0,
    "a_filter_1_cutoff": 520.0,
    "a_amp_eg_attack": 900.0,
    "a_volume": -8.0,
}

PATCHES: dict[str, Patch] = {
    "pads": PAD,
    "bass": BASS,
    "arps": ARP,
    "lead": LEAD,
    "vox": VOX,
    "hard_bass": HARD_BASS,
    "acid": ACID,
    "hoover": HOOVER,
    "screech": SCREECH,
    "dark_pad": DARK_PAD,
}
