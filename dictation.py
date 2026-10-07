"""Dictation from Tatoscription: "Hey Jev, transcribe" records until "stop transcribing", then pastes the text at your cursor.

The audio never leaves the PC: the same local speech model that listens for "stop transcribing" writes the text.
"""
import os, re, json, time

from winplatform import log_path

MAX_SECS = 15 * 60  # stops by itself after this, in case the stop phrase gets missed
HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY = log_path("Hey Jev dictation.jsonl")
START = re.compile(r"^\W*(?:(?:please|can you|could you)\s+)?(?:start\s+)?(?:transcrib\w*|dictat\w*|take notes)"
                   r"(?:\s+(?:this|this meeting|this call|notes|mode|now|please|for me))?\W*$", re.I)

USER_VOCAB = os.path.join(HERE, "vocabulary.json")  # your own words, gitignored
VOCAB = []


def read_vocab():
    path = USER_VOCAB if os.path.exists(USER_VOCAB) else os.path.join(HERE, "vocabulary.example.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_vocab():
    global VOCAB
    VOCAB = [(re.compile(r"\b" + re.escape(alt) + r"\b", re.I), word) for word, alts in read_vocab().items() for alt in alts]


def save_vocab(words):
    """words is {"Word": ["heard as", ...]}, saved to vocabulary.json and used straight away."""
    with open(USER_VOCAB, "w", encoding="utf-8") as f:
        json.dump(words, f, indent=2, ensure_ascii=False)
        f.write("\n")
    load_vocab()


load_vocab()


def fix_vocab(text):
    for rx, word in VOCAB:
        text = rx.sub(word, text)
    return text


class Dictation:
    def __init__(self, names):
        self.stop_rx = re.compile(rf"(?:\b(?:hey|hi|hay|okay|ok)\W+)?(?:\b(?:{names})\W+)?\b(?:stop|end|finish)\W+(?:the\W+)?"
                                  r"(?:transcri|dictat)\w*\W*$", re.I)
        self.active = False

    def start(self):
        self.active, self.started, self.heard = True, time.time(), []

    def timed_out(self):
        return self.active and time.time() - self.started > MAX_SECS

    def add(self, heard):
        """Keep what was heard in this phrase, returns True if it was the stop command."""
        if heard:
            self.heard.append(heard)
        return bool(self.stop_rx.search(heard)) or self.timed_out()

    def finish(self):
        """The whole dictation as one text, minus the stop phrase, also saved to the history."""
        self.active = False
        text = self.stop_rx.sub("", " ".join(self.heard)).strip(" ,")
        text = fix_vocab(text) if text else ""
        if text:
            with open(HISTORY, "a", encoding="utf-8") as f:
                f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "text": text}) + "\n")
        return text
