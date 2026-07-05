import math
import random
import struct
import wave
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SOUND_PATH = CONFIG_DIR / "notify.wav"
ONLINE_SOUND_PATH = CONFIG_DIR / "online.wav"


def _sine_wave(freq: float, duration: float, sr: int = 44100,
               amp: float = 16000, sweep_to: float = 0) -> list[int]:
    n = int(sr * duration)
    samples = []
    for i in range(n):
        t = i / sr
        f = freq + (sweep_to - freq) * (i / n) if sweep_to else freq
        env = max(0.0, 1.0 - t / duration)
        samples.append(int(amp * math.sin(2 * math.pi * f * t) * env))
    return samples


def _mix(*parts: list[list[int]]) -> list[int]:
    length = max(len(p) for p in parts) if parts else 0
    result = [0] * length
    for p in parts:
        for i, s in enumerate(p):
            if i < length:
                result[i] = max(-32768, min(32767, result[i] + s))
    return result


def _to_bytes(samples: list[int]) -> bytes:
    return b"".join(struct.pack("<h", s) for s in samples)


def generate_notify_sound(path: Path = SOUND_PATH):
    """
    Game-inspired notification chime:
    - Descending energy sweep (power-up whoosh)
    - Resonant pitch-bend hit
    - Sparkle overtone
    - Low thump for body
    Distinct from Slack/Discord — sounds like collecting an orb.
    """
    sr = 44100

    sweep = _sine_wave(1500, 0.04, sr, 12000, 400)
    gap = [0] * int(sr * 0.008)
    hit = _sine_wave(520, 0.08, sr, 16000, 780)
    sparkle = _sine_wave(1560, 0.055, sr, 7000)
    thump = _sine_wave(120, 0.10, sr, 10000, 60)

    gap2 = [0] * int(sr * 0.005)

    # Layer everything
    mixed = _mix(
        thump + gap2 + [0] * (len(hit) - len(gap2)),
        sweep + gap + hit,
        [0] * int(sr * 0.035) + sparkle,
    )

    audio_data = _to_bytes(mixed)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(audio_data)

    return path


def _load_wav(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    samples = []
    for i in range(0, len(raw) - 1, 2):
        samples.append(struct.unpack_from("<h", raw, i)[0])
    return samples


def generate_online_sound(path: Path = ONLINE_SOUND_PATH):
    """
    "User is online" chime — dual-tone:
    - Random7.wav (~2.7kHz) as the high anchor
    - 100Hz -> 1000Hz sweep as the low rumble
    """
    sr = 44100

    # Load Random7.wav as the base tone
    random7_path = Path.home() / "Downloads" / "Random7.wav"
    if random7_path.exists():
        base = _load_wav(random7_path)
        peak = max(abs(s) for s in base) or 1
        scale = 0.6 * 32768 / peak
        base = [int(s * scale) for s in base]
    else:
        base = _sine_wave(2750, 0.27, sr, 8000)

    # Low sweep 100Hz -> 1000Hz
    sweep = _sine_wave(100, 0.25, sr, 12000, 1000)

    # Mix
    mixed = _mix(base, sweep)

    # Normalize peak to 75%
    peak = max(abs(s) for s in mixed) or 1
    scale = 0.75 * 32768 / peak
    mixed = [int(s * scale) for s in mixed]

    audio_data = _to_bytes(mixed)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(audio_data)

    return path


EASTER_EGG_DIR = CONFIG_DIR / "sounder"
EASTER_EGG_DIR.mkdir(parents=True, exist_ok=True)

EASTER_EGG_SOUNDS = {}


def _register(name):
    def deco(fn):
        EASTER_EGG_SOUNDS[name] = fn
        return fn
    return deco


def _to_wav(samples, path, sr=44100):
    data = b"".join(struct.pack("<h", s) for s in samples)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(data)
    return path


@_register("ahoy.wav")
def _ahoy():
    sr = 44100
    return _to_wav(
        _sine_wave(200, 0.08, sr, 10000, 400) +
        [0] * int(sr * 0.03) +
        _sine_wave(300, 0.10, sr, 12000, 500) +
        [0] * int(sr * 0.05) +
        _sine_wave(400, 0.15, sr, 14000, 600),
        EASTER_EGG_DIR / "ahoy.wav", sr
    )


@_register("lol.wav")
def _lol():
    sr = 44100
    gap = [0] * int(sr * 0.04)
    a = _sine_wave(880, 0.06, sr, 12000)
    b = _sine_wave(660, 0.06, sr, 12000)
    c = _sine_wave(1047, 0.06, sr, 12000)
    d = _sine_wave(784, 0.06, sr, 12000)
    return _to_wav(a + gap + b + gap + c + gap + d + [0] * int(sr * 0.08), EASTER_EGG_DIR / "lol.wav", sr)


@_register("welcome.wav")
def _welcome():
    sr = 44100
    gap = [0] * int(sr * 0.04)
    c4 = _sine_wave(523, 0.12, sr, 12000)
    e4 = _sine_wave(659, 0.12, sr, 12000)
    g4 = _sine_wave(784, 0.12, sr, 12000)
    c5 = _sine_wave(1047, 0.18, sr, 14000)
    return _to_wav(c4 + gap + e4 + gap + g4 + gap + c5, EASTER_EGG_DIR / "welcome.wav", sr)


@_register("goodbye.wav")
def _goodbye():
    sr = 44100
    slide = _sine_wave(800, 0.20, sr, 14000, 200)
    gap = [0] * int(sr * 0.06)
    thud = _sine_wave(80, 0.12, sr, 10000)
    return _to_wav(slide + gap + thud, EASTER_EGG_DIR / "goodbye.wav", sr)


@_register("rickroll.wav")
def _rickroll():
    sr = 44100
    notes = [523, 659, 784, 659, 523, 659, 784, 1047]
    out = []
    for n in notes:
        out.extend(_sine_wave(n, 0.10, sr, 10000))
        out.extend([0] * int(sr * 0.02))
    return _to_wav(out, EASTER_EGG_DIR / "rickroll.wav", sr)


@_register("oops.wav")
def _oops():
    sr = 44100
    slide = _sine_wave(600, 0.15, sr, 14000, 100)
    buzz = _sine_wave(110, 0.10, sr, 8000)
    return _to_wav(slide + [0] * int(sr * 0.04) + buzz, EASTER_EGG_DIR / "oops.wav", sr)


@_register("bonk.wav")
def _bonk():
    sr = 44100
    hit = _sine_wave(400, 0.04, sr, 14000, 200)
    echo = [0] * int(sr * 0.06)
    hollow = _sine_wave(250, 0.12, sr, 8000, 180)
    return _to_wav(hit + echo + hollow, EASTER_EGG_DIR / "bonk.wav", sr)


@_register("yeet.wav")
def _yeet():
    sr = 44100
    sweep = _sine_wave(300, 0.06, sr, 10000, 1200)
    crash = _sine_wave(2000, 0.12, sr, 6000, 500)
    return _to_wav(sweep + [0] * int(sr * 0.02) + crash, EASTER_EGG_DIR / "yeet.wav", sr)


@_register("doh.wav")
def _doh():
    sr = 44100
    groan1 = _sine_wave(180, 0.12, sr, 10000, 120)
    groan2 = _sine_wave(150, 0.12, sr, 12000, 90)
    return _to_wav(groan1 + [0] * int(sr * 0.06) + groan2, EASTER_EGG_DIR / "doh.wav", sr)


@_register("woosh.wav")
def _woosh():
    sr = 44100
    sweep = _sine_wave(150, 0.06, sr, 14000, 2000)
    tail = _sine_wave(2000, 0.12, sr, 4000, 300)
    return _to_wav(sweep + [0] * int(sr * 0.03) + tail, EASTER_EGG_DIR / "woosh.wav", sr)


@_register("chirp.wav")
def _chirp():
    sr = 44100
    beep = _sine_wave(800, 0.08, sr, 14000)
    gap = [0] * int(sr * 0.03)
    boop = _sine_wave(1000, 0.10, sr, 16000)
    return _to_wav(beep + gap + boop, EASTER_EGG_DIR / "chirp.wav", sr)


@_register("random.wav")
def _random():
    sr = 44100
    tones = []
    for _ in range(6):
        freq = random.randint(200, 1200)
        tones.extend(_sine_wave(freq, 0.06, sr, 8000))
        tones.extend([0] * int(sr * 0.03))
    return _to_wav(tones, EASTER_EGG_DIR / "random.wav", sr)


def play_easter_egg(name: str) -> str:
    name = name.lower().strip()
    if not name.endswith(".wav"):
        name += ".wav"
    generator = EASTER_EGG_SOUNDS.get(name)
    if not generator:
        return None
    path = generator()
    return str(path)
