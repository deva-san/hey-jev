"""Her voice on this PC: Kyutai's Pocket TTS (code MIT, weights CC-BY 4.0) through the sherpa-onnx already used for
speech-to-text, so no new package. Free for good and nothing leaves the PC, not even the words. For when Fish's free
voice ends (30 November 2026) or is down, or picked in Settings > Voice.

Measured on this i5-12450H (7 Oct 2026): 0.7 s to load, +600 MB while loaded, the first sentence ready in about 0.5
to 0.8 s (Fish starts in about 1.0 s), three times faster than real time on 2 threads. So it loads when first needed
and unloads after IDLE seconds unused.

The voice comes from a short recording of someone (Pocket clones it): VCTK's speakers p248 and p251, Indian English,
CC-BY 4.0, from Kyutai's tts-voices. With a long recording a very short line ran away into 24 to 37 s of babble, so
it's cut to REF_SECS, and a line is stopped once it runs far longer than its words need (most_secs).
"""
import os
import queue
import threading
import time

import numpy as np
import psutil

import speech

FOLDER = "sherpa-onnx-pocket-tts-int8-2026-01-26"  # github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models, 98 MB
VOICES = {"p248": "vctk-p248.wav", "p251": "vctk-p251.wav"}  # in <models>\voices, from huggingface.co/kyutai/tts-voices
DEFAULT = "p248"
RATE = 24000
REF_SECS = 6.0
IDLE = 300.0  # seconds unused before it's let go, giving back its 600 MB
THREADS = 2


def available(voice=DEFAULT):
    return os.path.isfile(os.path.join(speech.models_dir(), FOLDER, "lm_main.int8.onnx")) and \
        os.path.isfile(_voice_file(voice))


def _voice_file(voice):
    return os.path.join(speech.models_dir(), "voices", VOICES.get(voice, VOICES[DEFAULT]))


def most_secs(text):
    """The longest a line can be before it's taken as running away: about 15 letters a second is normal speech."""
    return 1.5 + 0.12 * len(text)


class Engine:
    def __init__(self):
        self.tts, self.refs, self.used = None, {}, 0.0
        self.lock = threading.Lock()  # one line at a time: sherpa-onnx's TTS isn't for two threads at once
        threading.Thread(target=self._let_go, daemon=True).start()

    def _load(self):
        import sherpa_onnx
        d = os.path.join(speech.models_dir(), FOLDER)
        model = sherpa_onnx.OfflineTtsPocketModelConfig(
            lm_flow=os.path.join(d, "lm_flow.int8.onnx"), lm_main=os.path.join(d, "lm_main.int8.onnx"),
            encoder=os.path.join(d, "encoder.onnx"), decoder=os.path.join(d, "decoder.int8.onnx"),
            text_conditioner=os.path.join(d, "text_conditioner.onnx"), vocab_json=os.path.join(d, "vocab.json"),
            token_scores_json=os.path.join(d, "token_scores.json"))
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(pocket=model, num_threads=THREADS, provider="cpu"),
            max_num_sentences=1)  # the callback gets each sentence as soon as it's made
        self.tts = sherpa_onnx.OfflineTts(config)
        print(f"  her voice on this PC loaded, {psutil.Process().memory_info().rss / 2 ** 20:,.0f} MB in use")

    def _ref(self, voice):
        if voice not in self.refs:
            import soundfile as sf
            a, rate = sf.read(_voice_file(voice), dtype="float32", always_2d=True)
            a = a[:, 0]
            if rate != RATE:  # once here, rather than sherpa-onnx resampling it on every line
                n = int(len(a) * RATE / rate)
                a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
            self.refs[voice] = a[:int(REF_SECS * RATE)]
        return self.refs[voice]

    def make(self, text, voice=DEFAULT, on_audio=None, stop=None):
        """Say text in voice: on_audio(samples, float32 at RATE) gets it a sentence at a time. Returns all of it.
        stop(): True to stop making it, as when she's been stopped mid-line. Asked before it starts too: a sentence
        is made whole before stop is asked, so a line queued behind others was still made in full after a stop."""
        if stop and stop():
            return np.zeros(0, np.float32)
        import sherpa_onnx
        with self.lock:
            if stop and stop():  # stopped while it waited for the line before it
                return np.zeros(0, np.float32)
            if self.tts is None:
                self._load()
            self.used = time.time()
            config = sherpa_onnx.GenerationConfig()
            config.reference_audio, config.reference_sample_rate = self._ref(voice), RATE
            config.num_steps = 5
            most, made = int(most_secs(text) * RATE), [0]

            def got(samples, progress):
                samples = np.asarray(samples, np.float32)
                left = most - made[0]
                if on_audio is not None and left > 0:
                    on_audio(samples[:left])
                made[0] += len(samples)
                return 1 if made[0] < most and not (stop and stop()) else 0  # 0 stops it: running away, or stopped
            audio = self.tts.generate(text, config, callback=got)
            self.used = time.time()
            return np.asarray(audio.samples, np.float32)[:most]

    def _let_go(self):
        while True:
            time.sleep(30)
            with self.lock:
                if self.tts is not None and time.time() - self.used > IDLE:
                    self.tts, self.refs = None, {}


_engine = []
_engine_lock = threading.Lock()


def engine():
    with _engine_lock:
        if not _engine:
            _engine.append(Engine())
        return _engine[0]


def stream(text, voice=DEFAULT, stop=None):
    """A queue that gets her voice for text a sentence at a time (float32 at RATE), then None; an exception instead
    if it failed. Made on its own thread, so it can be under way while another line plays."""
    out = queue.Queue()

    def run():
        try:
            engine().make(text, voice, out.put, stop)
            out.put(None)
        except Exception as exc:
            out.put(exc)
    threading.Thread(target=run, daemon=True).start()
    return out


def to_wav(text, path, voice=DEFAULT):
    import soundfile as sf
    sf.write(path, engine().make(text, voice), RATE, subtype="PCM_16")
