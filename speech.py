"""Hey Jev's ears, all on the CPU, working in small pieces while you talk:

- Silero VAD hears where speech starts and stops, 32 ms at a time.
- Smart Turn, Pipecat's turn-taking model, decides at each pause whether you've finished: from how you said it,
  tone and pace, the way a person hears it, not just from the quiet. Finished: she answers straight away. Not yet:
  she waits for the rest, so a pause mid-sentence doesn't cut you off.
- Parakeet writes the words once the turn is over, in about 0.2 s.

From the end of a command to its text took 0.88 s here when half a second of quiet was the only sign you'd
finished, about 0.65 s now. Nemotron, NVIDIA's streaming speech-to-text, is in Settings too: it writes the words
as you say them, but in Hari's voice it wrote "Hey Jev" as "Hello", so with it a bare greeting gets the chime
(siri.GREETING_ONLY), and it costs more CPU (see STREAM_THREADS). Whisper small.en too.

Every phrase is turned into text and checked for "Hey Jev". A dedicated wake word model was tried first
(sherpa-onnx's 3.3M keyword spotter): it never caught the "Hey Jev" in this PC's own mic recordings, while
Parakeet wrote them as "Hey Joe" and "Hey Jim".

sherpa-onnx runs the speech models and onnxruntime Smart Turn. The models download once on first use into
HEYJEV_MODELS (D:\\HeyJev\\models on this PC, set in .env), or %LOCALAPPDATA%\\Hey Jev\\models.
"""
import hashlib
import os
import shutil
import tarfile
import threading
import time
import urllib.request

import numpy as np

RATE = 16000
RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
NEMOTRON = "sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25"
MODELS = {  # name: (file or folder once downloaded, where it comes from, size for the status line)
    "vad": ("silero_vad.onnx", RELEASES + "silero_vad.onnx", "2 MB"),
    "parakeet": ("sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
                 RELEASES + "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2", "460 MB"),
    "nemotron": (NEMOTRON, RELEASES + NEMOTRON + ".tar.bz2", "460 MB"),  # NVIDIA Open Model License
    "turn": ("smart-turn-v3.2-cpu.onnx", "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/"
             "f766f81d3cfdf7737ac64aad813d91bbfd56bf93/smart-turn-v3.2-cpu.onnx", "9 MB"),  # BSD 2-clause
}
SHA256 = {"turn": "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f"}  # from Hugging Face's LFS
PARAKEET_THREADS = 2  # as quick as 4 on this 12th gen i5 (315 vs 294 ms a command), and half the CPU; 6+ was slower
# Nemotron while someone talks, fed in real time, and its last words once they stop: 4.5 cores and 174 ms at 3
# threads, 2.3 cores and 222 ms at 2, 0.34 cores and 342 ms at 1. Most of it is sherpa-onnx's own onnxruntime
# keeping its helper threads spinning between pieces, which it has no setting for (Turn turns it off for Smart Turn)
STREAM_THREADS = 2
TURN_THREADS = 4  # Smart Turn: 16 ms at 4 threads, 26 at 2, 55 at 1. It only runs at pauses
# Nemotron gives the same words about 0.08 less than Parakeet: 0.88 against 0.97 for clear speech, 0.67 against
# 0.75 for Telugu and Hindi said by Windows' English voices. Moved up by that, so siri.py's 55% and 70% lines, worked
# out on Parakeet with 62 clips from this room, mean the same
SURE_SHIFT = 0.08


class Heard(str):
    """What speech-to-text wrote, and in .sure how sure it was: the average chance it gave its own words, 0 to 1.
    On 62 clips from this PC's room, clear speech came out above 0.9, "Hey Joe" said to her about 0.75, and
    mumbling, Telugu and talk across the room 0.4 to 0.6."""
    sure = 1.0


def heard(text, sure=1.0):
    h = Heard(text)
    h.sure = sure
    return h


def models_dir():
    return os.getenv("HEYJEV_MODELS") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Hey Jev", "models")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def model_path(name, notify=None):
    """Where a model lives, downloading it the first time. A half-finished download never counts as done."""
    local, url, size = MODELS[name]
    folder = models_dir()
    path = os.path.join(folder, local)
    if os.path.exists(path):
        return path
    os.makedirs(folder, exist_ok=True)
    download = os.path.join(folder, os.path.basename(url))
    if not os.path.exists(download):
        if notify:
            notify(f"Downloading the {name} model ({size}), one time\u2026")
        urllib.request.urlretrieve(url, download + ".part")
        if name in SHA256 and _sha256(download + ".part") != SHA256[name]:
            os.remove(download + ".part")
            raise RuntimeError(f"The {name} model didn't download right, it'll try again next time")
        os.replace(download + ".part", download)  # only a finished download gets the real name
    if download == path:
        return path
    staging = path + ".unpacking"
    shutil.rmtree(staging, ignore_errors=True)
    with tarfile.open(download) as tar:
        tar.extractall(staging, filter="data")  # "data" refuses paths that would land outside the folder
    os.replace(os.path.join(staging, local), path)
    shutil.rmtree(staging, ignore_errors=True)
    os.remove(download)
    return path


PAUSE = 0.2  # seconds of quiet that make a pause, where Smart Turn is asked whether you've finished


class Voice:
    """Silero VAD (v4, as sherpa-onnx ships it), run directly: the chance of speech in each 32 ms. Not through
    sherpa-onnx's detector, which waits a quarter of a second to be sure speech has started: in the middle of a turn
    that made a pause look longer than it was, and "Hey Jev, [a breath] open Notepad" came out as two."""
    WINDOW = 512

    def __init__(self, notify=None):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.inter_op_num_threads = so.intra_op_num_threads = 1  # a tiny model, a fraction of a millisecond a window
        self.session = ort.InferenceSession(model_path("vad", notify), sess_options=so,
                                            providers=["CPUExecutionProvider"])
        self.reset()

    def reset(self):
        self.h, self.c = np.zeros((2, 1, 64), np.float32), np.zeros((2, 1, 64), np.float32)
        self.left = np.zeros(0, np.float32)

    def __call__(self, audio):
        """The chance of speech in each whole window of the audio, in order. What's over waits for the next call."""
        x = np.concatenate([self.left, np.asarray(audio, dtype=np.float32)])
        n, out = len(x) // self.WINDOW * self.WINDOW, []
        for i in range(0, n, self.WINDOW):
            p, self.h, self.c = self.session.run(None, {"x": x[None, i:i + self.WINDOW], "h": self.h, "c": self.c})
            out.append(float(p.reshape(-1)[0]))
        self.left = x[n:]
        return out


def end_of_speech(notify=None):
    """The voice detector Listener uses: Silero, 32 ms at a time."""
    return Voice(notify)


def transcriber(engine="parakeet", notify=None):
    """A function from 16 kHz audio to (text, ms), for Parakeet or Whisper small.en, which hear a phrase whole."""
    if engine == "whisper":
        from faster_whisper import WhisperModel
        if notify:
            notify("Loading Whisper\u2026")
        model = WhisperModel("small.en", device="cpu", compute_type="int8")

        def run(audio):
            segs, _ = model.transcribe(audio, language="en", beam_size=1, temperature=0, without_timestamps=True,
                                       condition_on_previous_text=False)
            segs = list(segs)
            sure = float(np.exp(np.mean([s.avg_logprob for s in segs]))) if segs else 1.0
            return " ".join(s.text.strip() for s in segs), sure
    else:
        import sherpa_onnx
        d = model_path("parakeet", notify)
        if notify:
            notify("Loading Parakeet\u2026")
        rec = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=os.path.join(d, "encoder.int8.onnx"), decoder=os.path.join(d, "decoder.int8.onnx"),
            joiner=os.path.join(d, "joiner.int8.onnx"), tokens=os.path.join(d, "tokens.txt"),
            num_threads=PARAKEET_THREADS, model_type="nemo_transducer")

        def run(audio):
            s = rec.create_stream()
            s.accept_waveform(RATE, audio)
            rec.decode_stream(s)
            probs = np.exp(np.asarray(list(getattr(s.result, "ys_log_probs", None) or [0.0]), dtype=np.float32))
            return s.result.text, float(probs.mean())

    lock = threading.Lock()  # push to talk and the open mic can both want it at once

    def transcribe(audio):
        """(text, ms). text is a Heard, a str that also says how sure it is."""
        with lock:
            t = time.time()
            text, sure = run(audio)
        return heard(text.strip(), sure), int((time.time() - t) * 1000)
    return transcribe


class Whole:
    """One turn for Parakeet or Whisper, which hear a phrase whole: the words come once it's over."""
    live = False

    def __init__(self, transcribe):
        self.transcribe, self.parts = transcribe, []

    def feed(self, audio):
        self.parts.append(np.asarray(audio, dtype=np.float32))

    def text(self):
        return ""

    def finish(self, quiet=0.0):
        """(Heard, ms). quiet: seconds of quiet at the end, left out but for the last 0.3."""
        audio = np.concatenate(self.parts) if self.parts else np.zeros(0, np.float32)
        return self.transcribe(audio[:max(0, len(audio) - int(max(0.0, quiet - 0.3) * RATE))])


class Live:
    """One turn for Nemotron: audio goes in as it comes, in pieces of any size, and the words build up while you
    talk, a 0.56 s piece at a time."""
    live = True
    CHUNK, READS = 0.56, 0.65  # seconds the model moves on each time, and reads each time (its metadata: 56, 65 frames)

    def __init__(self, ears):
        self.ears, self.fed = ears, 0
        with ears.lock:
            self.s = ears.rec.create_stream()

    def feed(self, audio):
        with self.ears.lock:
            self.s.accept_waveform(RATE, np.asarray(audio, dtype=np.float32))
            self.fed += len(audio)
            while self.ears.rec.is_ready(self.s):
                self.ears.rec.decode_stream(self.s)

    def text(self):
        """The words so far. The last half second or so is still to come."""
        with self.ears.lock:
            return self.ears.rec.get_result(self.s).strip()

    def finish(self, quiet=0.2):
        """(Heard, ms) once the last words are through. quiet: seconds since the speech stopped. The model often
        writes a word a piece after it hears it, and a piece only goes through once it's whole, so it gets quiet up
        to the end of the piece after the one the speech ended in. With less, "Hey Jev" came out as "H"."""
        t = time.time()
        fed = self.fed / RATE
        need = (int((fed - quiet) / self.CHUNK) + 1) * self.CHUNK + self.READS + 0.03
        with self.ears.lock:
            self.s.accept_waveform(RATE, np.zeros(int(max(0.0, need - fed) * RATE), np.float32))
            self.s.input_finished()
            while self.ears.rec.is_ready(self.s):
                self.ears.rec.decode_stream(self.s)
            r = self.ears.rec.get_result_all(self.s)
        logs = list(r.ys_probs)
        sure = min(1.0, float(np.exp(np.asarray(logs, dtype=np.float64)).mean()) + SURE_SHIFT) if logs else 1.0
        return heard(r.text.strip(), sure), int((time.time() - t) * 1000)


class Ears:
    """Speech-to-text for the open mic and right Alt: session() for one turn, fed as the audio comes, and
    transcribe(audio) for a whole one. engine: parakeet or whisper (once you stop), or nemotron (writes as you
    talk)."""

    def __init__(self, engine="parakeet", notify=None):
        self.engine = engine
        self.live = engine == "nemotron"
        if not self.live:
            self._whole = transcriber(engine, notify)
            return
        import sherpa_onnx
        d = model_path("nemotron", notify)
        if notify:
            notify("Loading Nemotron\u2026")
        # blank_penalty 1: without it the last word went missing now and then ("who directed Iron Man [two]")
        self.rec = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=os.path.join(d, "tokens.txt"), encoder=os.path.join(d, "encoder.int8.onnx"),
            decoder=os.path.join(d, "decoder.int8.onnx"), joiner=os.path.join(d, "joiner.int8.onnx"),
            num_threads=STREAM_THREADS, sample_rate=RATE, feature_dim=128, enable_endpoint_detection=False,
            decoding_method="greedy_search", blank_penalty=1.0)
        self.lock = threading.Lock()  # push to talk and the open mic can both want it at once
        warm = Live(self)  # the first decode is the slow one, better now than on the first command
        warm.feed(np.zeros(RATE, np.float32))
        warm.finish()

    def session(self):
        return Live(self) if self.live else Whole(self._whole)

    def transcribe(self, audio):
        """(Heard, ms) for audio you already have, all of it."""
        s = self.session()
        s.feed(audio)
        return s.finish()


# --------------------------------------------------------------------------- Smart Turn: have you finished?
def _mel_filters(n_fft=400, n_mels=80):
    """Whisper's 80 mel bands (Slaney), the same numbers as librosa and faster-whisper."""
    fftfreqs = np.fft.rfftfreq(n=n_fft, d=1.0 / RATE)
    mels = np.linspace(0.0, 45.245640471924965, n_mels + 2)
    freqs = 200.0 / 3 * mels
    log = mels >= 15.0
    freqs[log] = 1000.0 * np.exp(np.log(6.4) / 27.0 * (mels[log] - 15.0))
    ramps = freqs[:, None] - fftfreqs[None, :]
    fdiff = np.diff(freqs)
    weights = np.maximum(0, np.minimum(-ramps[:-2] / fdiff[:-1, None], ramps[2:] / fdiff[1:, None]))
    return weights * (2.0 / (freqs[2:n_mels + 2] - freqs[:n_mels]))[:, None]


_MEL, _WINDOW = _mel_filters(), np.hanning(401)[:-1]


def _features(audio):
    """What Smart Turn reads: the last 8 s, quiet in front if it's shorter, evened out, as Whisper's log-mel
    spectrogram. Matches transformers' WhisperFeatureExtractor(chunk_length=8) to within 1e-5."""
    x = np.asarray(audio, dtype=np.float64)[-8 * RATE:]
    x = np.pad(x, (8 * RATE - len(x), 0))
    x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
    frames = np.lib.stride_tricks.sliding_window_view(np.pad(x, 200, mode="reflect"), 400)[::160]
    spec = np.abs(np.fft.rfft(frames * _WINDOW, axis=-1)) ** 2
    log = np.log10(np.maximum(_MEL @ spec[:-1].T, 1e-10))
    log = np.maximum(log, log.max() - 8.0)
    return ((log + 4.0) / 4.0).astype(np.float32)[None]


class Turn:
    """Smart Turn v3.2 (Pipecat, BSD 2-clause): has the speaker finished their turn? A Whisper Tiny encoder that
    hears the sound itself, so the pitch falling at the end of a sentence counts, or staying up mid-thought, the
    way a person hears it. 8 MB, 94% right on English in Pipecat's tests, about 20 ms here."""

    def __init__(self, notify=None):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.inter_op_num_threads, so.intra_op_num_threads = 1, TURN_THREADS
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        # its helper threads sleep between runs: by default onnxruntime keeps them spinning, burning CPU for nothing
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(model_path("turn", notify), sess_options=so,
                                            providers=["CPUExecutionProvider"])
        self.finished(np.zeros(RATE, np.float32))  # the first run is the slow one

    def finished(self, audio):
        """The chance, 0 to 1, that they're done, from all of what they've said this turn and the pause after it."""
        return float(self.session.run(None, {"input_features": _features(audio)})[0].reshape(-1)[0])


class Listener:
    """Mic audio in, 32 ms at a time, turns out, as on_phrase(audio, kind, text, ms). kind is one of:

    "dictation"  every turn while dictating
    "armed"      a turn that starts soon after a bare "Hey Jev" (see arm)
    "follow_up"  a turn that starts in the few seconds after she answered, no name needed
    "other"      anything else, which only counts if it has "Hey Jev" in it
    A turn is everything someone says until they've finished: speech-to-text is fed as it comes (ears), and at
    each pause Smart Turn (turn) says whether that was the end. on_words(text, kind) gets the words so far while
    they talk, when the ears write as you go. ms: how long the words took after the pause.
    Time is counted in samples, not on the clock, so a test can feed it faster than real time.
    """

    ON, OFF = 0.5, 0.35  # Silero's chance of speech: a turn starts above ON, and in one, only under OFF is quiet
    START = 2  # windows in a row over ON that start a turn, 64 ms, so a click doesn't
    PRE_ROLL = 0.4  # seconds put back before the speech that started a turn, for a soft start like the H of "Hey"
    KEEP = 45 * RATE  # audio kept, enough for the longest turn and its pre-roll
    MAX_TURN = 15.0  # seconds: a turn this long ends anyway, so a video that never stops still gets checked
    # A turn that's for her (after her name, in a follow-up window, or with her name in the words) may run longer: a
    # long instruction cut at 15 s came back as two turns, and the second, without her name, was ignored
    MAX_TURN_HERS = 40.0
    SHORT = 1.0  # a turn with less speech than this, like a bare "Hey Jev" before the rest, never ends at the first pause
    FINISHED, MAYBE = 0.5, 0.15  # Smart Turn's chance that you're done: over FINISHED, she goes at the first pause
    SETTLE, LONGEST = 0.5, 1.2  # over MAYBE after SETTLE seconds of quiet, and whatever it said after LONGEST

    def __init__(self, vad, ears, on_phrase, on_speech=lambda: None, turn=None, on_words=None, hold_for=None,
                 is_hers=None):
        """hold_for(words so far): True to wait the longest before ending, for words that are only the start.
        is_hers(words so far): True if her name is in them, so a long turn isn't cut at MAX_TURN."""
        self.vad, self.ears, self.on_phrase, self.on_speech, self.turn = vad, ears, on_phrase, on_speech, turn
        self.on_words = on_words or (lambda text, kind: None)
        self.hold_for = hold_for or (lambda words: False)
        self.is_hers = is_hers or (lambda words: False)
        self.dictating = False
        self.reset()

    def reset(self, window=0.0):
        """Start over after a gap in the audio. window: seconds in which a turn counts without the name."""
        self.vad.reset()
        self.pos, self.armed, self.talking, self.run = 0, False, False, 0
        self.window_end = int(window * RATE)
        self.recent, self.recent_start = [], 0  # the last few seconds of blocks, and where the first one starts
        self.speech_start = None  # where the speech going on now began, while someone is talking
        self.session = None  # speech-to-text for the turn going on now
        self.turn_start = self.onset = self.voice = 0  # where the turn's audio starts, its speech, and the last of it
        self.cut = 0  # where the last turn cut at MAX_TURN ended, so the next one doesn't hear any of it again
        self.chance, self.turn_ms, self.words = None, 0, ""
        self.early = None  # (words, ms) of a short turn Parakeet or Whisper wrote at its pause, see feed
        self.ended = (None, 0.0)

    def arm(self, secs):
        """After a bare "Hey Jev": the next phrase is the command, if it starts within secs."""
        self.armed, self.window_end = True, self.pos + int(secs * RATE)

    def open(self, secs):
        """A turn that starts within secs counts without the name, as a follow_up: she decides if it was for her."""
        self.armed, self.window_end = False, self.pos + int(secs * RATE)

    def end(self):
        """The audio stops here, as when she starts talking: a turn waiting in a pause ends now, as if finished,
        rather than being lost when the listener starts over. One cut off while still talking is let go."""
        if self.session is not None and not self.talking:
            self._end()

    def talking_for(self):
        """Seconds the speech going on now has lasted, 0 when nobody is talking."""
        return (self.pos - self.speech_start) / RATE if self.speech_start is not None else 0.0

    def _audio(self, start):
        recent = np.concatenate(self.recent) if self.recent else np.zeros(0, np.float32)
        return recent[max(0, start - self.recent_start):]

    def partial(self, secs=2.5):
        """The start of the turn going on now, up to secs of it, so it can be checked for her name early."""
        if self.session is None:
            return np.zeros(0, dtype=np.float32)
        return self._audio(self.turn_start)[:int(secs * RATE)]

    def state(self):
        """"armed" or "window" while a phrase counts without the name, else None. A turn that began in time keeps it
        until it's over: the popup closed while Hari was still talking, when the window ran out mid-sentence."""
        if (self.onset if self.session is not None else self.pos) >= self.window_end:
            return None
        return "armed" if self.armed else "window"

    def _hers(self):
        """True if the turn going on now is plainly for her, so it's let run to the end of what you're saying."""
        return self.dictating or self._kind() in ("armed", "follow_up") or self.is_hers(self.words)

    def _kind(self):
        if self.dictating:
            return "dictation"
        if self.onset < self.window_end:
            return "armed" if self.armed else "follow_up"
        return "other"

    def _end(self):
        audio, kind, session, early = self._audio(self.turn_start), self._kind(), self.session, self.early
        quiet = (self.pos - self.voice) / RATE
        self.session, self.words, self.talking, self.early = None, "", False, None
        self.ended = (self.chance, quiet)  # why it ended, for the log: Smart Turn's chance and the quiet
        text, ms = early or session.finish(quiet)
        self.on_phrase(audio, kind, text, ms + self.turn_ms)

    def feed(self, block, dictating=False):
        if dictating != self.dictating:
            self.dictating = dictating
            self.reset()
        self.pos += len(block)
        self.recent.append(block)
        while self.pos - self.recent_start - len(self.recent[0]) >= self.KEEP:
            self.recent_start += len(self.recent.pop(0))
        for p in self.vad(block):  # one window a block, from the mic
            self.run = self.run + 1 if p >= self.ON else 0
            if p >= self.ON or (self.session is not None and p >= self.OFF):
                self.voice = self.pos
        if self.session is None:
            if self.run < self.START:
                return
            # a turn begins, with what came just before it
            self.onset = self.pos - self.run * Voice.WINDOW
            self.turn_start = max(self.recent_start, self.cut, self.onset - int(self.PRE_ROLL * RATE))
            self.session, self.chance, self.turn_ms = self.ears.session(), None, 0
            # Nemotron needs a moment of quiet before the speech, or fast speech loses its first word: "Open
            # Notepad" came out as "Notepad", "When will Gemini..." as "Will Gemini...", 4 of 9 sentences said
            # quickly. Talking the instant she stops leaves no audio before it, so quiet is made up to fill
            short = int(self.PRE_ROLL * RATE) - (self.onset - self.turn_start)
            if self.session.live and short > 0:
                self.session.feed(np.zeros(short, np.float32))
            self.session.feed(self._audio(self.turn_start))
            self.on_speech()
        else:
            self.session.feed(block)  # pauses too, so the words keep their timing
        quiet = (self.pos - self.voice) / RATE  # seconds since the last speech
        talking, was = quiet < PAUSE, self.talking
        self.talking = talking
        if talking:
            if not was:
                self.speech_start = self.pos - len(block)
            self.chance = self.early = None  # still talking, so what Smart Turn said or was written no longer counts
        else:
            self.speech_start = None
        if self.session.live:
            words = self.session.text()
            if words != self.words:
                self.words = words
                self.on_words(words, self._kind())
        if talking:
            long_for = self.MAX_TURN_HERS if self._hers() else self.MAX_TURN
            if (self.pos - self.turn_start) / RATE >= long_for:
                # the next turn starts from here: with the speech still counted from before, a TV that never paused
                # started a new turn on every block, each the same 15 s again, 102 in a row in the log
                self.run, self.cut = 0, self.pos
                self._end()
            return
        spoke = (self.voice - self.onset) / RATE  # seconds of the turn with speech in
        if was and self.turn and not self.dictating and spoke >= self.SHORT:  # a pause: have they finished?
            t = time.time()
            try:
                self.chance = self.turn.finished(self._audio(self.turn_start))
            except Exception as exc:
                print(f"  smart turn failed: {exc!r}")
                self.chance = None
            self.turn_ms = int((time.time() - t) * 1000)
        # "Hello" and a pause is the start of "Hello [breath] Jev": ending there cut her name off, 3 times in 3 one
        # evening, so with only a greeting written it waits the longest for the rest
        held = self.hold_for(self.words)
        if quiet >= self.LONGEST or (not held and (
                (self.chance is not None and self.chance >= self.FINISHED) or
                (quiet >= self.SETTLE and (self.chance is None or self.chance >= self.MAYBE)))):
            if not self.session.live and spoke < self.SHORT and quiet < self.LONGEST:
                # Parakeet and Whisper only write once you stop, so a short turn is written here, when it would end
                # anyway, and waits the same if that's only a greeting: "Hello [700 ms] Jev" came out as "Hello." and
                # "Jeff". Anything else ends as soon as before, without being written twice
                self.early = self.early or self.session.finish(quiet)
                if self.hold_for(self.early[0]):
                    return
            self._end()
