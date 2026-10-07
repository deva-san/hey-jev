"""Quick typed decisions in milliseconds, the way Jev and Laya do them, without a model writing text.

A small sentence encoder (all-MiniLM-L6-v2, int8 ONNX, 23 MB, Apache 2.0, run by the onnxruntime already here) turns
what was said into 384 numbers, and small heads trained on her own past turns (train_decider.py) give a chance for
each question. About 15 ms on this PC. Laya and TypeSafe's Jev were looked at first: Laya needs PyTorch and a
0.6 to 0.8 GB model, takes 0.3 to 0.75 s a question on this CPU, and is near chance without training; the hosted Jev
is paid (OpenCode has a free one for a limited time). This answers in the same shape as their /v1/systemone, so
either can be swapped in later without changing callers.

Settings "decider":
    "off"     not asked
    "shadow"  asked and logged (%LOCALAPPDATA%\\Hey Jev\\decider\\shadow.jsonl), nothing changes (the default)
    "on"      a turn it's sure isn't for her is let go without a model call. It never drops a question she'd
              ask first, never clears the checks for words said without her name, and never acts on its own.

A head only acts above the levels train_decider.py set from held-out turns, where it was right 95% of the time.
"""
import json
import os
import threading
import time

import numpy as np

import settings
import speech

ENCODER = "minilm-l6"  # <models>\minilm-l6: model_quint8_avx2.onnx and tokenizer.json from huggingface.co/sentence-transformers/all-MiniLM-L6-v2
DIM = 384
KINDS = ("follow_up", "other", "cold")  # how a turn reached her, as context for the heads


def folder():
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Hey Jev", "decider")


def mode():
    value = settings.get("decider")
    return value if value in ("off", "on") else "shadow"


def available():
    d = os.path.join(speech.models_dir(), ENCODER)
    return os.path.isfile(os.path.join(d, "model_quint8_avx2.onnx")) and os.path.isfile(os.path.join(d, "tokenizer.json"))


class Encoder:
    """Sentence in, 384 numbers out, the mean of the last layer over its words, made length 1."""

    def __init__(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        d = os.path.join(speech.models_dir(), ENCODER)
        so = ort.SessionOptions()
        so.inter_op_num_threads, so.intra_op_num_threads = 1, 2  # leaves the rest to speech-to-text
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(os.path.join(d, "model_quint8_avx2.onnx"), sess_options=so,
                                            providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(os.path.join(d, "tokenizer.json"))
        self.tokenizer.enable_truncation(64)
        self.lock = threading.Lock()

    def __call__(self, text):
        e = self.tokenizer.encode(str(text))
        ids, mask = np.array([e.ids], np.int64), np.array([e.attention_mask], np.int64)
        with self.lock:
            out = self.session.run(None, {"input_ids": ids, "attention_mask": mask,
                                          "token_type_ids": np.zeros_like(ids)})[0]
        v = (out * mask[..., None]).sum(1)[0] / max(1, mask.sum())
        return (v / (np.linalg.norm(v) or 1.0)).astype(np.float32)


def features(vector, kind):
    """The sentence's numbers, then which way it reached her."""
    return np.concatenate([vector, np.array([kind == k for k in KINDS], np.float32)])


def train_head(x, y, steps=400, l2=1e-3, rate=0.5):
    """Logistic regression by gradient descent: (weights, bias). y is 0 or 1."""
    w, b = np.zeros(x.shape[1], np.float32), 0.0
    for _ in range(steps):
        p = 1 / (1 + np.exp(-(x @ w + b)))
        g = p - y
        w -= rate * (x.T @ g / len(y) + l2 * w)
        b -= rate * float(g.mean())
    return w, b


def predict(head, x):
    return 1 / (1 + np.exp(-(x @ head["w"] + head["b"])))


class Decider:
    def __init__(self):
        self.encoder, self.heads, self.lock = None, {}, threading.Lock()
        self.load()

    def load(self):
        try:
            data = np.load(os.path.join(folder(), "heads.npz"), allow_pickle=False)
            names = {k.split("__")[0] for k in data.files}
            self.heads = {n: {"w": data[f"{n}__w"], "b": float(data[f"{n}__b"]), "hi": float(data[f"{n}__hi"]),
                              "lo": float(data[f"{n}__lo"])} for n in names}
        except (OSError, KeyError, ValueError):
            self.heads = {}

    def ready(self, head):
        return head in self.heads and available()

    def encode(self, text):
        with self.lock:
            if self.encoder is None:
                self.encoder = Encoder()
        return self.encoder(text)

    def decide(self, state, questions):
        """Jev's /v1/systemone shape: state {"said": ..., "kind": ...}, questions {"for_me": {"type": "noul"}}.
        Returns {"answers": {"for_me": {"type": "noul", "noul": 0.97}}, "ms": ...}; questions it has no head for
        are left out."""
        t = time.time()
        x = features(self.encode(state.get("said", "")), state.get("kind", "other"))
        answers = {}
        for name, q in questions.items():
            head = self.heads.get(name)
            if head is not None and q.get("type", "noul") == "noul":
                answers[name] = {"type": "noul", "noul": float(predict(head, x))}
        return {"answers": answers, "ms": int((time.time() - t) * 1000)}

    def for_me(self, said, kind):
        """(chance it's for her, "yes", "no" or None when it isn't sure). None, None without a trained head."""
        if not self.ready("for_me"):
            return None, None
        p = self.decide({"said": said, "kind": kind}, {"for_me": {"type": "noul"}})["answers"]["for_me"]["noul"]
        head = self.heads["for_me"]
        return p, "yes" if p >= head["hi"] else "no" if p <= head["lo"] else None


def log(entry):
    """What it decided and what happened, kept on this PC for training it again."""
    os.makedirs(folder(), exist_ok=True)
    with open(os.path.join(folder(), "shadow.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


_decider = []


def get():
    if not _decider:
        _decider.append(Decider())
    return _decider[0]
