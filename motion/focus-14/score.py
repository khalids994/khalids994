"""Synthesized score + SFX for the Saudifitx 14-day focus film.

Writes score_raw.wav (unmastered), then:
  - loudness-normalises to -14 LUFS (ffmpeg loudnorm, two-pass)  -> score.wav
  - measures the beat grid from the mastered mix                  -> beats.json

Usage: python3 score.py   (needs numpy, scipy, and ffmpeg on PATH or $FFMPEG)
Cue times mirror index.html: both use beat index B(i) on a 120 BPM grid and
the same mulberry32 seeds for the intro "notification" chaos.
"""
import json, os, re, subprocess
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt, fftconvolve

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 48000
BPM = 120
BEAT = 60 / BPM
DUR = 20.0
N = int(SR * DUR)
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

def B(i):
    return i * BEAT

# ── seeded randomness (identical to the JS mulberry32 in index.html)
def mulberry32(a):
    state = [a & 0xFFFFFFFF]
    def imul(x, y):
        return (x * y) & 0xFFFFFFFF
    def rnd():
        state[0] = (state[0] + 0x6D2B79F5) & 0xFFFFFFFF
        a = state[0]
        t = imul(a ^ (a >> 15), 1 | a)
        t = ((t + imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return rnd

CHAOS_SEED, CHAOS_COUNT = 14, 18
def chaos_times():
    r = mulberry32(CHAOS_SEED)
    out = []
    for i in range(CHAOS_COUNT):
        raw = r()
        appear = i * .03 if i < 6 else .18 + raw * .6
        for _ in range(5):  # x, y, size, rot, style — consumed in the same order as JS
            r()
        out.append(appear)
    return out

noise_rng = np.random.default_rng(14)
L = np.zeros(N)
R = np.zeros(N)

def place(sig, t0, gain=1.0, pan=0.0):
    i0 = int(round(t0 * SR))
    if i0 >= N:
        return
    sig = sig[: N - i0] * gain
    L[i0 : i0 + len(sig)] += sig * np.sqrt(0.5 * (1 - pan))
    R[i0 : i0 + len(sig)] += sig * np.sqrt(0.5 * (1 + pan))

def tt(d):
    return np.arange(int(d * SR)) / SR

def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)

def hp(x, f, order=2):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)

def lp(x, f, order=2):
    return sosfilt(butter(order, f, "low", fs=SR, output="sos"), x)

# ── instruments
def kick(d=0.45):
    t = tt(d)
    f = 45 + 95 * np.exp(-t / 0.035)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t / 0.16) + 0.25 * np.exp(-t / 0.004) * noise_rng.standard_normal(len(t))

def clap():
    t = tt(0.3)
    n = bp(noise_rng.standard_normal(len(t)), 900, 3200)
    env = np.zeros(len(t))
    for k, off in enumerate((0, 0.011, 0.022)):
        m = t >= off
        env[m] += np.exp(-(t[m] - off) / (0.012 if k < 2 else 0.09))
    return n * env * 0.8

def hat(d=0.06):
    t = tt(d)
    return hp(noise_rng.standard_normal(len(t)), 7500) * np.exp(-t / 0.018)

def crash(d=1.6):
    t = tt(d)
    return hp(noise_rng.standard_normal(len(t)), 4000) * np.exp(-t / 0.45) * 0.5

def impact(d=1.4, depth=1.0):
    t = tt(d)
    f = 30 + 70 * np.exp(-t / 0.12)
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.5)
    body = lp(noise_rng.standard_normal(len(t)), 900) * np.exp(-t / 0.12)
    return (sub + 0.6 * body) * depth

def ping(freq, d=0.18):
    t = tt(d)
    two = np.where(t < 0.06, freq, freq * 1.5)
    return np.sin(2 * np.pi * np.cumsum(two) / SR) * np.exp(-t / 0.05) * 0.35

def tick(freq):
    t = tt(0.06)
    return np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.012) * 0.6

def pluck(freq, d=0.9):
    t = tt(d)
    s = sum(np.sin(2 * np.pi * freq * h * t) * a * np.exp(-t / (0.35 / h)) for h, a in ((1, 1), (2, .45), (3, .22), (4, .1)))
    return s * np.minimum(1, t / 0.003) * 0.5

def bell(freq, d=2.0):
    t = tt(d)
    return sum(np.sin(2 * np.pi * freq * r * t) * a * np.exp(-t / dec) for r, a, dec in ((1, 1, .9), (2.76, .5, .4), (5.4, .25, .2))) * 0.35

def zip_up(d=0.16):
    t = tt(d)
    f = 500 * (4 ** (t / d))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * t / d) * 0.35

def riser(d):
    t = tt(d)
    n = noise_rng.standard_normal(len(t))
    out = np.zeros(len(t))
    seg = int(0.02 * SR)
    for s in range(0, len(t), seg):  # stepped band sweep 400 Hz -> 8 kHz
        k = s / len(t)
        c = 400 * 20 ** k
        out[s : s + seg] = bp(n[s : s + seg + 512], c * .7, min(c * 1.4, 20000))[: len(out[s : s + seg])]
    return out * (t / d) ** 2 * 0.5

def whoosh(d=0.28):
    t = tt(d)
    return bp(noise_rng.standard_normal(len(t)), 500, 5000) * np.sin(np.pi * t / d) ** 2 * 0.45

def pad(freqs, d, gain=0.08):
    t = tt(d)
    s = np.zeros(len(t))
    for f in freqs:
        for det in (-0.12, 0.12):  # detuned saw-ish via 6 harmonics
            s += sum(np.sin(2 * np.pi * f * h * (1 + det / 100) * t) / h for h in range(1, 7))
    s = lp(s, 1400)
    env = np.minimum(1, t / 0.35) * np.minimum(1, (d - t) / 0.3)
    return s * env * gain / len(freqs)

def bass(freq, d):
    t = tt(d)
    return (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)) * np.minimum(1, t / 0.01) * np.minimum(1, (d - t) / 0.05) * 0.35

# Hijaz on D: D Eb F# G A Bb C
def hz(midi):
    return 440 * 2 ** ((midi - 69) / 12)
HIJAZ = [62, 63, 66, 67, 69, 70, 72, 74, 75, 78, 79, 81, 82, 84]  # 14 notes, one per day

# ── arrangement (beat indices mirror index.html)
# Act 1 — chaos 0..B2: notification pings at each word's appear time, rising swell
for i, a in enumerate(chaos_times()):
    place(ping(1500 + (i % 5) * 180), a, 0.9, pan=((i * 37) % 11 - 5) / 6)
place(riser(B(2)), 0, 0.6)
place(impact(), B(2), 1.1)                       # SNAP: chaos collapses to the focus line
place(crash(), B(2), 0.5)
place(impact(1.2, 0.5), B(3))                    # "مشتّت؟"

# Act 2 — groove B4..B28
def groove(b0, b1, claps=True, hats=True):
    for b in range(b0, b1):
        place(kick(), B(b), 0.95)
        if claps and b % 2 == 1:
            place(clap(), B(b), 0.55, pan=0.1)
        if hats:
            place(hat(), B(b) + BEAT / 2, 0.35, pan=-0.3)

groove(4, 28)
CHORDS = {4: [62, 66, 69], 8: [63, 67, 70], 12: [62, 66, 69], 16: [60, 63, 67], 20: [62, 66, 69], 24: [63, 67, 70]}
for b, notes in CHORDS.items():
    place(pad([hz(n) for n in notes], 4 * BEAT), B(b), 1.0)
    for k in range(4):
        env_d = BEAT * 0.85
        place(bass(hz(notes[0] - 24), env_d), B(b + k) + 0.06, 0.9)

for k in range(13):                               # counter ticks ١ -> ١٤ (16ths from B5)
    place(tick(1100 + k * 55), B(5) + k * BEAT / 4, 0.8)
place(crash(), B(8), 0.6)                         # ١٤ lands
place(riser(BEAT), B(10), 0.5)                    # rack focus
place(impact(0.8, 0.6), B(11))
for i, m in enumerate(HIJAZ):                     # tracker: one pluck per day
    place(pluck(hz(m)), B(12) + i * BEAT / 2, 0.8, pan=(i - 6.5) / 10)
place(pad([hz(n) for n in (74, 78, 81)], 1.2, 0.2), B(19), 1.0)
place(crash(), B(19), 0.5)
for k in range(4):                                # habits: whoosh into a hit on each card
    place(whoosh(), B(20 + 2 * k) - 0.26, 0.9)
    place(impact(0.6, 0.5), B(20 + 2 * k))

# Act 3 — statement B28..B32: drums drop, a kick per word, snare roll into the logo
for b in (28, 29, 30):
    place(kick(), B(b), 1.0)
    place(pluck(hz(62 + (b - 28) * 4), 1.2), B(b), 0.6)
for k in range(8):
    place(clap(), B(30) + k * BEAT / 4, 0.2 + 0.06 * k)
place(riser(2 * BEAT), B(30), 0.7)
place(pad([hz(n) for n in (62, 66, 69)], 1.0, 0.1), B(28), 1.0)

# Act 4 — end card B32..B40
place(impact(1.6, 1.2), B(32))
place(crash(2.2), B(32), 0.6)
place(zip_up(), B(33) - 0.08, 1.0)                # the arrow in the S flicks up
place(bell(hz(86)), B(33), 0.9)
groove(34, 38, claps=False)
place(pad([hz(n) for n in (62, 66, 69, 74)], 6 * BEAT, 0.12), B(34), 1.0)
place(impact(0.7, 0.6), B(36))                    # CTA button
for k, m in enumerate((74, 78, 81)):              # social row
    place(pluck(hz(m)), B(37) + k * 0.08, 0.5)
place(impact(1.2, 0.9), B(38))
place(bell(hz(74), 2.0), B(38), 0.8)

# ── mix bus: reverb send, low-cut, gentle saturation, fade tail
ir_t = tt(0.9)
ir = noise_rng.standard_normal(len(ir_t)) * np.exp(-ir_t / 0.25)
ir /= np.sqrt(np.sum(ir ** 2))
mix = []
for ch in (L, R):
    wet = fftconvolve(ch, ir)[:N]
    x = hp(ch + 0.22 * wet, 28)
    x = np.tanh(1.4 * x) / np.tanh(1.4)
    mix.append(x)
mix = np.stack(mix, 1)
fade = int(0.4 * SR)
mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
mix /= np.max(np.abs(mix)) * 1.05
raw = os.path.join(HERE, "score_raw.wav")
wavfile.write(raw, SR, mix.astype(np.float32))

# ── master to -14 LUFS (two-pass loudnorm)
out = os.path.join(HERE, "score.wav")
target = "I=-14:TP=-1.5:LRA=11"
p1 = subprocess.run([FFMPEG, "-hide_banner", "-i", raw, "-af", f"loudnorm={target}:print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p1, re.S).group(0))
af = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
      f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", raw, "-af", af, "-ar", str(SR), "-c:a", "pcm_s16le", out], check=True)
chk = subprocess.run([FFMPEG, "-hide_banner", "-i", out, "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", chk)[-1])
print(f"integrated loudness: {lufs} LUFS")

# ── measure the beat grid from the mastered mix (onset flux -> tempo autocorr -> phase)
_, y = wavfile.read(out)
y = y.astype(np.float64).mean(1) / 32768
hop, win = 480, 2048                               # 10 ms hop
# left-pad so frame k ENDS at k*hop: an onset registers the moment it enters the window
frames = np.lib.stride_tricks.sliding_window_view(np.pad(y, (win, 0)), win)[::hop]
spec = np.abs(np.fft.rfft(frames * np.hanning(win), axis=1))
flux = np.maximum(0, np.diff(np.log1p(spec[:, :200]), axis=0)).sum(1)   # low-band flux (< ~4.7 kHz)
flux = (flux - flux.mean()) / (flux.std() + 1e-9)
fps = SR / hop
lags = np.arange(int(fps * 60 / 160), int(fps * 60 / 90) + 1)
ac = np.array([np.dot(flux[:-l], flux[l:]) for l in lags])
period = lags[np.argmax(ac)] / fps
best, phase = -1e9, 0.0
for ph in np.arange(0, period, 1 / fps):
    idx = np.round((ph + np.arange(0, DUR, period)) * fps).astype(int) - 1   # flux[k] is frame k+1
    idx = idx[(idx >= 0) & (idx < len(flux))]
    s = flux[idx].sum()
    if s > best:
        best, phase = s, ph
beats = [round(phase + k * period, 4) for k in range(int((DUR - phase) / period) + 1) if phase + k * period < DUR]
json.dump({"bpm": round(60 / period, 2), "offset": round(phase, 4), "count": len(beats), "beats": beats,
           "lufs": lufs, "source": "measured from score.wav (spectral-flux onset autocorrelation)"},
          open(os.path.join(HERE, "beats.json"), "w"), indent=1)
print(f"measured {60/period:.2f} BPM, offset {phase:.3f}s, {len(beats)} beats")
